"""Series -> forecast, via TabPFN-TS-3 over the hosted API.

The sibling of `model.py`, and deliberately a *different shape*. `model.py`
hands TabPFN a pooled table of hand-built features — lags, calendar codes,
company identity — and asks it to predict a year-on-year transform.
TabPFN-TS-3 does not work that way:

- It is **not autoregressive**. It regresses the target on features it derives
  itself from the timestamp (`RunningIndexFeature`, `CalendarFeature`,
  `AutoSeasonalFeature`), so our lag columns have no home here.
- It forecasts the **level**, not a transform, so there is no base to invert
  against and no `Frame` to unwind.
- It is **univariate**: a multivariate frame is decomposed into N independent
  forecasts and static covariates are dropped. There is no pooling. A series
  is forecast from its own history and nothing else.

That last point is the whole reason this module has a floor. Four of the twelve
challenge targets lean on the pooled table for most of their rows — Hays'
pre-exceptional operating profit resolves 3 times in this corpus against 167
pooled rows — and handing TabPFN-TS three points would produce a number with
nothing behind it. `MIN_TS_POINTS` refuses those, and the caller routes them to
the path that can still defend an answer.

Mode is CLIENT, always. LOCAL would pull torch weights behind a licence gate;
the hosted API needs only TABPFN_TOKEN, which is the name both official SDKs
read (tabpfn_client/constants.py, tabpfn/browser_auth.py).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Mapping, Optional, Sequence

from .model import QUANTILES, Forecast

log = logging.getLogger(__name__)

#: Below this many of its *own* observations a series is not forecastable here.
#: TabPFN-TS has no pool to borrow strength from, so the floor is real rather
#: than conventional: at 3 points AutoSeasonalFeature has nothing to detect and
#: the running index is a two-parameter line.
MIN_TS_POINTS = 8

#: One point, the next period. Every challenge target is a single-period ahead
#: forecast.
HORIZON = 1


# ---------------------------------------------------------------------------
# Timestamps
#
# Fiscal periods are regular by construction; real print dates are not (Deere
# files a quarter 91 days after the last, then 98). Synthesising a regular grid
# off the fiscal label gives pandas a frequency it can infer every time, and
# costs nothing: TabPFN-TS reads the index for ordering and seasonality, not for
# the literal calendar day a filing landed.
# ---------------------------------------------------------------------------
def fiscal_timestamp(fy: int, quarter: Optional[int], half: Optional[int]):
    """A fiscal period as a regular period-end timestamp."""
    import pandas as pd

    if quarter:
        return pd.Period(year=fy, quarter=quarter, freq="Q").to_timestamp(how="end").normalize()
    if half:
        # Placed on the quarterly grid at the half's end, so a semi-annual
        # reporter infers as 2Q rather than becoming unorderable against one.
        return pd.Period(year=fy, quarter=half * 2, freq="Q").to_timestamp(how="end").normalize()
    return pd.Period(year=fy, freq="Y").to_timestamp(how="end").normalize()


Series = Sequence[tuple["date", float]]


def eligible(series: Series) -> bool:
    return len({t for t, _ in series}) >= MIN_TS_POINTS


# ---------------------------------------------------------------------------
def forecast_batch(
    history: Mapping[str, Series],
    targets: Mapping[str, "date"],
    quantiles: Sequence[float] = QUANTILES,
) -> dict[str, Forecast]:
    """Forecast many series in one call to the hosted model.

    `history` maps an item id to its own observations; `targets` maps the same
    ids to the timestamp being forecast. Series are independent under this
    model, so batching is free — and worth doing, since the round trip
    dominates the runtime.

    An explicit `future_df` is used rather than `prediction_length`. Two
    reasons: it pins the forecast to the period we actually want instead of
    whatever `generate_test_X` infers as "next", and it skips that inference
    entirely — which is what fails outright when the batch mixes quarterly and
    annual reporters (`freq` comes back None and the offset arithmetic raises).

    Returns a Forecast per id. Ids absent from the result failed; the caller
    decides what to do about that rather than being handed a fabricated number.
    """
    import pandas as pd

    from tabpfn_time_series import TabPFNMode, TabPFNTSPipeline

    usable = {k: v for k, v in history.items() if k in targets and eligible(v)}
    if not usable:
        return {}

    context = pd.DataFrame(
        [
            {"item_id": item, "timestamp": pd.Timestamp(ts), "target": float(value)}
            for item, series in usable.items()
            for ts, value in sorted(series)
        ]
    )
    future = pd.DataFrame(
        [{"item_id": item, "timestamp": pd.Timestamp(targets[item])} for item in usable]
    )

    pipeline = TabPFNTSPipeline(tabpfn_mode=TabPFNMode.CLIENT)
    predictions = pipeline.predict_df(context, future_df=future, quantiles=list(quantiles))

    out: dict[str, Forecast] = {}
    for item in usable:
        try:
            row = predictions.loc[item].iloc[0]
        except (KeyError, IndexError):
            log.warning("TabPFN-TS returned no row for %s", item)
            continue
        out[item] = Forecast(
            point=float(row["target"]),
            low=_column(row, 0.1),
            high=_column(row, 0.9),
            quantiles={q: v for q in quantiles if (v := _column(row, q)) is not None},
            model="tabpfn-ts",
            n_train=len(usable[item]),
            notes=[f"tabpfn-ts (CLIENT) · {len(usable[item])} own observations"],
        )
    return out


def _column(row, q: float) -> Optional[float]:
    """Read a quantile column.

    predict_df labels these with float keys, not the strings the docstring
    suggests, so both are tried before giving up.
    """
    for key in (q, str(q)):
        if key in row.index:
            return float(row[key])
    return None
