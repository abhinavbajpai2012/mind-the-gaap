#!/usr/bin/env python3
"""Forecast all twelve challenge targets, routing each to a model that can defend it.

    python3 scripts/run_tabpfn_ts.py

TabPFN-TS-3 is univariate: it forecasts a series from its own history and has no
pool to borrow from. Eight of the twelve targets carry enough of their own
observations for that; four do not, and are routed to the seasonal baseline
instead of being handed to a model that would answer from three points.

Which engine produced each number is printed, and never inferred.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.aggregator.panel import Panel                      # noqa: E402
from agent.forecast.features import grain_of                  # noqa: E402
from agent.forecast.model_ts import (                         # noqa: E402
    MIN_TS_POINTS,
    eligible,
    fiscal_timestamp,
    forecast_batch,
)
from agent.pipeline import baseline_forecast, make_builder    # noqa: E402


def stamp(period) -> object:
    return fiscal_timestamp(period.fy, period.quarter, period.half)


def main() -> int:
    print("indexing corpus...", flush=True)
    panel = Panel.challenge()
    builder = make_builder(panel)
    if builder is None:
        print("forecast package unavailable", file=sys.stderr)
        return 1

    history: dict[str, list[tuple[object, float]]] = {}
    target_ts: dict[str, object] = {}
    raw: dict[str, list[tuple[object, float]]] = {}   # (FiscalPeriod, value) for the baseline
    meta: dict[str, object] = {}

    for t in panel.targets:
        item = f"{t.ticker}::{t.metric_label}"
        meta[item] = t
        levels = builder.levels(t.ticker, t.metric_label, t.units, grain_of(t.period))
        observed = sorted(
            ((p, float(v)) for p, v in levels.items() if p.sort_key < t.period.sort_key),
            key=lambda kv: kv[0].sort_key,
        )
        raw[item] = observed
        history[item] = [(stamp(p), v) for p, v in observed]
        target_ts[item] = stamp(t.period)

    routed = [i for i in history if eligible(history[i])]
    print(f"\n{len(routed)}/{len(history)} targets have >= {MIN_TS_POINTS} own "
          f"observations -> TabPFN-TS; the rest -> seasonal baseline", flush=True)

    print("calling TabPFN-TS (CLIENT)...", flush=True)
    ts = forecast_batch(history, target_ts)
    print(f"TabPFN-TS returned {len(ts)} forecasts\n", flush=True)

    rows = []
    for item, t in meta.items():
        if item in ts:
            fc = ts[item]
            band = "" if fc.low is None else f"[{fc.low:,.2f} – {fc.high:,.2f}]"
            rows.append((t, fc.point, "tabpfn-ts", f"n={fc.n_train}  {band}"))
            continue
        point, method, _ = baseline_forecast(raw[item], t.period)
        why = f"{len(raw[item])} own obs < {MIN_TS_POINTS}" if point is not None else "no history"
        rows.append((t, point, "baseline", f"{method}; {why}"))

    w_metric = max(len(t.metric_label) for t in meta.values())
    print(f"  {'CO':<4}  {'PERIOD':<9}  {'METRIC':<{w_metric}}  {'FORECAST':>12}  "
          f"{'UNITS':<12}  ENGINE      DETAIL")
    print(f"  {'-' * (w_metric + 78)}")
    for t, value, engine, detail in rows:
        shown = "—" if value is None else f"{value:,.2f}"
        print(f"  {t.ticker:<4}  {str(t.period):<9}  {t.metric_label:<{w_metric}}  "
              f"{shown:>12}  {t.units:<12}  {engine:<10}  {detail}")

    filled = sum(1 for _, v, _, _ in rows if v is not None)
    by_ts = sum(1 for _, v, e, _ in rows if v is not None and e == "tabpfn-ts")
    print(f"\n  {filled}/{len(rows)} forecast "
          f"({by_ts} from TabPFN-TS, {filled - by_ts} from the baseline)")
    return 0 if filled == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
