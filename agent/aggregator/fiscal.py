"""Fiscal period types and calendars.

A FiscalPeriod is a label (FY2026Q3). A PeriodSpan is what a table column
actually refers to: an end date plus a duration. The duration is what stops a
nine-month year-to-date column being read as a quarter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

QUARTER_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Three Months Ended Aug. 2, 2025" / "Year ended 30 June"
DURATION_WORDS = {
    "three": 3, "six": 6, "nine": 9, "twelve": 12,
    "year": 12, "annual": 12, "full year": 12, "half": 6,
}


@dataclass(frozen=True, order=True)
class FiscalPeriod:
    """A fiscal period label."""

    fy: int
    quarter: int | None = None
    half: int | None = None

    def __str__(self) -> str:
        if self.quarter:
            return f"FY{self.fy}Q{self.quarter}"
        if self.half:
            return f"FY{self.fy}H{self.half}"
        return f"FY{self.fy}"

    @property
    def months(self) -> int:
        """Nominal duration of this period."""
        if self.quarter:
            return 3
        if self.half:
            return 6
        return 12

    @classmethod
    def parse(cls, text: str) -> "FiscalPeriod":
        """Parse 'FY2026Q3' / 'FY2026H1' / 'FY2026' / 'q3-2025'."""
        s = text.strip().upper().replace(" ", "").replace("_", "-")
        m = re.fullmatch(r"FY?(\d{4})Q([1-4])", s)
        if m:
            return cls(int(m.group(1)), quarter=int(m.group(2)))
        m = re.fullmatch(r"FY?(\d{4})H([12])", s)
        if m:
            return cls(int(m.group(1)), half=int(m.group(2)))
        m = re.fullmatch(r"Q([1-4])-?(\d{4})", s)
        if m:
            return cls(int(m.group(2)), quarter=int(m.group(1)))
        m = re.fullmatch(r"H([12])-?(\d{4})", s)
        if m:
            return cls(int(m.group(2)), half=int(m.group(1)))
        m = re.fullmatch(r"FY?(\d{4})", s)
        if m:
            return cls(int(m.group(1)))
        raise ValueError(f"cannot parse period {text!r}")


@dataclass(frozen=True)
class PeriodSpan:
    """What a table column refers to: an end date and a duration."""

    end_date: date | None
    months: int
    fiscal: FiscalPeriod | None = None

    def __str__(self) -> str:
        head = str(self.fiscal) if self.fiscal else "?"
        tail = f"{self.months} months"
        if self.end_date:
            tail += f" to {self.end_date.isoformat()}"
        return f"{head} ({tail})"


class Granularity:
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"


@dataclass(frozen=True)
class FiscalCalendar:
    """Maps a publication date to the fiscal period it reports.

    report_months maps period-slot -> calendar month of the report.
    fy_offset maps period-slot -> adjustment applied to the publication year
    to obtain the fiscal-year label. Home Depot's Q4 (published February) needs
    -1; Hays' Q1 (published October) needs +1.
    """

    report_months: dict[int, int] = field(default_factory=dict)
    fy_offset: dict[int, int] = field(default_factory=dict)
    granularity: str = Granularity.QUARTERLY
    #: every observed publication month -> slot. Companies drift (Hays reports
    #: H1 in January some years and February others), so a single modal month
    #: per slot loses real documents. Observations win over a tidy model.
    month_to_slot: dict[int, int] = field(default_factory=dict)

    def slot_for_month(self, month: int) -> int | None:
        """Which period slot does a publication month belong to?"""
        if month in self.month_to_slot:
            return self.month_to_slot[month]
        if not self.report_months:
            return None
        best, best_gap = None, 99
        for slot, rm in self.report_months.items():
            gap = min((month - rm) % 12, (rm - month) % 12)
            if gap < best_gap:
                best, best_gap = slot, gap
        # a report month more than one month adrift is not this slot
        return best if best_gap <= 1 else None

    def fiscal_for(self, published: date, slot: int | None = None) -> FiscalPeriod | None:
        """Resolve a publication date (and optional known slot) to a period."""
        if slot is None:
            slot = self.slot_for_month(published.month)
        if slot is None:
            return None
        fy = published.year + self.fy_offset.get(slot, 0)
        if self.granularity == Granularity.HALF_YEARLY and slot in (2, 4):
            return FiscalPeriod(fy, half=1 if slot == 2 else 2)
        return FiscalPeriod(fy, quarter=slot)


def parse_duration(text: str) -> int | None:
    """'Three Months Ended' -> 3, 'Year ended 30 June' -> 12."""
    low = text.casefold()
    m = re.search(r"\b(three|six|nine|twelve)\s+months?\b", low)
    if m:
        return DURATION_WORDS[m.group(1)]
    if re.search(r"\b(year|twelve months|full[- ]year|annual)\b.{0,12}\bended?\b", low):
        return 12
    if re.search(r"\bended?\b.{0,20}\b(year)\b", low):
        return 12
    if re.search(r"\bhalf[- ]year\b", low):
        return 6
    return None


def parse_end_date(text: str) -> date | None:
    """'Aug. 2, 2025' / 'August 2, 2025' / '30 June 2025' -> date."""
    low = text.strip()
    # Home Depot prints "August 3,2025" with no space after the comma
    m = re.search(r"([A-Za-z]{3,9})\.?\s*(\d{1,2}),?\s*(\d{4})", low)
    if m:
        mon = MONTHS.get(m.group(1)[:3].casefold())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", low)
    if m:
        mon = MONTHS.get(m.group(2)[:3].casefold())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                return None
    return None


def parse_quarter_words(text: str) -> int | None:
    """'Fiscal Third Quarter 2025' -> 3."""
    low = text.casefold()
    m = re.search(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b", low)
    if m:
        return QUARTER_WORDS[m.group(1)]
    m = re.search(r"\bq([1-4])\b", low)
    if m:
        return int(m.group(1))
    return None
