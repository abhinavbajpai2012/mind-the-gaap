"""Tabular assembly: Panel history + signal outputs -> the matrix the model eats.

Everything opinionated about *how* the forecast is framed lives here, because the
model must not know and the aggregator must not care.

The four decisions, and why:

1. **The target is a transform, never a level.** A row's `y` is year-on-year
   growth (currency and per-share metrics) or a year-on-year percentage-point
   difference (metrics already quoted in %). Levels cannot be pooled: ADI is in
   USDm, Hays' EPS in pence, and a margin is bounded at 100. Growth is
   dimensionless, so four companies share one table — which matters because Hays
   has five citable annual EPS observations on its own. The level comes back via
   `Frame.invert()`, from the prior-year base the frame carries.

2. **One row per *reported* period, built at that period's own print date.** This
   is the backfill, and it is the only place the as-of cutoff is set: a row for
   FY2025Q3 sees only documents published before FY2025Q3's results landed.
   Without it the call-tone signal scores the call that announced the number it
   is being used to predict, and the backtest is meaningless.

3. **Missing stays missing.** Signals abstain — the call-tone level channels
   return None below six prior calls, which is most of any company's early
   history — and `Panel.history` is genuinely holey (older filings format their
   tables differently, so roughly two thirds of quarters resolve). Both arrive as
   None and reach the model as NaN. Zero-filling would encode "not measured" as
   "ordinary", and the periods that resolve are not contiguous, so nothing here
   may assume a dense series.

4. **Ordinals, not words.** `CallToneOutput` carries every channel twice and says
   outright that a model must see one form, never both. `signals.numeric_features`
   keeps the ordinal half; the words survive only in `Frame.because()`, which is
   the audit trail.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from ..aggregator.fiscal import FiscalPeriod
from ..aggregator.panel import AmbiguousMetric, NotReported, Panel, Value
from . import signals as fanout

log = logging.getLogger(__name__)

# How far back to look for citable observations. The corpus runs to ~28 quarters
# per company and older filings mostly do not resolve, so this is a cost bound,
# not a modelling choice.
MAX_PERIODS = 44

# Below this many rows of a target's *own* history, pool in other series. TabPFN
# is built for small tables, but a dozen rows is small even for it. Above it,
# pooling only dilutes: Home Depot has 36 of its own quarters of net sales and
# does not need Deere's.
MIN_POOL = 24

# ...and below this, refuse. A target with one or two citable observations of its
# own cannot be forecast from other companies' growth rates: the pool would be
# supplying the entire answer, applied to a base it has never seen. Two of the
# twelve challenge metrics fall here, and both are aggregator coverage gaps
# (Home Depot reports "Diluted earnings per share" and "Comparable store sales",
# neither of which is the label companies.json asks for). Reporting the gap is
# the honest outcome; emitting a number is not.
MIN_OWN = 3

# Growth beyond this is a base near zero rather than a real move, and one such row
# dominates a table this size. Dropped, and counted in Frame.notes.
Y_CLIP = 3.0

# Categoricals first, so their column indices are known without a lookup.
CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "company_code",
    "family_code",
    "grain_code",
    "quarter_code",
)

# calltone_n_history counts the calls supplied, which grows monotonically with
# time: the prediction row's value exceeds every training row's, so the model
# would be extrapolating on a disguised time index. calltone_n_baseline carries
# the same "how much history backed this" information and saturates at
# BASELINE_WINDOW, so it is kept.
DROP_FEATURES = frozenset({"calltone_n_history"})

# Ordered so the first match wins: "Adjusted diluted EPS" must not be caught by
# "profit"-style rules, and "Adjusted gross margin" must not be read as revenue.
_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eps", ("earnings per share", "eps")),
    ("comp", ("comparable", "like-for-like", "like for like", "same-store")),
    ("margin", ("margin",)),
    ("profit", ("operating profit", "operating income", "net income", "profit")),
    ("revenue", ("net sales", "revenue", "net fees", "sales", "fees", "turnover")),
)
_FAMILIES: tuple[str, ...] = tuple(name for name, _ in _FAMILY_RULES) + ("other",)

_GRAINS: tuple[str, ...] = ("annual", "half", "quarter")
_PER_YEAR = {"annual": 1, "half": 2, "quarter": 4}


# --------------------------------------------------------------------------
# Period arithmetic
#
# FiscalPeriod is a label with no arithmetic of its own, and it is not safely
# sortable across grains (comparing FY2025 with FY2025Q1 compares None with an
# int and raises). Both gaps are closed here rather than in the aggregator.
# --------------------------------------------------------------------------


def grain_of(period: FiscalPeriod) -> str:
    if period.quarter:
        return "quarter"
    if period.half:
        return "half"
    return "annual"


def order_key(period: FiscalPeriod) -> tuple[int, int]:
    return (period.fy, period.quarter or period.half or 0)


def step_back(period: FiscalPeriod, k: int) -> FiscalPeriod:
    """`k` periods earlier, at this period's own grain."""
    grain = grain_of(period)
    if grain == "annual":
        return FiscalPeriod(period.fy - k)
    per_year = _PER_YEAR[grain]
    slot = (period.quarter or period.half) - 1
    fy, slot = divmod(period.fy * per_year + slot - k, per_year)
    if grain == "quarter":
        return FiscalPeriod(fy, quarter=slot + 1)
    return FiscalPeriod(fy, half=slot + 1)


