"""Evidence-ranked period-of-record resolution.

Five sources, ranked. The frontmatter `period:` field is rank 5 and never
decides anything: in the supplied corpus it labels the ADI Q2 FY2026 10-Q as
"Q3 2026", and splits one conference call across "Q2 2026" and "FY 2026".
It is recorded so disagreements can be surfaced, not trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .classify import DocClass, is_noise_title
from .corpus import Document
from .fiscal import FiscalPeriod, parse_quarter_words
from .profiler import CompanyProfile

FISCAL_YEAR_RE = re.compile(r"\bfiscal\s+(?:year\s+)?(\d{4})\b", re.I)
HEAD_LINES = 40


@dataclass(frozen=True)
class Evidence:
    source: str
    rank: int
    period: FiscalPeriod | None
    detail: str

    def __str__(self) -> str:
        return f"[{self.rank}] {self.source}: {self.period or '-'}  ({self.detail})"


def _from_token(doc: Document, profile: CompanyProfile) -> Evidence | None:
    slot = doc.facts.token_slot
    if slot is None:
        return None
    period = profile.calendar.fiscal_for(doc.published_at, slot=slot)
    return Evidence("filename_token", 1, period, f"token {doc.facts.period_token!r}")


def _from_calendar(doc: Document, profile: CompanyProfile) -> Evidence | None:
    period = profile.calendar.fiscal_for(doc.published_at)
    if period is None:
        return None
    return Evidence(
        "fiscal_calendar", 2, period,
        f"published {doc.published_at.isoformat()}"
    )


def _from_title(doc: Document, profile: CompanyProfile) -> Evidence | None:
    q = parse_quarter_words(doc.title)
    if not q:
        return None
    m = FISCAL_YEAR_RE.search(doc.title)
    fy = int(m.group(1)) if m else None
    if fy is None:
        guess = profile.calendar.fiscal_for(doc.published_at, slot=q)
        fy = guess.fy if guess else doc.published_at.year
    return Evidence("title", 3, FiscalPeriod(fy, quarter=q), doc.title[:60])


def _from_body(doc: Document, profile: CompanyProfile) -> Evidence | None:
    head = "\n".join(doc.lines[:HEAD_LINES])
    q = parse_quarter_words(head)
    m = FISCAL_YEAR_RE.search(head)
    if not q or not m:
        return None
    return Evidence("body", 4, FiscalPeriod(int(m.group(1)), quarter=q), "head text")


def _from_frontmatter(doc: Document) -> Evidence | None:
    raw = doc.frontmatter_period
    if not raw:
        return None
    m = re.fullmatch(r"\s*(?:Q([1-4])|H([12])|FY)\s*(\d{4})?\s*", raw, re.I)
    period = None
    if m and m.group(3):
        if m.group(1):
            period = FiscalPeriod(int(m.group(3)), quarter=int(m.group(1)))
        elif m.group(2):
            period = FiscalPeriod(int(m.group(3)), half=int(m.group(2)))
        else:
            period = FiscalPeriod(int(m.group(3)))
    return Evidence("frontmatter", 5, period, f"{raw!r} — recorded, not used")


def resolve(doc: Document, profile: CompanyProfile) -> Document:
    """Resolve a document's period of record in place; returns the document."""
    # classes that carry no period of record at all
    if doc.doc_class == DocClass.CONFERENCE:
        doc.period, doc.period_confidence = None, 1.0
        doc.evidence = (Evidence("doc_class", 0, None, "CONFERENCE — off-cycle"),)
        return doc
    if doc.doc_class == DocClass.GENERIC_FILING and is_noise_title(doc.title):
        doc.period, doc.period_confidence = None, 1.0
        doc.evidence = (Evidence("doc_class", 0, None, f"administrative: {doc.title[:50]}"),)
        return doc

    ev = [
        e for e in (
            _from_token(doc, profile),
            _from_calendar(doc, profile),
            _from_title(doc, profile),
            _from_body(doc, profile),
            _from_frontmatter(doc),
        ) if e is not None
    ]
    doc.evidence = tuple(ev)

    deciding = [e for e in ev if e.rank <= 4 and e.period is not None]
    if not deciding:
        doc.period, doc.period_confidence = None, 0.0
        doc.conflicts = ("no usable period evidence",)
        return doc

    chosen = min(deciding, key=lambda e: e.rank)
    doc.period = chosen.period

    agree = sum(1 for e in deciding if e.period == chosen.period)
    doc.period_confidence = round(agree / len(deciding), 2)
    doc.conflicts = tuple(
        f"{e.source} says {e.period}" for e in ev
        if e.period is not None and e.period != chosen.period
    )
    return doc


def resolve_all(docs: list[Document], profile: CompanyProfile) -> list[Document]:
    for d in docs:
        resolve(d, profile)
    return docs
