"""Matrix -> forecast.

This module imports nothing from the rest of the repository. It takes lists of
numbers and returns a number, which is what makes the model swappable and lets
it be tested without a 1,139-document Panel build behind it.

Two implementations, one interface:

- `TabPFNForecaster` — TabPFN, the intended model. Its dependencies are heavy
  (torch, ~2GB) and, as of tabpfn 8.3.0, local inference needs a one-time
  licence acceptance and a `TABPFN_TOKEN` before it will download weights.
- `NeighbourForecaster` — pure standard library. Gower-distance nearest
  neighbours over the same matrix, with conformal intervals from leave-one-out
  residuals.

The fallback is not decoration. `TabPFNForecaster` delegates to it on *any*
failure — missing token, no network, an out-of-memory fit — because a run that
finishes with a defensible neighbour forecast beats a run that raises at 17:50.
Which one produced a number is recorded in `Forecast.model` and reaches the
workbook's rationale, so the fallback can never be mistaken for the real thing.

Call `preflight()` early. It performs a real fit against a toy table and tells
you whether TabPFN will work in this environment — which is worth knowing hours
before the deadline rather than minutes.
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

log = logging.getLogger(__name__)

Matrix = Sequence[Sequence[Optional[float]]]
Vector = Sequence[Optional[float]]

# Reported band. 0.5 is carried so a skewed predictive distribution can be seen.
QUANTILES: tuple[float, ...] = (0.1, 0.5, 0.9)

# tabpfn's own default grid, returned when quantiles are not requested explicitly.
_TABPFN_DEFAULT_GRID: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# Neighbours averaged by the fallback. Small: the tables here are 20-60 rows and
# a wider window just regresses everything to the pooled mean.
K_NEIGHBOURS = 7

# How much a categorical column counts for against a numeric one. Above 1.0 the
# distance matches on identity first — same company, same metric family, same
# reporting grain — and only then on trajectory. At 1.0 a pooled table drowns the
# target's own series: Hays' net fees have fallen three years running, and an
# unweighted neighbourhood forecast them *up*, on the strength of US quarterly
# revenue rows that happened to have similar lag features.
CATEGORICAL_WEIGHT = 4.0


@dataclass
class Forecast:
    """One prediction, in whatever space the caller's matrix was built in.

    `point` is *not* a level. features.py forecasts year-on-year growth or a
    percentage-point difference; `Frame.invert()` turns this back into a number
    a workbook can hold.
    """

    point: float
    low: Optional[float] = None
    high: Optional[float] = None
    quantiles: dict[float, float] = field(default_factory=dict)
    model: str = ""
    n_train: int = 0
    notes: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        band = "" if self.low is None else f" [{self.low:+.4f}, {self.high:+.4f}]"
        return f"<Forecast {self.point:+.4f}{band} · {self.model} · n={self.n_train}>"


class Forecaster(Protocol):
    name: str

    def fit_predict(
        self,
        X: Matrix,
        y: Sequence[float],
        x_pred: Vector,
        categorical_indices: Sequence[int] = (),
    ) -> Forecast: ...


# --------------------------------------------------------------------------
# Fallback: Gower nearest neighbours
#
# Chosen over "last value" or "mean growth" because it respects the matrix it is
# handed rather than ignoring it: the categorical columns (company, metric
# family, grain, quarter) match exactly, so a Home Depot Q2 row is compared with
# other Home Depot Q2 rows before it is compared with a Deere Q4 one, and the
# pooled table does not drag every company towards a common average.
#
# Missing values are skipped rather than imputed, and the distance is
# renormalised over the columns both rows actually share — which is Gower's
# original treatment, and the only one that is honest about a table where the
# call-tone channels abstain on most early rows.
# --------------------------------------------------------------------------


class NeighbourForecaster:
    name = "neighbours"

    def __init__(self, k: int = K_NEIGHBOURS) -> None:
        self.k = k

    def fit_predict(
        self,
        X: Matrix,
        y: Sequence[float],
        x_pred: Vector,
        categorical_indices: Sequence[int] = (),
    ) -> Forecast:
        rows, target = [list(r) for r in X], list(x_pred)
        values = [float(v) for v in y]
        if not rows:
            raise ValueError("nothing to train on: the frame has no rows")

        categorical = set(categorical_indices)
        scales = _column_scales(rows, categorical)

        point = self._predict(rows, values, target, categorical, scales)

        # Leave-one-out residuals as a calibration set: the spread of the errors
        # this same estimator makes on this same table. Honest about a thin table,
        # where it comes back wide, which is the correct answer.
        residuals = []
        for i in range(len(rows)):
            others = rows[:i] + rows[i + 1 :]
            other_y = values[:i] + values[i + 1 :]
            if not others:
                continue
            residuals.append(values[i] - self._predict(others, other_y, rows[i], categorical, scales))

        quantiles: dict[float, float] = {}
        if len(residuals) >= 4:
            quantiles = {q: point + _quantile(residuals, q) for q in QUANTILES}
            quantiles[0.5] = point  # the point estimate is the median by construction

        return Forecast(
            point=point,
            low=quantiles.get(0.1),
            high=quantiles.get(0.9),
            quantiles=quantiles,
            model=self.name,
            n_train=len(rows),
            notes=[f"gower k={min(self.k, len(rows))} of {len(rows)} rows"]
            + ([] if quantiles else ["interval omitted: too few rows to calibrate residuals"]),
        )

    def _predict(
        self,
        rows: list[list[Optional[float]]],
        values: list[float],
        target: list[Optional[float]],
        categorical: set[int],
        scales: list[float],
    ) -> float:
        scored = sorted(
            ((_gower(row, target, categorical, scales), value) for row, value in zip(rows, values)),
            key=lambda pair: pair[0],
        )[: max(1, min(self.k, len(rows)))]

        # Inverse-distance weights. The epsilon keeps an exact match from taking
        # the whole weight, which on a table this small is overfitting to one row.
        weights = [1.0 / (distance + 0.15) for distance, _ in scored]
        return sum(w * v for w, (_, v) in zip(weights, scored)) / sum(weights)


def _column_scales(rows: list[list[Optional[float]]], categorical: set[int]) -> list[float]:
    """Per-column spread, for putting numeric distances on a common footing."""
    width = max((len(r) for r in rows), default=0)
    scales = []
    for i in range(width):
        if i in categorical:
            scales.append(1.0)
            continue
        seen = [r[i] for r in rows if i < len(r) and r[i] is not None]
        span = (max(seen) - min(seen)) if len(seen) >= 2 else 0.0
        scales.append(span if span > 0 else 1.0)
    return scales


def _gower(
    a: Sequence[Optional[float]],
    b: Sequence[Optional[float]],
    categorical: set[int],
    scales: list[float],
) -> float:
    total, weight = 0.0, 0.0
    for i in range(min(len(a), len(b))):
        left, right = a[i], b[i]
        if left is None or right is None:
            continue  # skipped, not imputed; the denominator shrinks with it
        if i in categorical:
            total += CATEGORICAL_WEIGHT * (0.0 if left == right else 1.0)
            weight += CATEGORICAL_WEIGHT
        else:
            total += min(abs(left - right) / scales[i], 1.0)
            weight += 1.0
    return total / weight if weight else 1.0


def _quantile(sample: Sequence[float], q: float) -> float:
    """Linear-interpolated empirical quantile. statistics.quantiles needs n>=2
    and returns a fixed grid; this takes an arbitrary q off any sample."""
    ordered = sorted(sample)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


# --------------------------------------------------------------------------
# TabPFN
# --------------------------------------------------------------------------


class TabPFNForecaster:
    """TabPFN, falling back to neighbours on any failure.

    Verified against tabpfn 8.3.0: `TabPFNRegressor(categorical_features_indices=...)`,
    sklearn-style `fit`, and `predict(X, output_type="main")` returning a dict of
    mean/median/mode/quantiles. The output is read defensively anyway, so a
    version that returns a bare array still works.

    NaN is passed through rather than imputed — TabPFN handles missing values
    natively, and features.py is explicit that None means "not measured".
    """

    name = "tabpfn"

    def __init__(
        self,
        device: str = "cpu",
        random_state: int = 0,
        n_estimators: int = 8,
        fallback: Optional[Forecaster] = None,
    ) -> None:
        self.device = device
        self.random_state = random_state
        self.n_estimators = n_estimators
        self.fallback = fallback or NeighbourForecaster()

    def fit_predict(
        self,
        X: Matrix,
        y: Sequence[float],
        x_pred: Vector,
        categorical_indices: Sequence[int] = (),
    ) -> Forecast:
        try:
            return self._tabpfn(X, y, x_pred, categorical_indices)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {str(exc).strip().splitlines()[0] if str(exc) else ''}"
            log.warning("TabPFN unavailable, falling back to neighbours (%s)", reason)
            result = self.fallback.fit_predict(X, y, x_pred, categorical_indices)
            result.model = f"{self.fallback.name} (tabpfn failed)"
            result.notes.append(f"tabpfn fallback: {reason}")
            return result

    def _tabpfn(
        self,
        X: Matrix,
        y: Sequence[float],
        x_pred: Vector,
        categorical_indices: Sequence[int],
    ) -> Forecast:
        import numpy as np
        from tabpfn import TabPFNRegressor

        train = np.array([[np.nan if v is None else float(v) for v in row] for row in X], dtype=float)
        target = np.array([float(v) for v in y], dtype=float)
        query = np.array([[np.nan if v is None else float(v) for v in x_pred]], dtype=float)
        if train.size == 0:
            raise ValueError("nothing to train on: the frame has no rows")

        regressor = TabPFNRegressor(
            categorical_features_indices=list(categorical_indices) or None,
            device=self.device,
            random_state=self.random_state,
            n_estimators=self.n_estimators,
            # These tables are ~20-60 rows, far below anything TabPFN was tuned
            # on. The flag stops it refusing an input it can still handle.
            ignore_pretraining_limits=True,
        )
        regressor.fit(train, target)

        raw = regressor.predict(query, output_type="main")
        if isinstance(raw, dict):
            point = _scalar(raw.get("median", raw.get("mean")))
            grid, columns = _read_quantiles(raw.get("quantiles"))
        else:
            point, grid, columns = _scalar(raw), (), ()

        if not columns:
            grid = QUANTILES
            columns = tuple(
                _scalar(column)
                for column in regressor.predict(query, output_type="quantiles", quantiles=list(QUANTILES))
            )

        quantiles = dict(zip(grid, columns))
        return Forecast(
            point=point,
            low=quantiles.get(0.1),
            high=quantiles.get(0.9),
            quantiles=quantiles,
            model=self.name,
            n_train=int(train.shape[0]),
            notes=[f"tabpfn n_estimators={self.n_estimators} device={self.device}"],
        )


def _scalar(value) -> float:
    """First element of whatever shape the model returned."""
    try:
        return float(value)
    except (TypeError, ValueError):
        flat = value
        while hasattr(flat, "__len__") and len(flat):
            flat = flat[0]
        return float(flat)


def _read_quantiles(payload) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Label a quantile array whose grid was implied rather than requested."""
    if payload is None or not hasattr(payload, "__len__"):
        return (), ()
    columns = tuple(_scalar(column) for column in payload)
    if len(columns) == len(_TABPFN_DEFAULT_GRID):
        return _TABPFN_DEFAULT_GRID, columns
    if len(columns) == len(QUANTILES):
        return QUANTILES, columns
    return (), ()  # unrecognised grid: ask again, explicitly


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def choose(prefer: str = "auto", **kwargs) -> Forecaster:
    """Pick a forecaster.

    "auto" uses TabPFN when the package imports and falls back per-call
    otherwise; "tabpfn" insists and raises if it cannot be imported;
    "neighbours" skips it entirely.
    """
    if prefer == "neighbours":
        return NeighbourForecaster()
    try:
        import tabpfn  # noqa: F401
    except ImportError as exc:
        if prefer == "tabpfn":
            raise RuntimeError(
                "tabpfn is not installed. `uv pip install tabpfn` (pulls torch, ~2GB), "
                "or pass prefer='neighbours'."
            ) from exc
        log.info("tabpfn not installed; using the neighbour fallback")
        return NeighbourForecaster()
    return TabPFNForecaster(**kwargs)