def prior_year(period: FiscalPeriod) -> FiscalPeriod:
    return step_back(period, _PER_YEAR[grain_of(period)])


def time_index(period: FiscalPeriod) -> float:
    """Fiscal period as a fractional year: FY2026Q3 -> 2026.5.

    A time axis that exists for every row whether or not the extraction supplied
    a period end date, and that is comparable across grains — Hays' FY2025 and
    Deere's FY2025Q3 land on the same scale, which is what lets an annual row and
    a quarterly row share a table.
    """
    per_year = _PER_YEAR[grain_of(period)]
    slot = (period.quarter or period.half or 1) - 1
    return period.fy + slot / per_year


def period_end(
    level: Optional[Value],
    base: Optional[Value],
    printed: Optional[date],
    prior_printed: Optional[date] = None,
) -> Optional[date]:
    """Best available real date for a row, in order of directness.

    The extraction knows the actual period end ("3 months to 2025-08-02") because
    it read it off the table column, so that is used when present — but not every
    accepted cell carries one (Deere's tables label their columns without dates),
    so the period's own print date stands in.

    The period being forecast has neither, and is dated a year on from the
    prior-year period: plus 364 days rather than one calendar year, because Home
    Depot, Analog Devices and Deere all run 52/53-week fiscal years where the
    same quarter ends a few days earlier each year rather than on the same date.
    """
    if level is not None and _span_end(level):
        return _span_end(level)
    if printed is not None:
        return printed
    anchor = _span_end(base) or prior_printed
    return anchor + timedelta(days=364) if anchor else None


def _span_end(value: Optional[Value]) -> Optional[date]:
    span = getattr(value, "span", None) if value is not None else None
    return span.end_date if span is not None else None


def family_of(metric_label: str) -> str:
    low = metric_label.casefold()
    for name, needles in _FAMILY_RULES:
        if any(needle in low for needle in needles):
            return name
    return "other"


def transform_kind(units: str) -> str:
    """A metric already quoted in % moves in points, not in multiples.

    Home Depot's comparable sales is itself a growth rate and crosses zero, so a
    ratio against it is unbounded nonsense; Analog Devices' gross margin is
    bounded at 100 and a 69->73 move is +3.8pp, not +5.5%.
    """
    return "diff" if "%" in units else "ratio"


def apply_transform(kind: str, level: float, base: float) -> Optional[float]:
    if kind == "diff":
        return float(level) - float(base)
    if base <= 0:
        # Growth off a zero or negative base has no sign anyone can defend.
        return None
    return float(level) / float(base) - 1.0


def invert_transform(kind: str, y: float, base: float) -> float:
    return float(base) + y if kind == "diff" else float(base) * (1.0 + y)


# --------------------------------------------------------------------------
# Rows and frames
# --------------------------------------------------------------------------


@dataclass
class Row:
    """One observation: a transformed target and the covariates known before it."""

    company: str
    metric: str
    family: str
    period: FiscalPeriod
    as_of: Optional[date]  # the period's print date; the cutoff its features saw
    timestamp: Optional[date] = None  # when the period itself ended
    level: Optional[float] = None  # None for the row being predicted
    base: Optional[float] = None  # prior-year level, the denominator of the transform
    y: Optional[float] = None
    x: dict[str, Optional[float]] = field(default_factory=dict)
    cites: tuple[str, ...] = ()

    def __repr__(self) -> str:
        y = "?" if self.y is None else f"{self.y:+.3f}"
        return f"<Row {self.company} {self.period} {self.metric[:22]} y={y} as_of={self.as_of}>"


