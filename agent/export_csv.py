"""Corpus -> ML-ready CSVs, one directory per company.

Extraction is deterministic, not model-driven. Every row is produced by the
same table parser the forecasts already rely on, so a cell in a CSV can be
traced to a file and a line, and no value can be invented. (The hand-made
Home Depot CSV in the corpus carries `net_sales_usd_m = 100` on a 10-K row,
against an actual near 83,000 — that is the failure mode this avoids.)

Outputs per company, in output/<company>/:

  metrics_long.csv        tidy: one row per (period, metric, source cell)
  metrics_wide.csv        pivoted: one row per fiscal period, one column per metric
  categories_master.csv   per segment/category: sales, margin, operating profit
  guidance.csv            forward-looking statements, with the period they concern
  call_signals.csv        per earnings call: tone channels from the call-tone subagent
  document_inventory.csv  every document, its class and resolved period
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from .aggregator.classify import DocClass, TABLE_BEARING
from .aggregator.corpus import REPO_ROOT
from .aggregator.facets import parse as parse_facets
from .aggregator.panel import Panel
from .aggregator.tables import parse_tables
from .aggregator.units import parse_cell

OUTPUT_ROOT = REPO_ROOT / "output"

#: sentences that state a forward-looking figure
GUIDANCE_RE = re.compile(
    r"\b(expect|expects|expected|outlook|guidance|guide|guiding|anticipate|forecast|"
    r"full[- ]year|for fiscal|we now see|targeting)\b", re.I)
NUMBER_IN_SENTENCE = re.compile(r"[-+]?[\d,]+\.?\d*\s*(?:%|percent|billion|million|bps)?")

SLUG = re.compile(r"[^a-z0-9]+")

#: a column reporting movement, not a level. Its cells often carry no % sign
#: at all ("| 25 |" under a header of "Change"), so the header is the only
#: reliable way to keep a growth figure out of a revenue series.
CHANGE_HEADER_RE = re.compile(r"%|\bchange\b|\bgrowth\b|\bvs\b|\bbps\b|\blfl\b", re.I)


def _slug(text: str) -> str:
    return SLUG.sub("_", (text or "").casefold()).strip("_")


def _metric_key(spec, row_label: str) -> str:
    """Stable column name for a metric, built from its facets."""
    bits = [spec.concept or _slug(row_label)[:40]]
    if spec.adjustment:
        bits.append(spec.adjustment)
    if spec.share_basis:
        bits.append(spec.share_basis)
    if spec.statistic not in ("level",):
        bits.append(spec.statistic)
    if spec.scope:
        bits.append(_slug(spec.scope)[:28])
    return "_".join(_slug(b) for b in bits if b)


# ---------------------------------------------------------------------------
def collect_long(panel: Panel, ticker: str) -> list[dict]:
    """Every numeric cell we can attribute to a metric and a period."""
    profile = panel.profiles[ticker]
    segments = panel._segments(ticker)
    rows: list[dict] = []
    seen: set[tuple] = set()

    for doc in panel._docs[ticker]:
        if doc.doc_class not in TABLE_BEARING:
            continue
        for table in parse_tables(doc, profile):
            for row in table.rows:
                spec = parse_facets(row.effective_label, segments)
                if not spec.concept:
                    continue
                scope = spec.scope
                if scope is None and table.scope_label and segments:
                    if any(_slug(table.scope_label) == _slug(s) for s in segments):
                        scope = table.scope_label
                key = _metric_key(spec, row.label)

                for col in table.columns:
                    if col.index == 0 or col.index >= len(row.cells) or col.span is None:
                        continue
                    span = col.span
                    if span.fiscal is None or span.months == 0:
                        continue
                    if CHANGE_HEADER_RE.search(col.header or ""):
                        continue
                    parsed = parse_cell(row.cells[col.index], table.units,
                                        per_share=spec.is_per_share)
                    if parsed is None:
                        continue
                    value, unit = parsed
                    # A "% Change" column sits beside every figure and carries a
                    # period, so without this guard a level metric collects the
                    # change column's 7.0 instead of the 2,880 it belongs to.
                    if spec.unit_class == "currency_abs" and unit in ("pct", "bps"):
                        continue
                    if spec.unit_class == "percent" and unit not in ("pct", "bps"):
                        continue
                    if spec.unit_class == "per_share" and unit in ("pct", "bps"):
                        continue
                    # one value per (period, duration, metric, scope, value)
                    dedup = (str(span.fiscal), span.months, key, _slug(scope or ""),
                             round(value, 6), unit)
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    rows.append({
                        "company": profile.company, "ticker": ticker,
                        "fiscal_period": str(span.fiscal),
                        "fiscal_year": span.fiscal.fy,
                        "fiscal_quarter": span.fiscal.quarter or "",
                        "fiscal_half": span.fiscal.half or "",
                        "period_months": span.months,
                        "period_end": span.end_date.isoformat() if span.end_date else "",
                        "metric_key": key,
                        "concept": spec.concept,
                        "adjustment": spec.adjustment or "",
                        "share_basis": spec.share_basis or "",
                        "statistic": spec.statistic,
                        "scope": scope or "",
                        "value": round(value, 6),
                        "unit": unit,
                        "row_label": row.raw_label,
                        "doc_class": doc.doc_class,
                        "doc_kind": doc.kind,
                        "published_at": doc.published_at.isoformat(),
                        "source_file": str(doc.path.relative_to(REPO_ROOT)),
                        "line_no": row.line_no,
                        # same ranking the forecaster uses: a headline summary
                        # row in the press release beats a same-named line
                        # buried in a cash-flow schedule. Without it the
                        # "revenue" column mixes group net sales with every
                        # incidental revenue line in the filing.
                        "_rank": (len(spec.residual),
                                  0 if table.units is not None else 1,
                                  0 if "8k" in doc.kind else
                                  1 if doc.kind == "slide" else
                                  2 if "10q" in doc.kind or "10k" in doc.kind else 3,
                                  row.line_no),
                    })
    return rows


def pivot_wide(long_rows: list[dict], months: int) -> tuple[list[str], list[dict]]:
    """One row per fiscal period, one column per metric — the modelling table.

    Where a metric appears more than once for a period, the modal value wins:
    the same figure is usually printed in the press release and again in the
    10-Q, and agreement across documents is the signal that it is right.
    """
    by_period: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    meta: dict[str, dict] = {}
    for r in long_rows:
        if r["period_months"] != months or r["scope"]:
            continue
        by_period[r["fiscal_period"]][r["metric_key"]].append(
            (r.get("_rank", (9, 9, 9, 9)), r["value"]))
        meta.setdefault(r["fiscal_period"], {
            "fiscal_period": r["fiscal_period"], "fiscal_year": r["fiscal_year"],
            "fiscal_quarter": r["fiscal_quarter"], "period_end": r["period_end"],
        })

    keys = sorted({k for p in by_period.values() for k in p})
    out = []
    for period, metrics in by_period.items():
        row = dict(meta[period])
        for k in keys:
            vals = metrics.get(k, [])
            if not vals:
                row[k] = ""
                continue
            row[k] = _consensus(vals)
        out.append(row)
    out.sort(key=lambda r: (r["fiscal_year"], r["fiscal_quarter"] or 5))
    header = ["fiscal_period", "fiscal_year", "fiscal_quarter", "period_end"] + keys
    return header, out


def _consensus(ranked: list[tuple]) -> float:
    """The value for a metric in a period: best-ranked source, then agreement.

    Rank first, because "revenue" matches the group's net sales in the results
    summary AND every incidental revenue line deeper in the filing; a plain
    vote across all of them returns neither. Among sources of equal rank the
    modal value wins, since the same figure printed in both the press release
    and the 10-Q is the one that is right.
    """
    if not ranked:
        return ""
    best = min(r for r, _ in ranked)
    vals = [v for r, v in ranked if r[:3] == best[:3]] or [v for _, v in ranked]
    counts = defaultdict(int)
    for v in vals:
        counts[round(v, 4)] += 1
    return max(counts.items(), key=lambda kv: (kv[1], -abs(kv[0])))[0]


def categories_master(long_rows: list[dict]) -> list[dict]:
    """Per category/segment: sales, operating profit, margin — the analyst's split.

    Revenue is forecast category by category and summed, so the category table
    is the object that method operates on.
    """
    grouped: dict[tuple, dict] = {}
    for r in long_rows:
        if not r["scope"]:
            continue
        k = (r["fiscal_period"], r["period_months"], r["scope"])
        g = grouped.setdefault(k, {
            "company": r["company"], "ticker": r["ticker"],
            "fiscal_period": r["fiscal_period"], "fiscal_year": r["fiscal_year"],
            "fiscal_quarter": r["fiscal_quarter"], "period_months": r["period_months"],
            "period_end": r["period_end"], "category": r["scope"],
            "net_sales": "", "operating_profit": "", "operating_margin_pct": "",
            "unit": "", "sources": set(),
        })
        c, stat = r["concept"], r["statistic"]
        if c == "revenue" and stat == "level" and g["net_sales"] == "":
            g["net_sales"], g["unit"] = r["value"], r["unit"]
        elif c == "operating_profit" and stat == "level" and g["operating_profit"] == "":
            g["operating_profit"] = r["value"]
        elif c in ("operating_margin",) or (c == "operating_profit" and stat != "level"):
            if g["operating_margin_pct"] == "":
                g["operating_margin_pct"] = r["value"]
        g["sources"].add(f"{Path(r['source_file']).name}:{r['line_no']}")

    out = []
    for g in grouped.values():
        # price x volume is not disclosed, but mix is derivable and is the
        # lever an analyst actually moves
        g["sources"] = "; ".join(sorted(g["sources"])[:3])
        out.append(g)
    # sales mix within each period
    totals: dict[tuple, float] = defaultdict(float)
    for g in out:
        if isinstance(g["net_sales"], float):
            totals[(g["fiscal_period"], g["period_months"])] += g["net_sales"]
    for g in out:
        t = totals.get((g["fiscal_period"], g["period_months"]), 0)
        g["sales_mix_pct"] = round(g["net_sales"] / t * 100, 2) \
            if t and isinstance(g["net_sales"], float) else ""
    out.sort(key=lambda r: (r["fiscal_year"], r["fiscal_quarter"] or 5, r["category"]))
    return out


def guidance_rows(panel: Panel, ticker: str, limit_docs: int = 60) -> list[dict]:
    """Forward-looking sentences carrying a number, with the doc's own period.

    Guidance for the next quarter is published in this quarter's release, so
    the period recorded is the document's, and the statement points forward
    from it.
    """
    profile = panel.profiles[ticker]
    docs = [d for d in panel._docs[ticker]
            if d.doc_class in (DocClass.STRUCTURED_RESULT, DocClass.EARNINGS_CALL)]
    docs.sort(key=lambda d: d.published_at, reverse=True)
    out = []
    for doc in docs[:limit_docs]:
        for i, line in enumerate(doc.lines, start=1):
            s = line.strip()
            if len(s) < 40 or s.startswith("|") or not GUIDANCE_RE.search(s):
                continue
            nums = [n for n in NUMBER_IN_SENTENCE.findall(s) if any(c.isdigit() for c in n)]
            if not nums:
                continue
            out.append({
                "company": profile.company, "ticker": ticker,
                "published_at": doc.published_at.isoformat(),
                "stated_in_period": str(doc.period) if doc.period else "",
                "doc_class": doc.doc_class, "doc_kind": doc.kind,
                "figures": " | ".join(nums[:6]),
                "quote": s[:400],
                "source_file": str(doc.path.relative_to(REPO_ROOT)),
                "line_no": i,
            })
    return out[:4000]


def call_signals(panel: Panel, ticker: str) -> list[dict]:
    """Call-tone channels per forecastable period, from the signal subagent."""
    try:
        from .signal_subagents.abc_subagent import SignalInput
        from .signal_subagents.sentiment import SentimentSignal
    except Exception:
        return []
    periods = sorted({d.period for d in panel._docs[ticker]
                      if d.period and d.doc_class == DocClass.EARNINGS_CALL},
                     key=lambda p: p.sort_key)
    out = []
    for p in periods[-24:]:
        try:
            payload = panel.signal_input(ticker, p)
            res = SentimentSignal().run(SignalInput(**payload)).model_dump()
        except Exception:
            continue
        out.append({
            "company": panel.profiles[ticker].company, "ticker": ticker,
            "fiscal_period": str(p),
            "as_of_call": res.get("as_of_call") or "",
            "n_history": res.get("n_history", 0), "n_baseline": res.get("n_baseline", 0),
            "qa_neg": res.get("qa_neg") or "", "qa_neg_ord": res.get("qa_neg_ord", ""),
            "qa_neg_z": res.get("qa_neg_z", ""),
            "qa_neg_change": res.get("qa_neg_change") or "",
            "qa_neg_change_ord": res.get("qa_neg_change_ord", ""),
            "uncertainty": res.get("uncertainty") or "",
            "uncertainty_ord": res.get("uncertainty_ord", ""),
            "guidance_language": res.get("guidance_language") or "",
            "guidance_language_ord": res.get("guidance_language_ord", ""),
        })
    return out


def inventory(panel: Panel, ticker: str) -> list[dict]:
    return [{
        "company": panel.profiles[ticker].company, "ticker": ticker,
        "published_at": d.published_at.isoformat(),
        "doc_class": d.doc_class, "doc_kind": d.kind,
        "resolved_period": str(d.period) if d.period else "",
        "period_confidence": d.period_confidence,
        "corpus_period_field": d.frontmatter_period or "",
        "title": d.title[:160],
        "source_file": str(d.path.relative_to(REPO_ROOT)),
    } for d in sorted(panel._docs[ticker], key=lambda d: d.published_at, reverse=True)]


# ---------------------------------------------------------------------------
def write_csv(path: Path, rows: list[dict], header: list[str] | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    header = header or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def export_company(panel: Panel, ticker: str,
                   out_root: Path = OUTPUT_ROOT) -> dict[str, int]:
    profile = panel.profiles[ticker]
    out = out_root / _slug(profile.company)
    long_rows = collect_long(panel, ticker)
    quarterly = profile.calendar.granularity != "HALF_YEARLY"
    wide_months = 3 if quarterly else 6

    hdr_q, wide_q = pivot_wide(long_rows, wide_months)
    hdr_a, wide_a = pivot_wide(long_rows, 12)

    counts = {
        "metrics_long": write_csv(out / "metrics_long.csv", long_rows),
        "metrics_wide": write_csv(out / "metrics_wide.csv", wide_q, hdr_q),
        "metrics_wide_annual": write_csv(out / "metrics_wide_annual.csv", wide_a, hdr_a),
        "categories_master": write_csv(out / "categories_master.csv",
                                       categories_master(long_rows)),
        "guidance": write_csv(out / "guidance.csv", guidance_rows(panel, ticker)),
        "call_signals": write_csv(out / "call_signals.csv", call_signals(panel, ticker)),
        "document_inventory": write_csv(out / "document_inventory.csv",
                                        inventory(panel, ticker)),
    }
    return counts


def export_all(panel: Panel, out_root: Path = OUTPUT_ROOT) -> dict[str, dict[str, int]]:
    return {t: export_company(panel, t, out_root) for t in sorted(panel.profiles)}