def preflight(prefer: str = "auto") -> tuple[bool, str]:
    """Fit a toy table to find out whether TabPFN really works here.

    Importing tabpfn proves nothing: version 8.3.0 downloads its weights on the
    first `fit`, and that download is gated behind a one-time licence acceptance
    and a `TABPFN_TOKEN`. The failure therefore surfaces on the first real
    forecast, which on hackathon day is the worst possible moment to find it.
    Call this early.

    Returns (working, message). A False is not fatal — the neighbour fallback
    covers it — but it means the entry script is not running the model you think.
    """
    forecaster = choose(prefer)
    if not isinstance(forecaster, TabPFNForecaster):
        return False, "tabpfn is not installed; the neighbour fallback will be used"

    X = [[float(i % 3), float(i), None if i == 2 else float(i * i)] for i in range(12)]
    y = [float(i) * 1.5 for i in range(12)]
    try:
        forecaster._tabpfn(X, y, [1.0, 12.0, 144.0], categorical_indices=[0])
    except Exception as exc:
        hint = ""
        if "TABPFN_TOKEN" in str(exc) or "License" in type(exc).__name__:
            hint = (
                " — accept the licence at https://ux.priorlabs.ai, then "
                'export TABPFN_TOKEN="<key>" from https://ux.priorlabs.ai/account'
            )
        return False, f"tabpfn present but not usable: {type(exc).__name__}: {exc}{hint}"

    token = "set" if os.environ.get("TABPFN_TOKEN") else "not needed"
    return True, f"tabpfn ready (TABPFN_TOKEN {token})"