@dataclass
class Frame:
    """A model-ready table for one target, plus everything needed to undo it."""

    company: str
    metric: str
    units: str
    period: FiscalPeriod
    kind: str  # "ratio" | "diff"
    base: Optional[float]  # prior-year level of the target period
    columns: list[str]
    categorical: list[int]
    X: list[list[Optional[float]]]
    y: list[float]
    rows: list[Row]
    x_pred: list[Optional[float]]
    target_row: Optional[Row]
    signal_words: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Can this frame produce a *defensible* level?

        Three ways it cannot: no prior-year base to invert against, nothing to
        train on, or too little of the target's own history (MIN_OWN) — in which
        case the pooled rows would be supplying the whole answer, applied to a
        base drawn from a series the model has never otherwise seen. All three
        mean the metric barely resolves in this corpus. `notes` says which.
        """
        return (
            self.base is not None
            and self.target_row is not None
            and len(self.y) >= 2
            and self.n_self >= MIN_OWN
        )

    @property
    def n_self(self) -> int:
        return sum(1 for r in self.rows if r.company == self.company and r.metric == self.metric)

    @property
    def timestamps(self) -> list[Optional[date]]:
        """Period end date per training row, aligned with X and y."""
        return [row.timestamp for row in self.rows]

    @property
    def target_timestamp(self) -> Optional[date]:
        return self.target_row.timestamp if self.target_row else None

    def to_records(self) -> list[dict[str, Any]]:
        """The table as records: one row per observation, timestamp and target
        first, then the covariates.

        This is the same data as `X`/`y`, in the shape a time-series model or a
        human wants it: every row is stamped with when its period ended and what
        actually happened. The final record is the period being forecast, with
        `target` None — the row the model has to fill in.
        """
        out = []
        for row in [*self.rows, *( [self.target_row] if self.target_row else [] )]:
            record: dict[str, Any] = {
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "target": row.y,
                "company": row.company,
                "metric": row.metric,
                "period": str(row.period),
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "level": row.level,
                "base": row.base,
            }
            record.update({column: row.x.get(column) for column in self.columns})
            out.append(record)
        return out

    def to_csv(self, path: str | Any = None) -> str:
        """The table as CSV, for eyeballing it or handing it to something else."""
        records = self.to_records()
        if not records:
            return ""
        header = list(records[0])
        lines = [",".join(header)]
        for record in records:
            lines.append(
                ",".join("" if record[k] is None else f"{record[k]}" for k in header)
            )
        text = "\n".join(lines)
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def invert(self, y_hat: float) -> float:
        if self.base is None:
            raise ValueError(
                f"{self.company} {self.period} {self.metric!r}: no prior-year base, "
                f"nothing to invert against (see frame.notes)"
            )
        return invert_transform(self.kind, y_hat, self.base)

    def because(self, forecast: Any = None) -> str:
        """The push() rationale: what was forecast, on what, and what tilted it."""
        unit = "pp" if self.kind == "diff" else "%"
        scale = 1.0 if self.kind == "diff" else 100.0
        parts = []
        if forecast is not None:
            band = ""
            if getattr(forecast, "low", None) is not None:
                band = f" [{forecast.low * scale:+.2f}, {forecast.high * scale:+.2f}]"
            parts.append(
                f"{forecast.model} on {forecast.n_train} rows "
                f"({self.n_self} own): YoY {forecast.point * scale:+.2f}{unit}{band} "
                f"on {prior_year(self.period)} base {self.base:g} {self.units}"
            )
        for name, output in self.signal_words.items():
            channels = ", ".join(
                f"{k}={v}"
                for k, v in output.items()
                if v is not None and not k.endswith("_ord")
            )
            if channels:
                parts.append(f"{name}: {channels}")
        return "; ".join(parts)

    def describe(self) -> str:
        head = (
            f"Frame · {self.company} {self.period} · {self.metric} ({self.units})\n"
            f"  transform {self.kind} · base {self.base} · "
            f"{len(self.y)} rows ({self.n_self} own) x {len(self.columns)} columns"
        )
        counts = [
            f"    {c:<32} {sum(1 for row in self.X if row[i] is not None):>3}/{len(self.X)} present"
            for i, c in enumerate(self.columns)
        ]
        notes = [f"  note: {n}" for n in self.notes]
        return "\n".join([head, "  columns:"] + counts + notes)


# --------------------------------------------------------------------------
# The builder
# --------------------------------------------------------------------------


class FeatureBuilder:
    """Builds frames from a Panel, caching the expensive parts across targets.

    Three caches, all keyed so that the twelve challenge targets share work:
    metric levels per (company, metric, grain), signal outputs per (company,
    as_of) — the fan-out does not depend on which metric is being forecast, so
    one company's three metrics run it once per period rather than three times —
    and print dates per (company, period).

    Measured on the supplied corpus: a Panel build is ~0.6s, a metric's full
    history ~1-2s, and the call-tone fan-out ~0.2s per as-of date. All twelve
    frames land in well under a minute, so nothing here is cached to disk.
    """

    def __init__(
        self,
        panel: Panel,
        pool: str = "family",
        max_periods: int = MAX_PERIODS,
        min_pool: int = MIN_POOL,
    ) -> None:
        self.panel = panel
        self.pool = pool
        self.max_periods = max_periods
        self.min_pool = min_pool
        self._tickers: dict[str, str] = {}
        self._candidates: dict[tuple[str, str], list[FiscalPeriod]] = {}
        self._levels: dict[tuple[str, str, str, str], dict[FiscalPeriod, Value]] = {}
        self._prints: dict[tuple[str, str], Optional[date]] = {}
        self._fanouts: dict[tuple[str, Optional[date]], fanout.FanOut] = {}
        self._series: dict[tuple[str, str, str, str], list[Row]] = {}

    # ---- public ----------------------------------------------------------
    def build_target(self, target: Any, as_of: date | str | None = None) -> Frame:
        """Frame for one of `panel.targets`."""
        return self.build(
            target.ticker, target.metric_label, target.units, target.period, as_of=as_of
        )

    def build(
        self,
        company: str,
        metric: str,
        units: str,
        period: FiscalPeriod | str,
        as_of: date | str | None = None,
    ) -> Frame:
        """Assemble the training table and the prediction row for one target.

        `as_of` is only needed to backtest a period that has already printed. The
        twelve challenge targets leave it unset: the corpus is frozen 2026-08-14
        and none of those prints have happened, so there is nothing to hide.
        """
        ticker = self._ticker(company)
        want = FiscalPeriod.parse(period) if isinstance(period, str) else period
        cutoff = _as_date(as_of) or _as_date(self.panel.frozen_at)
        kind = transform_kind(units)
        family = family_of(metric)
        notes: list[str] = []

        own = self.series_rows(ticker, metric, units, grain_of(want))
        rows = list(own)

        # Pool only to cover a thin series, and only with rows in the same
        # transform space: a percentage-point move and a growth rate are both
        # called `y`, but +3.8 and +0.038 in one column is not a feature, it is
        # a scaling error.
        if self.pool != "self" and len(own) < self.min_pool:
            pooled = self._pooled_rows(ticker, metric, kind, family)
            widened = (
                self._pooled_rows(ticker, metric, kind, None)
                if self.pool == "family" and len(own) + len(pooled) < self.min_pool
                else []
            )
            chosen, scope = (
                (widened, "every metric") if len(widened) > len(pooled) else (pooled, f"family {family!r}")
            )
            rows += chosen
            notes.append(
                f"{len(own)} own row(s) < min_pool={self.min_pool}: pooled "
                f"{len(chosen)} {kind}-space row(s) from {scope}"
            )

        # Leak guard for the pooled rows. A row is dated by its own print, so in
        # backtest mode another company's later print must not be in the table.
        if cutoff:
            fresh = [r for r in rows if r.as_of is None or r.as_of < cutoff]
            if len(fresh) != len(rows):
                notes.append(f"{len(rows) - len(fresh)} row(s) dropped: printed on/after {cutoff}")
            rows = fresh

        target_row, base = self._prediction_row(ticker, metric, units, want, as_of, notes)

        # How old each observation is relative to the period being forecast. It
        # cannot be baked into the cached rows — the same Hays row is 1 year old
        # in one frame and 4 in another — so it is stamped here, onto copies.
        here = time_index(want)
        rows = [
            replace(row, x={**row.x, "ts_age_years": here - time_index(row.period)})
            for row in rows
        ]
        rows.sort(key=lambda r: (r.company, r.metric, order_key(r.period)))
        if target_row is not None:
            target_row = replace(target_row, x={**target_row.x, "ts_age_years": 0.0})

        columns = _columns([*rows, target_row] if target_row else rows)
        frame = Frame(
            company=ticker,
            metric=metric,
            units=units,
            period=want,
            kind=kind,
            base=base,
            columns=columns,
            categorical=[i for i, c in enumerate(columns) if c in CATEGORICAL_COLUMNS],
            X=[[r.x.get(c) for c in columns] for r in rows],
            y=[float(r.y) for r in rows],
            rows=rows,
            x_pred=[target_row.x.get(c) for c in columns] if target_row else [],
            target_row=target_row,
            signal_words=self._words(ticker, target_row.as_of if target_row else None),
            notes=notes,
            cites=self._cites(ticker, metric, units, want),
        )
        if len(own) < MIN_OWN:
            frame.notes.append(
                f"{metric!r} resolves for only {len(self.levels(ticker, metric, units, grain_of(want)))} "
                f"period(s) at {ticker}, giving {len(own)} year-on-year row(s) < MIN_OWN={MIN_OWN}: "
                f"no forecast can be defended from this corpus. Check the label against what the "
                f"company actually prints, and add it to aggregator/data/concepts.json"
            )
        return frame

    # ---- series ----------------------------------------------------------
    def series_rows(self, company: str, metric: str, units: str, grain: str) -> list[Row]:
        """Every reported period of one metric, as a training row.

        This is the backfill. Each row's covariates are rebuilt at that period's
        own print date, so a row never sees a document that did not exist when
        the period was still a forecast.
        """
        ticker = self._ticker(company)
        key = (ticker, metric.casefold(), units, grain)
        if key in self._series:
            return self._series[key]

        levels = self.levels(ticker, metric, units, grain)
        ordered = sorted(levels, key=order_key)

        # Pass one: the transformed target, which the lag features then read.
        ys, clipped = _transformed(levels, transform_kind(units))

        # Pass two: covariates, each at its own period's cutoff.
        rows: list[Row] = []
        for period in ordered:
            if period not in ys:
                continue
            printed = self.print_date(ticker, period)
            level, base = levels[period], levels[prior_year(period)]
            rows.append(
                Row(
                    company=ticker,
                    metric=metric,
                    family=family_of(metric),
                    period=period,
                    as_of=printed,
                    timestamp=period_end(level, base, printed),
                    level=float(level),
                    base=float(base),
                    y=ys[period],
                    x=self._covariates(ticker, metric, units, period, levels, ys, printed),
                    cites=tuple(dict.fromkeys([*level.cites, *base.cites]))[:6],
                )
            )
        if clipped:
            log.debug("%s %s: %d row(s) clipped at |y|>%s", ticker, metric, clipped, Y_CLIP)

        self._series[key] = rows
        return rows

    def levels(
        self, company: str, metric: str, units: str, grain: str
    ) -> dict[FiscalPeriod, Value]:
        """Citable levels of one metric, keyed by period. Holes are expected.

        Deliberately not `Panel.history()`: that method sorts the periods it finds
        with FiscalPeriod's own ordering, which raises on a half-yearly reporter
        (comparing FY2025 against FY2025H1 compares None with an int), and it
        cannot be asked for one grain. Hays needs both — its annual figures are
        the target, and no Hays document resolves to a bare fiscal year, so the
        annual periods have to be constructed from the years its half-year
        documents cover.
        """
        ticker = self._ticker(company)
        key = (ticker, metric.casefold(), units, grain)
        if key in self._levels:
            return self._levels[key]

        out: dict[FiscalPeriod, Value] = {}
        for period in self._candidate_periods(ticker, grain):
            try:
                out[period] = self.panel.value(ticker, period, metric, units, strict=False)
            except (NotReported, AmbiguousMetric):
                continue
        self._levels[key] = out
        return out

    def print_date(self, company: str, period: FiscalPeriod) -> Optional[date]:
        """When this period's results first reached the corpus.

        The earliest document of record for the period — its results release. It
        is the cutoff for that period's row: anything published on or after it
        may already contain the number being predicted.
        """
        ticker = self._ticker(company)
        key = (ticker, str(period))
        if key not in self._prints:
            found = self.panel.docs(ticker, period)
            self._prints[key] = found.docs[0].published_at if found.docs else None
        return self._prints[key]

    # ---- covariates ------------------------------------------------------
    def _covariates(
        self,
        ticker: str,
        metric: str,
        units: str,
        period: FiscalPeriod,
        levels: dict[FiscalPeriod, Value],
        ys: dict[FiscalPeriod, float],
        as_of: Optional[date],
    ) -> dict[str, Optional[float]]:
        kind = transform_kind(units)
        grain = grain_of(period)
        here = order_key(period)
        x: dict[str, Optional[float]] = {
            "company_code": float(sorted(self.panel.profiles).index(ticker))
            if ticker in self.panel.profiles
            else None,
            "family_code": float(_FAMILIES.index(family_of(metric))),
            "grain_code": float(_GRAINS.index(grain)),
            "quarter_code": float(period.quarter or period.half or 0),
            # Absolute time axis. Every row carries one, so the table is a time
            # series rather than a bag of observations. It is deliberately paired
            # with ts_age_years, set at frame assembly: ts_index for the row being
            # forecast is larger than any training row's, so on its own it is a
            # value the model has to extrapolate past. ts_age_years is 0 there and
            # positive everywhere else, which is inside the training range.
            "ts_index": time_index(period),
        }

        # Autoregressive terms, in transform space. Lag 1 and 2 are the recent
        # trajectory; lag 4 is the same slot one cycle earlier at quarterly grain,
        # which is where a seasonal pattern shows up.
        for k in (1, 2, 4):
            prior = ys.get(step_back(period, k))
            x[f"y_lag{k}"] = None if prior is None else float(prior)

        recent = [
            ys[step_back(period, k)]
            for k in range(1, 13)
            if step_back(period, k) in ys and order_key(step_back(period, k)) < here
        ][:4]
        x["y_recent_mean"] = statistics.fmean(recent) if recent else None
        # Spread of the company's own recent moves: what the interval should be
        # sized against, and the one feature that says "this series is erratic".
        x["y_recent_sd"] = statistics.stdev(recent) if len(recent) >= 2 else None
        # Saturating, unlike a row count: how much history backed this row, capped
        # so it cannot act as a time index the prediction row sits beyond.
        x["y_depth"] = float(min(sum(1 for p in ys if order_key(p) < here), 8))

        # Sequential move of the level itself (last period vs the one before),
        # which carries momentum that a year-on-year term averages away.
        one, two = levels.get(step_back(period, 1)), levels.get(step_back(period, 2))
        x["lvl_step_lag1"] = (
            apply_transform(kind, float(one), float(two)) if one is not None and two is not None else None
        )

        x.update(self.fan_out(ticker, period, as_of).features)
        return {k: v for k, v in x.items() if k not in DROP_FEATURES}

    def fan_out(
        self, company: str, period: FiscalPeriod, as_of: Optional[date]
    ) -> fanout.FanOut:
        """Signal outputs at one cutoff, cached across a company's metrics.

        Keyed on (company, as_of) and not on the period: the fan-out hands over a
        company's whole transcript run and the subagents standardise it against
        itself, so which metric is being forecast changes nothing. Three metrics
        per company therefore cost one run per period, not three.
        """
        ticker = self._ticker(company)
        key = (ticker, as_of)
        if key not in self._fanouts:
            self._fanouts[key] = fanout.run_signals(self.panel, ticker, period, as_of=as_of)
        return self._fanouts[key]

    # ---- assembly helpers ------------------------------------------------
    def _prediction_row(
        self,
        ticker: str,
        metric: str,
        units: str,
        want: FiscalPeriod,
        as_of: date | str | None,
        notes: list[str],
    ) -> tuple[Optional[Row], Optional[float]]:
        """The row being forecast: same covariates, no y, plus the base to invert."""
        levels = self.levels(ticker, metric, units, grain_of(want))
        ys, _ = _transformed(levels, transform_kind(units))

        base = levels.get(prior_year(want))
        if base is None:
            notes.append(
                f"no citable {metric!r} for {prior_year(want)}: without a prior-year "
                f"base a year-on-year forecast cannot be turned back into a level"
            )
            return None, None

        cutoff = _as_date(as_of)
        row = Row(
            company=ticker,
            metric=metric,
            family=family_of(metric),
            period=want,
            as_of=cutoff,
            timestamp=period_end(
                None, base, None, prior_printed=self.print_date(ticker, prior_year(want))
            ),
            level=None,
            base=float(base),
            y=None,
            x=self._covariates(ticker, metric, units, want, levels, ys, cutoff),
            cites=tuple(base.cites)[:6],
        )
        return row, float(base)

    def _pooled_rows(
        self, ticker: str, metric: str, kind: str, family: Optional[str]
    ) -> list[Row]:
        """Other challenge targets' history, as extra rows.

        The pool is `panel.targets` rather than a hand-written list, so a fifth
        company or a thirteenth metric joins it without a code change. `family`
        of None pools every metric in the same transform space; `kind` is never
        relaxed.
        """
        rows: list[Row] = []
        for target in self.panel.targets:
            if target.ticker == ticker and target.metric_label.casefold() == metric.casefold():
                continue
            if transform_kind(target.units) != kind:
                continue
            if family is not None and family_of(target.metric_label) != family:
                continue
            rows.extend(
                self.series_rows(
                    target.ticker,
                    target.metric_label,
                    target.units,
                    grain_of(target.period),
                )
            )
        return rows

    def _words(self, ticker: str, as_of: Optional[date]) -> dict[str, Any]:
        """The word channels of the target row's signals, for the audit trail."""
        key = (ticker, as_of)
        if key not in self._fanouts:
            return {}
        out: dict[str, Any] = {}
        for name, output in self._fanouts[key].outputs.items():
            dumped = output.model_dump()
            out[name] = {
                k: v
                for k, v in dumped.items()
                if isinstance(v, str) and k not in ("company", "period")
            }
        return out

    def _cites(self, ticker: str, metric: str, units: str, want: FiscalPeriod) -> list[str]:
        """Documents the forecast rests on: the base, and the most recent history.

        `Panel.push` refuses a value without these, and rightly — these are the
        figures the model actually saw.
        """
        levels = self.levels(ticker, metric, units, grain_of(want))
        seen: list[str] = []
        wanted = [prior_year(want)] + [step_back(want, k) for k in (1, 2, 3, 4)]
        for period in wanted:
            value = levels.get(period)
            if value is None:
                continue
            for cite in value.cites:
                if cite not in seen:
                    seen.append(cite)
        return seen[:8]

    def _candidate_periods(self, ticker: str, grain: str) -> list[FiscalPeriod]:
        """Periods of one grain that this company might have reported.

        Annual periods are *constructed* from the fiscal years the documents
        cover, not filtered from them: Hays' documents resolve to halves, so
        FY2025 exists as a reportable period even though no document is labelled
        with it. `Panel.value` reaches the annual figures through its own
        full-year matching.
        """
        key = (ticker, grain)
        if key in self._candidates:
            return self._candidates[key]

        periods = {d.period for d in self.panel.docs(ticker) if d.period}
        if grain == "annual":
            found = {FiscalPeriod(p.fy) for p in periods}
        elif grain == "half":
            found = {p for p in periods if p.half}
        else:
            found = {p for p in periods if p.quarter}

        ordered = sorted(found, key=order_key)[-self.max_periods :]
        self._candidates[key] = ordered
        return ordered

    def _ticker(self, company: str) -> str:
        if company not in self._tickers:
            self._tickers[company] = self.panel.docs(company).company
        return self._tickers[company]


def _transformed(
    levels: dict[FiscalPeriod, Value], kind: str
) -> tuple[dict[FiscalPeriod, float], int]:
    """Every period whose prior year also resolved, in transform space.

    Returns the series and how many observations were dropped as implausible —
    a near-zero base, which turns an ordinary move into a 400% one and would
    dominate a table this small.
    """
    ys: dict[FiscalPeriod, float] = {}
    clipped = 0
    for period, level in levels.items():
        base = levels.get(prior_year(period))
        if base is None:
            continue
        y = apply_transform(kind, float(level), float(base))
        if y is None:
            continue
        if abs(y) > Y_CLIP:
            clipped += 1
            continue
        ys[period] = y
    return ys, clipped


def _columns(rows: list[Row]) -> list[str]:
    """Categoricals first (so their indices are known), then everything else."""
    seen: set[str] = set()
    for row in rows:
        seen.update(row.x)
    rest = sorted(seen - set(CATEGORICAL_COLUMNS) - DROP_FEATURES)
    return [c for c in CATEGORICAL_COLUMNS if c in seen] + rest


def _as_date(value: date | str | None) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)
