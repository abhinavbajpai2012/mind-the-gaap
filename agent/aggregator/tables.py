"""Markdown table parsing, with each column resolved to a PeriodSpan.

The period a number belongs to is a property of its COLUMN, not of the
document. A 10-Q interleaves quarterly and year-to-date columns roughly 50/50:
the ADI Q3 10-Q carries 74 "Nine Months Ended" headers alongside 70
"Three Months Ended". Reading the row without reading the column header is a
coin flip between the quarter and a figure ~3x larger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .corpus import Document
from .fiscal import FiscalPeriod, PeriodSpan, parse_duration, parse_end_date
from .units import UnitContext, parse_unit_caption

FOOTNOTE_RE = re.compile(r"\s*\((\d{1,2})\)\s*$")
SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]*\|[\s:|-]*\|?\s*$")


@dataclass
class Column:
    index: int
    header: str
    span: PeriodSpan | None = None


@dataclass
class Row:
    label: str            # footnote markers stripped
    raw_label: str        # exactly as printed
    cells: list[str]
    line_no: int          # 1-indexed
    section: str = ""     # nearest section header above this row

    @property
    def effective_label(self) -> str:
        """Label qualified by its section.

        Deere prints `Diluted` twice in one table: once under `Per Share Data`
        (4.75) and once under `Average Shares Outstanding` (271.4). The label
        alone is meaningless; the section is what distinguishes them.
        """
        return f"{self.label} {self.section}".strip() if self.section else self.label


@dataclass
class Table:
    doc: Document
    start_line: int
    caption: str
    units: UnitContext | None
    columns: list[Column] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    #: ordered period slots, used when a table is ragged and index alignment
    #: fails. Home Depot puts "$" in its own cell in data rows but not in
    #: header rows, so `4.68` lands at index 2 while its date header is at 1.
    slots: list[PeriodSpan | None] = field(default_factory=list)

    def column_spans(self) -> list[PeriodSpan | None]:
        return [c.span for c in self.columns]


def _split(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _strip_footnote(label: str) -> str:
    return FOOTNOTE_RE.sub("", label).strip()


def _fiscal_for_end(end, doc: Document, months: int, profile) -> FiscalPeriod | None:
    """Attribute a column end date to a fiscal period using the company calendar."""
    if end is None or profile is None:
        return None
    cal = profile.calendar
    # a period ending in month M is reported ~lag days later
    lag = profile.reporting_lag_days or 20
    from datetime import timedelta

    approx_report = end + timedelta(days=lag)
    slot = cal.slot_for_month(approx_report.month)
    if slot is None:
        return None
    if months >= 12:
        fy = approx_report.year + cal.fy_offset.get(4, 0)
        return FiscalPeriod(fy)
    period = cal.fiscal_for(approx_report, slot=slot)
    if period and months not in (3, period.months):
        # a YTD column: keep the fiscal year, drop the quarter label
        return FiscalPeriod(period.fy)
    return period


def parse_tables(doc: Document, profile=None) -> list[Table]:
    """Extract every markdown table in a document, with column periods resolved."""
    lines = doc.lines
    tables: list[Table] = []
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        block = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            block.append((i + 1, lines[i]))
            i += 1
        if len(block) < 2:
            continue

        # caption: nearest non-empty line above that declares units, else prose
        caption = ""
        units = None
        for back in range(start - 1, max(-1, start - 8), -1):
            text = lines[back].strip()
            if not text:
                continue
            got = parse_unit_caption(text)
            if got:
                caption, units = text, got
                break
            if not caption:
                caption = text
        # a unit declaration can also live inside the header cell itself
        if units is None:
            units = parse_unit_caption(block[0][1])
            if units:
                caption = block[0][1].strip()

        # header rows: leading rows whose later cells are mostly non-numeric
        header_rows: list[tuple[int, list[str]]] = []
        body_rows: list[tuple[int, list[str]]] = []
        for line_no, raw in block:
            if SEPARATOR_RE.match(raw):
                continue
            cells = _split(raw)
            numericish = sum(
                1 for c in cells[1:] if re.search(r"\d", c) and not re.search(r"20\d{2}", c)
            )
            if not body_rows and numericish == 0 and len(header_rows) < 4:
                header_rows.append((line_no, cells))
            else:
                body_rows.append((line_no, cells))

        width = max((len(c) for _, c in header_rows + body_rows), default=0)
        headers = [""] * width
        for _, cells in header_rows:
            for j, c in enumerate(cells):
                if j < width and c:
                    headers[j] = (headers[j] + " " + c).strip()

        columns = []
        carried_duration = None
        for j, h in enumerate(headers):
            dur = parse_duration(h) or parse_duration(caption)
            end = parse_end_date(h)
            if dur:
                carried_duration = dur
            elif end and carried_duration:
                dur = carried_duration
            # bare year header ("2025") inherits the caption's duration
            if end is None and re.fullmatch(r"(?:FY\s*)?(20\d{2})", h.strip()):
                from datetime import date as _date

                yr = int(re.search(r"(20\d{2})", h).group(1))
                if profile and profile.fiscal_year_end_month:
                    end = _date(yr, profile.fiscal_year_end_month, 28)
                dur = dur or 12

            fiscal = _fiscal_for_end(end, doc, dur or 0, profile) if end else None

            # Deere-style header: "Three Months Ended" over a bare year row, no
            # explicit end date. The printed year IS the fiscal-year label, so
            # it separates the current column from the prior-year comparative.
            if fiscal is None and dur:
                ym = re.search(r"\b(20\d{2})\b", h)
                if ym:
                    yr = int(ym.group(1))
                    q = doc.period.quarter if (doc.period and dur == 3) else None
                    fiscal = FiscalPeriod(yr, quarter=q)

            span = None
            if dur or end:
                span = PeriodSpan(end_date=end, months=dur or 0, fiscal=fiscal)
            columns.append(Column(index=j, header=h, span=span))

        rows = []
        section = ""
        for line_no, cells in body_rows:
            if not cells or not cells[0]:
                continue
            raw_label = cells[0]
            if not re.search(r"[A-Za-z]", raw_label):
                continue
            label = _strip_footnote(raw_label)
            # a row with a label but no values is a section header
            if not any(c.strip() for c in cells[1:]):
                section = label
                continue
            rows.append(
                Row(
                    label=label,
                    raw_label=raw_label,
                    cells=cells,
                    line_no=line_no,
                    section=section,
                )
            )
        slots = _positional_slots(header_rows, caption, doc, profile)

        if rows:
            tables.append(
                Table(doc=doc, start_line=start + 1, caption=caption,
                      units=units, columns=columns, rows=rows, slots=slots)
            )
    return tables


CHANGE_RE = re.compile(r"%\s*change|^\s*change\s*$", re.I)


def _positional_slots(header_rows, caption, doc, profile) -> list[PeriodSpan | None]:
    """Derive ordered period slots independent of cell indices.

    Reads the header rows left to right, collecting duration groups
    ("Three Months Ended", "Six Months Ended") and period columns (dates or
    "% Change"). If the columns divide evenly among the groups, each block of
    columns inherits its group's duration.
    """
    durations: list[int] = []
    marks: list[date_or_change] = []  # type: ignore[name-defined]
    for _, cells in header_rows:
        for c in cells[1:]:
            d = parse_duration(c)
            if d and d not in ("",):
                durations.append(d)
            end = parse_end_date(c)
            if end:
                marks.append(end)
            elif CHANGE_RE.search(c or ""):
                marks.append(None)
    if not marks:
        return []
    if not durations:
        d = parse_duration(caption)
        durations = [d] if d else []
    if not durations or len(marks) % len(durations) != 0:
        return []

    block = len(marks) // len(durations)
    out: list[PeriodSpan | None] = []
    for i, mark in enumerate(marks):
        months = durations[i // block]
        if mark is None:
            out.append(None)          # a "% change" column, never a value slot
            continue
        out.append(
            PeriodSpan(end_date=mark, months=months,
                       fiscal=_fiscal_for_end(mark, doc, months, profile))
        )
    return out


date_or_change = object  # documentation alias for the list above
