"""Facet match + cell read -> cited DataPoint.

Period and duration are HARD predicates here, not score terms. A column is in
the requested period or it is not; nothing about relevance can promote a
nine-month or prior-year column into a quarterly answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .corpus import Document
from .facets import MetricSpec, parse as parse_facets
from .fiscal import FiscalPeriod, PeriodSpan
from .tables import Table, parse_tables
from .units import parse_cell


@dataclass(frozen=True)
class DataPoint:
    metric: MetricSpec
    value: float
    unit: str
    span: PeriodSpan
    source_path: str
    source_short: str
    line_no: int
    row_label: str
    quote: str
    extractor: str = "table.row_facet_match"
    confidence: float = 1.0
    #: ranking inputs — a headline summary row beats a buried detail row
    label_residual: str = ""
    has_units: bool = False
    doc_kind: str = ""

    @property
    def rank(self) -> tuple:
        """Lower sorts first: clean label, declared units, press release, early line."""
        kind_priority = (
            0 if "8k" in self.doc_kind else
            1 if self.doc_kind == "slide" else
            2 if "10q" in self.doc_kind or "10k" in self.doc_kind else 3
        )
        return (len(self.label_residual), 0 if self.has_units else 1,
                kind_priority, self.line_no)

    @property
    def cite(self) -> str:
        return f"{self.source_short}:{self.line_no}"

    def __repr__(self) -> str:
        return f"{self.value:g} {self.unit} · {self.span} · {self.cite}"


@dataclass
class Extraction:
    """Everything a query found, plus everything it refused and why."""

    accepted: list[DataPoint] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)


def _cell_quote(table: Table, row) -> str:
    return table.doc.lines[row.line_no - 1].strip()


def extract(
    docs: list[Document],
    spec: MetricSpec,
    period: FiscalPeriod,
    profile,
    segments: tuple[str, ...] = (),
) -> Extraction:
    """Pull every cited value matching `spec` for `period` out of `docs`."""
    out = Extraction()
    want_months = period.months
    seen_labels: set[str] = set()

    for doc in docs:
        for table in parse_tables(doc, profile):
            for row in table.rows:
                row_spec = parse_facets(row.effective_label, segments)
                if not spec.matches(row_spec):
                    continue
                seen_labels.add(row.label)

                matched_any = False
                for col in table.columns:
                    if col.index == 0 or col.index >= len(row.cells):
                        continue
                    raw = row.cells[col.index]
                    if not raw:
                        continue
                    span = col.span
                    tag = f"{doc.short}:{row.line_no}c{col.index}"

                    if span is None or span.months == 0:
                        out.rejected.append((tag, f"column {col.header!r} has no resolved period"))
                        continue
                    if span.months != want_months:
                        out.rejected.append(
                            (tag, f"{span.months}-month column ({col.header.strip()[:40]!r}) "
                                  f"— query needs {want_months}")
                        )
                        continue
                    if span.fiscal != period:
                        out.rejected.append(
                            (tag, f"column period {span.fiscal} != {period}")
                        )
                        continue

                    parsed = parse_cell(raw, table.units, per_share=spec.is_per_share)
                    if parsed is None:
                        continue
                    value, unit = parsed
                    if spec.unit_class == "percent" and unit not in ("pct", "bps"):
                        out.rejected.append((tag, f"expected a percentage, cell was {raw!r}"))
                        continue
                    if spec.unit_class == "currency_abs" and unit in ("pct", "bps"):
                        out.rejected.append((tag, f"expected an amount, cell was {raw!r}"))
                        continue

                    matched_any = True
                    out.accepted.append(
                        DataPoint(
                            metric=row_spec,
                            value=value,
                            unit=unit,
                            span=span,
                            source_path=str(doc.path),
                            source_short=doc.short,
                            line_no=row.line_no,
                            row_label=row.raw_label,
                            quote=_cell_quote(table, row),
                            label_residual=row_spec.residual,
                            has_units=table.units is not None,
                            doc_kind=doc.kind,
                        )
                    )

                # ragged table: fall back to positional slots
                if not matched_any and table.slots:
                    values = []
                    for raw in row.cells[1:]:
                        parsed = parse_cell(raw, table.units, per_share=spec.is_per_share)
                        if parsed is not None:
                            values.append((raw, parsed))
                    if len(values) == len(table.slots):
                        for (raw, (value, unit)), span in zip(values, table.slots):
                            if span is None or span.months != want_months \
                                    or span.fiscal != period:
                                continue
                            if spec.unit_class == "percent" and unit not in ("pct", "bps"):
                                continue
                            if spec.unit_class == "currency_abs" and unit in ("pct", "bps"):
                                continue
                            out.accepted.append(
                                DataPoint(
                                    metric=row_spec, value=value, unit=unit, span=span,
                                    source_path=str(doc.path), source_short=doc.short,
                                    line_no=row.line_no, row_label=row.raw_label,
                                    quote=_cell_quote(table, row),
                                    extractor="table.positional_slot",
                                    label_residual=row_spec.residual,
                                    has_units=table.units is not None,
                                    doc_kind=doc.kind,
                                )
                            )

    out.accepted.sort(key=lambda dp: dp.rank)

    if len({_key(dp) for dp in out.accepted}) > 1:
        distinct = sorted({(dp.row_label.strip(), dp.value, dp.unit) for dp in out.accepted})
        if len({(d[1], d[2]) for d in distinct}) > 1:
            out.ambiguities.append(
                f"{len(distinct)} distinct values match {spec}: "
                + "; ".join(f"{lbl!r}={v:g}{u}" for lbl, v, u in distinct[:4])
            )
    return out


def _key(dp: DataPoint) -> tuple:
    return (round(dp.value, 6), dp.unit)
