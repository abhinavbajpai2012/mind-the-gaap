"""The Panel: the object every stage reads from and writes to.

Signal pipelines call `docs()` and push conclusions back with `push()`.
The time-series stage calls `history()`. The run ends with `to_workbooks()`.
Nothing converts between stages because nothing leaves this object.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .classify import DocClass
from .corpus import (DEFAULT_DATA_ROOT, Document, REPO_ROOT, load_challenge_targets,
                     load_documents)
from .extract import DataPoint, Extraction, extract
from .facets import MetricSpec, parse as parse_facets
from .fiscal import FiscalPeriod
from .periods import resolve_all
from .profiler import CompanyProfile, fit

KIND_ALIASES = {
    "transcript": {DocClass.EARNINGS_CALL},
    "call": {DocClass.EARNINGS_CALL},
    "filing": {DocClass.STRUCTURED_RESULT, DocClass.GENERIC_FILING},
    "results": {DocClass.STRUCTURED_RESULT},
    "slide": {DocClass.SLIDE},
    "slides": {DocClass.SLIDE},
}


def period_matches(doc_period: FiscalPeriod, want: FiscalPeriod) -> bool:
    """Is a document's period of record relevant to the requested period?

    A full-year query must reach the annual report, which the company files in
    its Q4 slot (or, for a half-yearly reporter like Hays, its H2 slot). Exact
    equality alone would return nothing for `FY2025`.
    """
    if doc_period == want:
        return True
    if want.quarter is None and want.half is None:
        return doc_period.fy == want.fy and (
            doc_period.quarter == 4 or doc_period.half == 2
            or (doc_period.quarter is None and doc_period.half is None)
        )
    return False


class Undefensible(Exception):
    """Raised when a pipeline pushes a value without citations."""


class NotReported(Exception):
    """The company does not report at the requested granularity."""


class AmbiguousMetric(Exception):
    """More than one distinct value matches; the caller must disambiguate."""


# --------------------------------------------------------------------------
# Value: a float that carries its own evidence
# --------------------------------------------------------------------------
class Value(float):
    """A number that cannot be separated from its provenance."""

    def __new__(cls, value: float, **kw):
        obj = super().__new__(cls, value)
        obj.unit = kw.get("unit", "")
        obj.span = kw.get("span")
        obj.origin = kw.get("origin", "extracted")
        obj.points = tuple(kw.get("points", ()))
        obj.extraction = kw.get("extraction")
        obj.because = kw.get("because", "")
        obj.cites = tuple(kw.get("cites", ()))
        return obj

    @property
    def raw(self) -> DataPoint | None:
        return self.points[0] if self.points else None

    def __repr__(self) -> str:
        head = f"{float(self):g} {self.unit}"
        if self.span:
            head += f" · {self.span}"
        if self.cites:
            head += f" · {self.cites[0]}"
            if len(self.cites) > 1:
                head += f" (corroborated x{len(self.cites)})"
        return head

    def why(self) -> str:
        """Full accepted/rejected trace. This is the defensibility surface."""
        lines = [repr(self), ""]
        if self.origin != "extracted":
            lines += [f"ORIGIN   {self.origin}", f"BECAUSE  {self.because}", ""]
        ex: Extraction | None = self.extraction
        if ex:
            lines.append("ACCEPTED")
            for dp in ex.accepted[:8]:
                lines.append(f"  {dp.cite:<34} {dp.value:>12g}  {dp.quote[:74]}")
            if ex.rejected:
                lines.append("")
                lines.append("REJECTED")
                for tag, reason in ex.rejected[:10]:
                    lines.append(f"  {tag:<34} {reason}")
                if len(ex.rejected) > 10:
                    lines.append(f"  ... and {len(ex.rejected) - 10} more")
            if ex.ambiguities:
                lines += [""] + [f"AMBIGUOUS  {a}" for a in ex.ambiguities]
        elif self.cites:
            lines += ["CITES"] + [f"  {c}" for c in self.cites]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# DocSet
# --------------------------------------------------------------------------
@dataclass
class DocSet:
    company: str
    period: FiscalPeriod | None
    docs: list[Document]
    excluded_docs: list[tuple[str, str]] = field(default_factory=list)
    total: int = 0

    def __iter__(self):
        return iter(self.docs)

    def __len__(self):
        return len(self.docs)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.docs[key]
        for d in self.docs:
            if d.kind == key or key in d.short:
                return d
        raise KeyError(key)

    def text(self) -> str:
        return "\n\n".join(d.body for d in self.docs)

    def cites(self) -> list[str]:
        return [d.short for d in self.docs]

    def paths(self) -> list[Path]:
        return [d.path for d in self.docs]

    def to_signal_input(self, period: str | FiscalPeriod | None = None) -> dict:
        """Arguments for signal_subagents.abc_subagent.SignalInput.

        Returned as a plain dict so the aggregator stays standard-library only;
        the subagent side does `SignalInput(**docset.to_signal_input())`.
        `period` is emitted in the corpus convention ("Q3 2026") that
        SignalInput normalises to.

        `period` is the period being *forecast*, which is not always the period
        these documents belong to — a signal that standardises a company against
        its own past is handed years of calls and asked about one quarter. It
        defaults to this DocSet's period, which is right only when the DocSet is
        the target period's own documents. `Panel.signal_input()` is the usual
        way in and passes it explicitly.

        Each document carries its resolved period and class, so a subagent never
        has to fall back on the corpus's `period:` front matter — the one that
        labels Deere's May 2026 Q2 call "Q3 2026".
        """
        want = FiscalPeriod.parse(period) if isinstance(period, str) else period
        want = want or self.period
        if want is None:
            raise ValueError(
                "to_signal_input() needs a period: pass period=..., or build the "
                "DocSet with one"
            )
        if want.quarter:
            label = f"Q{want.quarter} {want.fy}"
        elif want.half:
            label = f"H{want.half} {want.fy}"
        else:
            label = f"FY {want.fy}"
        return {
            "company": self.company,
            "period": label,
            "relevant_documents": [
                {
                    "path": d.path,
                    "doc_class": d.doc_class,
                    "period": str(d.period) if d.period else None,
                    "published_at": d.published_at.isoformat(),
                }
                for d in self.docs
            ],
        }

    def excluded(self, limit: int = 20) -> list[tuple[str, str]]:
        return self.excluded_docs[:limit]

    def __repr__(self) -> str:
        head = (f"DocSet · {self.company} {self.period or 'any'} · "
                f"{len(self.docs)} of {self.total} documents")
        rows = [
            f"  {d.kind:<12} {d.published_at}  {d.title[:44]:<44} {d.period_confidence:.2f}"
            for d in self.docs[:12]
        ]
        tail = []
        if len(self.docs) > 12:
            tail.append(f"  ... {len(self.docs) - 12} more")
        if self.excluded_docs:
            tail.append(f"  {len(self.excluded_docs)} excluded → .excluded()")
        return "\n".join([head, ""] + rows + tail)


# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
@dataclass
class Target:
    company: str
    ticker: str
    period: FiscalPeriod
    metric_label: str
    units: str
    spec: MetricSpec
    output_file: str
    values: list[Value] = field(default_factory=list)

    @property
    def resolved(self) -> Value | None:
        for v in self.values:
            if v.origin == "resolved" or v.origin == "model":
                return v
        return self.values[0] if len(self.values) == 1 else None


class Panel:
    """One table; every stage reads and writes it."""

    def __init__(self, root: Path | str = DEFAULT_DATA_ROOT):
        self.root = Path(root)
        self.profiles: dict[str, CompanyProfile] = {}
        self._docs: dict[str, list[Document]] = {}
        self.targets: list[Target] = []
        self.frozen_at = "2026-08-14"

    # ---- construction ----------------------------------------------------
    @classmethod
    def challenge(cls, root: Path | str = DEFAULT_DATA_ROOT) -> "Panel":
        p = cls(root)
        p.load()
        for t in load_challenge_targets():
            p.targets.append(
                Target(
                    company=t["company"],
                    ticker=t["ticker"],
                    period=FiscalPeriod.parse(t["period"]),
                    metric_label=t["metric"],
                    units=t["units"],
                    spec=parse_facets(t["metric"], p._segments(t["ticker"]),
                                      unit_hint=t["units"]),
                    output_file=t["output_file"],
                )
            )
        return p

    def load(self) -> "Panel":
        for directory in sorted(d for d in self.root.iterdir() if d.is_dir()):
            docs = load_documents(directory)
            if not docs:
                continue
            profile = fit(docs)
            resolve_all(docs, profile)
            self.profiles[profile.ticker] = profile
            self._docs[profile.ticker] = docs
        return self

    def _segments(self, ticker: str) -> tuple[str, ...]:
        return ()

    def _ticker(self, name: str) -> str:
        n = name.strip().upper().rsplit(":", 1)[-1]
        if n in self.profiles:
            return n
        for t, prof in self.profiles.items():
            if prof.company.upper() == name.strip().upper():
                return t
        raise KeyError(f"unknown company {name!r}; known: {sorted(self.profiles)}")

    # ---- documents -------------------------------------------------------
    def docs(self, company: str, period: str | FiscalPeriod | None = None,
             kind: str | None = None, metric: str | None = None) -> DocSet:
        ticker = self._ticker(company)
        all_docs = self._docs[ticker]
        want = FiscalPeriod.parse(period) if isinstance(period, str) else period

        keep, dropped = [], []
        classes = KIND_ALIASES.get(kind, None) if kind else None
        spec = parse_facets(metric, self._segments(ticker)) if metric else None

        for d in all_docs:
            if want is not None:
                if d.period is None:
                    dropped.append((d.short, f"{d.doc_class} — no period of record"))
                    continue
                if not period_matches(d.period, want):
                    dropped.append((d.short, f"period {d.period}"))
                    continue
            if classes and d.doc_class not in classes:
                dropped.append((d.short, f"class {d.doc_class} != {kind}"))
                continue
            if spec is not None and spec.concept:
                if not self._mentions(d, spec):
                    dropped.append((d.short, f"does not state {spec}"))
                    continue
            keep.append(d)

        keep.sort(key=lambda d: (d.published_at, d.kind))
        return DocSet(company=ticker, period=want, docs=keep,
                      excluded_docs=dropped, total=len(all_docs))

    def signal_input(self, company: str, period: str | FiscalPeriod,
                     kind: str | None = "transcript",
                     as_of: str | date | None = None) -> dict:
        """Documents for a signal subagent forecasting `period`, with its history.

        `docs(company, period)` is a hard filter and returns that period alone —
        for ADI FY2026Q2, two transcripts. A signal that standardises a company
        against its own past needs more than that: hand the call-tone signal one
        quarter and every channel abstains, correctly and uselessly. So this
        returns *every* document of `kind` for the company, and carries `period`
        separately as the period being forecast. Subagents select within what
        they are given; this decides what is on the table.

        `as_of` drops documents published on or after that date. The twelve
        challenge targets do not need it — the corpus is frozen 2026-08-14 and
        none of those prints have happened — but a backtest of an already-reported
        period does, or the signal reads the answer off the call that announced it.
        """
        cutoff = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        found = self.docs(company, kind=kind)
        keep, dropped = [], list(found.excluded_docs)
        for d in found:
            if cutoff and d.published_at >= cutoff:
                dropped.append((d.short, f"published {d.published_at} >= as_of {cutoff}"))
                continue
            keep.append(d)
        return DocSet(company=found.company, period=None, docs=keep,
                      excluded_docs=dropped, total=found.total).to_signal_input(period)

    def _mentions(self, doc: Document, spec: MetricSpec) -> bool:
        from .facets import _lexicons

        concepts, _ = _lexicons()
        surfaces = concepts.get(spec.concept, [])
        low = doc.body.casefold()
        return any(s in low for s in surfaces)

    # ---- values ----------------------------------------------------------
    def value(self, company: str, period: str | FiscalPeriod, metric: str,
              units: str | None = None, strict: bool = True) -> Value:
        ticker = self._ticker(company)
        profile = self.profiles[ticker]
        want = FiscalPeriod.parse(period) if isinstance(period, str) else period
        spec = parse_facets(metric, self._segments(ticker), unit_hint=units)

        if profile.calendar.granularity == "HALF_YEARLY" and want.quarter in (2, 4):
            raise NotReported(
                f"{profile.company} reports H1/FY; Q{want.quarter} carries no "
                f"{metric} disclosure. Nearest: "
                f"FY{want.fy}{'H1' if want.quarter == 2 else ''}"
            )

        docset = self.docs(company, want)
        ex = extract(docset.docs, spec, want, profile, self._segments(ticker))
        if not ex.accepted:
            raise NotReported(
                f"no cited value for {metric} · {ticker} {want} "
                f"({len(docset)} docs searched, {len(ex.rejected)} cells rejected)"
            )
        if ex.ambiguities and strict:
            raise AmbiguousMetric(ex.ambiguities[0])

        best = ex.accepted[0]
        cites = []
        for dp in ex.accepted:
            if dp.cite not in cites:
                cites.append(dp.cite)
        return Value(best.value, unit=best.unit, span=best.span, points=tuple(ex.accepted),
                     extraction=ex, cites=cites)

    def __getitem__(self, key) -> Value:
        company, period, metric = key
        return self.value(company, period, metric)

    def history(self, company: str, metric: str, units: str | None = None,
                periods: int = 12) -> list[tuple[FiscalPeriod, Value]]:
        ticker = self._ticker(company)
        profile = self.profiles[ticker]
        quarterly = profile.calendar.granularity != "HALF_YEARLY"
        seen = sorted(
            {d.period for d in self._docs[ticker]
             if d.period and (d.period.quarter if quarterly else True)},
            reverse=True,
        )
        out = []
        # walk back as far as needed: older filings format differently and not
        # every period yields a citable value, so a fixed window under-fills.
        for p in seen:
            try:
                out.append((p, self.value(ticker, p, metric, units, strict=False)))
            except (NotReported, AmbiguousMetric):
                continue
            if len(out) >= periods:
                break
        return list(reversed(out))

    # ---- pipelines write in ---------------------------------------------
    def push(self, company: str, period: str | FiscalPeriod, metric: str,
             value: float, origin: str, because: str = "",
             cites: list[str] | None = None, unit: str = "") -> Value:
        if not cites:
            raise Undefensible(
                f"push({company}, {period}, {metric!r}) has no cites. Every data "
                f"point must be defensible; pass cites=docset.cites()."
            )
        ticker = self._ticker(company)
        want = FiscalPeriod.parse(period) if isinstance(period, str) else period
        v = Value(value, unit=unit, origin=origin, because=because, cites=tuple(cites))
        for t in self.targets:
            if t.ticker == ticker and t.period == want and (
                t.metric_label.casefold() == metric.casefold()
            ):
                t.values.append(v)
                return v
        self.targets.append(
            Target(company=ticker, ticker=ticker, period=want, metric_label=metric,
                   units=unit, spec=parse_facets(metric), output_file="",
                   values=[v])
        )
        return v

    def resolve(self, company: str, period, metric: str, value: float,
                because: str, cites: list[str]) -> Value:
        v = self.push(company, period, metric, value, origin="resolved",
                      because=because, cites=cites)
        return v

    # ---- reporting -------------------------------------------------------
    def gaps(self) -> list[Target]:
        return [t for t in self.targets if t.resolved is None]

    def audit(self) -> str:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out = [f"# Aggregator run · {stamp}", "",
               f"corpus: {self.root}", f"frozen: {self.frozen_at}", ""]
        for t in self.targets:
            out.append(f"## {t.ticker} · {t.period} · {t.metric_label} ({t.units})")
            if not t.values:
                out.append("  UNFILLED")
            for v in t.values:
                out.append(f"  {v!r}   origin={v.origin}")
                if v.because:
                    out.append(f"    because: {v.because}")
                for c in v.cites[:6]:
                    out.append(f"    cite: {c}")
            out.append("")
        return "\n".join(out)

    def to_dict(self) -> list[dict]:
        rows = []
        for t in self.targets:
            v = t.resolved
            rows.append({
                "ticker": t.ticker, "period": str(t.period), "metric": t.metric_label,
                "units": t.units, "value": float(v) if v is not None else None,
                "origin": v.origin if v is not None else None,
                "cites": list(v.cites) if v is not None else [],
                "candidates": len(t.values),
            })
        return rows

    def to_csv(self, path: str | Path | None = None) -> str:
        head = "ticker,period,metric,units,value,origin,candidates"
        lines = [head]
        for r in self.to_dict():
            val = "" if r["value"] is None else f"{r['value']:g}"
            lines.append(f'{r["ticker"]},{r["period"]},"{r["metric"]}",{r["units"]},'
                         f'{val},{r["origin"] or ""},{r["candidates"]}')
        text = "\n".join(lines)
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def __repr__(self) -> str:
        filled = sum(1 for t in self.targets if t.resolved is not None)
        head = (f"Panel · {len(self.profiles)} companies · {len(self.targets)} targets "
                f"· corpus frozen {self.frozen_at}")
        rows = ["", "  COMPANY  PERIOD      METRIC                              VALUE  ORIGIN"]
        for t in self.targets:
            v = t.resolved
            val = f"{float(v):>10g}" if v is not None else f"{'—':>10}"
            org = v.origin if v is not None else ("—" if not t.values
                                                  else f"{len(t.values)} disagree")
            rows.append(f"  {t.ticker:<8} {str(t.period):<11} {t.metric_label[:33]:<34}"
                        f"{val}  {org}")
        rows.append("")
        rows.append(f"  {len(self.targets)} targets · {filled} filled · "
                    f"{len(self.gaps())} gaps  →  p.gaps()")
        return "\n".join([head] + rows)
