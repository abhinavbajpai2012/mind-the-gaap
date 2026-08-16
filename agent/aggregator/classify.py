"""Filename-driven document classification.

Every corpus document is named:
    YYYY-MM-DD__<slug>-<cc>-YYYYMMDD-<KIND>__<id>.md

KIND partitions the corpus deterministically, which is the cheapest reliable
signal available. Two classes carry no period of record at all and must be kept
out of period queries: investor conferences (off-cycle) and administrative
filings (buyback logs, voting-rights notices).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class DocClass:
    STRUCTURED_RESULT = "STRUCTURED_RESULT"
    EARNINGS_CALL = "EARNINGS_CALL"
    SLIDE = "SLIDE"
    GENERIC_FILING = "GENERIC_FILING"
    CONFERENCE = "CONFERENCE"
    AGM = "AGM"
    NOISE = "NOISE"


#: classes that can legitimately carry a period of record
PERIOD_BEARING = {
    DocClass.STRUCTURED_RESULT,
    DocClass.EARNINGS_CALL,
    DocClass.SLIDE,
    DocClass.GENERIC_FILING,
}

#: classes worth mining for the metric catalogue (tables of real financials)
TABLE_BEARING = {DocClass.STRUCTURED_RESULT, DocClass.SLIDE, DocClass.GENERIC_FILING}

FILENAME_RE = re.compile(
    r"^(?P<pub>\d{4}-\d{2}-\d{2})__"
    r"(?P<stem>.+?)__"
    r"(?P<docid>\d+)\.md$"
)
STEM_PREFIX_RE = re.compile(r"^(?P<slug>[a-z]+)-(?P<cc>[a-z]{2})-(?P<ymd>\d{8})-")
PERIOD_TOKEN_RE = re.compile(r"^(?:call-)?(?P<tok>q[1-4]|h[12]|fy)(?:-|$)")

#: administrative filings with no financial content
NOISE_TITLE_PATTERNS = (
    r"notification of major holdings",
    r"transaction in own shares",
    r"voting rights and capital",
    r"total voting rights",
    r"pdmr shareholding",
    r"director/pdmr",
    r"change of registered office",
    r"share buyback (transaction )?log",
    r"daily share buyback",
    r"block ?listing",
    r"holding\(s\) in company",
    r"annual meeting proxy",
    r"proxy statement",
)
NOISE_TITLE_RE = re.compile("|".join(NOISE_TITLE_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class FileFacts:
    """Everything derivable from the filename alone."""

    path: Path
    published_at: date
    slug: str
    country: str
    kind: str
    doc_id: str
    period_token: str | None      # 'q3' | 'h1' | 'fy' | None
    doc_class: str

    @property
    def token_slot(self) -> int | None:
        """Period token as a slot number: q3 -> 3, h1 -> 2, h2 -> 4."""
        t = self.period_token
        if not t:
            return None
        if t.startswith("q"):
            return int(t[1])
        if t == "h1":
            return 2
        if t == "h2":
            return 4
        return None


def _doc_class(kind: str) -> str:
    if kind.startswith("call-conf"):
        return DocClass.CONFERENCE
    if kind.startswith("call-agm"):
        return DocClass.AGM
    # Before the period-token test: PERIOD_TOKEN_RE deliberately allows a 'call-' prefix
    # so that 'call-q3-qna' yields the token q3, and testing it first classified 27
    # quarter-tagged earnings calls across the corpus as results documents. A call is a
    # call whether or not its filename names the quarter.
    if kind.startswith("call"):
        return DocClass.EARNINGS_CALL
    if PERIOD_TOKEN_RE.match(kind):
        return DocClass.STRUCTURED_RESULT
    if kind == "slide":
        return DocClass.SLIDE
    return DocClass.GENERIC_FILING


def parse_filename(path: str | Path) -> FileFacts | None:
    """Derive class and period token from a corpus filename. None if not a corpus doc."""
    path = Path(path)
    m = FILENAME_RE.match(path.name)
    if not m:
        return None
    stem = m.group("stem")
    pm = STEM_PREFIX_RE.match(stem)
    if not pm:
        return None
    kind = stem[pm.end():]
    # strip variant suffixes: 'call-conf-pres-3' -> 'call-conf-pres', 'filing-2' -> 'filing'
    kind = re.sub(r"-\d+$", "", kind)
    tok = PERIOD_TOKEN_RE.match(kind)
    y, mo, d = (int(x) for x in m.group("pub").split("-"))
    return FileFacts(
        path=path,
        published_at=date(y, mo, d),
        slug=pm.group("slug"),
        country=pm.group("cc"),
        kind=kind,
        doc_id=m.group("docid"),
        period_token=tok.group("tok") if tok else None,
        doc_class=_doc_class(kind),
    )


def is_noise_title(title: str) -> bool:
    """Administrative filing with no financial content?"""
    return bool(title and NOISE_TITLE_RE.search(title))
