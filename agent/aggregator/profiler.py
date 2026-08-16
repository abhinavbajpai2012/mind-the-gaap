"""Derive a company's reporting profile from its documents.

Nothing here is hand-authored per company. Point it at a directory of corpus
documents and it works out the fiscal calendar, the fiscal-year label offset,
the reporting granularity and the reporting lag, then certifies itself against
held-out evidence.

Why not simply count "fiscal YYYY" mentions? Because Deere's Q4 release leads
with next-year guidance, so forward-looking text outvotes the results being
reported and the calendar comes out backwards. Labels are commentary; period
end dates are facts. Evidence is ranked accordingly.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .classify import DocClass
from .corpus import Document, load_documents
from .fiscal import FiscalCalendar, Granularity, parse_end_date

#: quarter-word bound to a year, e.g. "Fiscal Third Quarter 2025"
QUARTER_YEAR_RES = (
    re.compile(r"\b(?:fiscal\s+)?(first|second|third|fourth)\s+quarter\s+(?:of\s+)?"
               r"(?:fiscal\s+)?(?:year\s+)?(\d{4})", re.I),
    re.compile(r"\bfiscal\s+(?:year\s+)?(\d{4})\s+(first|second|third|fourth)\s+quarter", re.I),
    re.compile(r"\bq([1-4])\s*(?:fy|fiscal)\s*(\d{2,4})", re.I),
)
#: "year ended 30 June 2025" / "year ended February 1, 2026"
YEAR_ENDED_RE = re.compile(r"\b(?:year|full[- ]year)\s+ended\s+([^,\n|]{3,20},?\s*\d{4})", re.I)
PERIOD_ENDED_RE = re.compile(
    r"\b(?:quarter|period|year|months)\s+ended\s+([A-Za-z0-9][^,\n|]{2,20},?\s*\d{4})", re.I
)
WORD_Q = {"first": 1, "second": 2, "third": 3, "fourth": 4}

HEAD_LINES = 80


@dataclass
class CompanyProfile:
    """A derived reporting profile. Every field carries its own confidence."""

    ticker: str
    company: str
    calendar: FiscalCalendar
    fiscal_year_end_month: int | None = None
    reporting_lag_days: int | None = None
    n_documents: int = 0
    n_tokened: int = 0
    confidence: dict[str, float] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)
    selftest: tuple[int, int] = (0, 0)
    pins: dict = field(default_factory=dict)

    # ---- overrides -------------------------------------------------------
    def pin(self, **kwargs) -> "CompanyProfile":
        """Pin a derived field. Contradicting strong evidence warns, never silently wins."""
        for key, value in kwargs.items():
            if key == "fy_offset":
                if self.confidence.get("fy_offset", 0) > 0.9 and value != self.calendar.fy_offset:
                    self.unknown.append(
                        f"PIN CONFLICT fy_offset: pinned {value} over derived "
                        f"{self.calendar.fy_offset} (confidence "
                        f"{self.confidence['fy_offset']:.2f})"
                    )
                object.__setattr__(self.calendar, "fy_offset", dict(value))
            elif key == "report_months":
                object.__setattr__(self.calendar, "report_months", dict(value))
            elif key == "granularity":
                object.__setattr__(self.calendar, "granularity", value)
            else:
                setattr(self, key, value)
            self.pins[key] = value
        return self

    # ---- reporting -------------------------------------------------------
    def report(self) -> str:
        cal = self.calendar
        months = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                  7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
        slots = " · ".join(
            f"Q{s} {months[m]}" for s, m in sorted(cal.report_months.items())
        )
        offs = ", ".join(f"Q{s}: {o:+d}" for s, o in sorted(cal.fy_offset.items())) or "none"
        ok, total = self.selftest
        out = [
            f"CompanyProfile · {self.ticker} · derived from {self.n_documents} documents",
            "",
            f"  fiscal year end   {months.get(self.fiscal_year_end_month, '?')}"
            f"{'':<18}conf {self.confidence.get('fiscal_year_end', 0):.2f}",
            f"  report months     {slots}",
            f"  FY label offset   {offs:<32}conf {self.confidence.get('fy_offset', 0):.2f}",
            f"  granularity       {cal.granularity:<32}conf {self.confidence.get('granularity', 0):.2f}",
            f"  reporting lag     {self.reporting_lag_days} days (median)",
            "",
            f"  SELF-TEST  predicted period == filename token on {ok}/{total} docs   "
            + ("PASS" if total and ok == total else "REVIEW"),
        ]
        if self.unknown:
            out += ["", f"  UNKNOWN ({len(self.unknown)})"]
            out += [f"    {u}" for u in self.unknown]
        return "\n".join(out)

    def __repr__(self) -> str:
        return self.report()


def _head(doc: Document) -> str:
    return "\n".join(doc.lines[:HEAD_LINES])


def _labelled_fy(doc: Document) -> tuple[int, int] | None:
    """Extract (quarter, fiscal_year) where the label is bound to a quarter word.

    Binding is what makes this safe: a bare 'fiscal 2026' anywhere in a Deere Q4
    release is usually guidance, not the period being reported.
    """
    text = doc.title + "\n" + _head(doc)
    for rx in QUARTER_YEAR_RES:
        m = rx.search(text)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        if a.isdigit() and not b.isdigit():
            year, word = a, b
        elif b.isdigit() and not a.isdigit():
            word, year = a, b
        elif a.isdigit() and b.isdigit():
            word, year = a, b
        else:
            continue
        q = WORD_Q.get(str(word).lower()) or (int(word) if str(word).isdigit() else None)
        y = int(year)
        if y < 100:
            y += 2000
        if q and 1 <= q <= 4 and 1990 < y < 2100:
            return q, y
    return None


def fit(source: Path | str | list[Document], ticker: str | None = None) -> CompanyProfile:
    """Derive a reporting profile from a directory of documents (or a doc list)."""
    docs = load_documents(source) if not isinstance(source, list) else list(source)
    if not docs:
        raise ValueError(f"no documents found for profiling: {source}")

    ticker = ticker or Counter(d.ticker for d in docs if d.ticker).most_common(1)[0][0]
    ticker = ticker.rsplit(":", 1)[-1]
    company = Counter(d.company for d in docs if d.company).most_common(1)[0][0]

    tokened = [d for d in docs if d.facts.token_slot]
    conf: dict[str, float] = {}
    unknown: list[str] = []

    # --- report months: slot -> modal publication month -------------------
    months_by_slot: dict[int, Counter] = defaultdict(Counter)
    for d in tokened:
        months_by_slot[d.facts.token_slot][d.published_at.month] += 1
    report_months, month_conf = {}, []
    for slot, counter in months_by_slot.items():
        month, n = counter.most_common(1)[0]
        report_months[slot] = month
        month_conf.append(n / sum(counter.values()))
    conf["report_months"] = min(month_conf) if month_conf else 0.0

    # --- granularity ------------------------------------------------------
    half_tokens = sum(1 for d in tokened if d.facts.period_token in ("h1", "h2"))
    q_results = sum(
        1 for d in tokened
        if d.facts.period_token in ("q1", "q2", "q3", "q4")
        and re.search(r"10-?q|10-?k|8-?k", d.kind)
    )
    granularity = Granularity.HALF_YEARLY if half_tokens >= 5 and half_tokens > q_results * 0.3 \
        else Granularity.QUARTERLY
    conf["granularity"] = 1.0 if tokened else 0.0
    if granularity == Granularity.HALF_YEARLY:
        # H1 reports in the Q2 slot, full-year in the Q4 slot
        for d in tokened:
            if d.facts.period_token == "h1":
                report_months.setdefault(2, d.published_at.month)
            if d.facts.period_token == "h2":
                report_months.setdefault(4, d.published_at.month)

    # --- fiscal year end, from period-end DATES (facts, not labels) -------
    fy_end_months: Counter = Counter()
    lags: list[int] = []
    for d in tokened:
        m = YEAR_ENDED_RE.search(_head(d)) or PERIOD_ENDED_RE.search(_head(d))
        if not m:
            continue
        end = parse_end_date(m.group(1))
        if not end:
            continue
        lag = (d.published_at - end).days
        if 0 <= lag <= 120:
            lags.append(lag)
            if YEAR_ENDED_RE.search(_head(d)):
                fy_end_months[end.month] += 1
    fiscal_year_end = fy_end_months.most_common(1)[0][0] if fy_end_months else None
    conf["fiscal_year_end"] = (
        fy_end_months.most_common(1)[0][1] / sum(fy_end_months.values())
        if fy_end_months else 0.0
    )
    if fiscal_year_end is None:
        unknown.append("fiscal year end — no 'year ended <date>' statements found")

    # --- FY label offset, from quarter-BOUND fiscal labels ----------------
    offsets_by_slot: dict[int, Counter] = defaultdict(Counter)
    for d in tokened:
        slot = d.facts.token_slot
        got = _labelled_fy(d)
        if not got:
            continue
        q, y = got
        if d.facts.period_token.startswith("q") and q != slot:
            continue  # label disagrees with the filename token; skip rather than guess
        offsets_by_slot[slot][y - d.published_at.year] += 1
    fy_offset, off_conf = {}, []
    for slot, counter in offsets_by_slot.items():
        off, n = counter.most_common(1)[0]
        if off:
            fy_offset[slot] = off
        off_conf.append(n / sum(counter.values()))
    conf["fy_offset"] = min(off_conf) if off_conf else 0.0
    for slot in report_months:
        if slot not in offsets_by_slot:
            unknown.append(f"FY label offset for slot Q{slot} — no quarter-bound fiscal label")

    # --- observed month -> slot (companies drift between adjacent months) --
    slots_by_month: dict[int, Counter] = defaultdict(Counter)
    for d in tokened:
        slots_by_month[d.published_at.month][d.facts.token_slot] += 1
    month_to_slot = {m: c.most_common(1)[0][0] for m, c in slots_by_month.items()}
    ambiguous = [m for m, c in slots_by_month.items() if len(c) > 1]
    for m in ambiguous:
        unknown.append(
            f"month {m} maps to multiple slots {dict(slots_by_month[m])} — "
            f"using the most frequent"
        )

    calendar = FiscalCalendar(
        report_months=report_months,
        fy_offset=fy_offset,
        granularity=granularity,
        month_to_slot=month_to_slot,
    )

    profile = CompanyProfile(
        ticker=ticker,
        company=company,
        calendar=calendar,
        fiscal_year_end_month=fiscal_year_end,
        reporting_lag_days=int(statistics.median(lags)) if lags else None,
        n_documents=len(docs),
        n_tokened=len(tokened),
        confidence=conf,
        unknown=unknown,
    )
    profile.selftest = selftest(profile, tokened)
    return profile


def selftest(profile: CompanyProfile, tokened: list[Document]) -> tuple[int, int]:
    """A derived calendar is trusted only if it predicts held-out tokened docs."""
    ok = 0
    total = 0
    for d in tokened:
        slot = d.facts.token_slot
        if slot is None:
            continue
        total += 1
        if profile.calendar.slot_for_month(d.published_at.month) == slot:
            ok += 1
    return ok, total


def fit_all(root: Path | str = None) -> dict[str, CompanyProfile]:
    """Profile every company directory under a corpus root."""
    from .corpus import DEFAULT_DATA_ROOT

    root = Path(root or DEFAULT_DATA_ROOT)
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            prof = fit(d)
        except (ValueError, IndexError):
            continue
        out[prof.ticker] = prof
    return out
