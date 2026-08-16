#!/usr/bin/env python3
"""Head-to-head holdout: seasonal baseline vs TabPFN-TS-3, on identical data.

One fold. For each target the last observed period is held out, every engine
forecasts it from the periods before, and the absolute percentage error is
compared. Crude — one fold is one draw — but it is the same draw for every
engine, which is what makes it a comparison rather than two anecdotes.

The pooled path (neighbours, and the eleven sklearn families in selector.py) is
already scored over an expanding window in output/backtest.json; it is not
re-run here because rebuilding a Frame at each historical cutoff costs a full
Panel pass per fold.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.aggregator.panel import Panel                    # noqa: E402
from agent.forecast.features import grain_of                # noqa: E402
from agent.forecast.model_ts import (                       # noqa: E402
    MIN_TS_POINTS, eligible, fiscal_timestamp, forecast_batch)
from agent.pipeline import baseline_forecast, make_builder  # noqa: E402


def ape(pred, truth):
    if pred is None or truth is None or abs(truth) < 1e-9:
        return None
    return abs(pred - truth) / abs(truth) * 100.0


def main() -> int:
    panel = Panel.challenge()
    builder = make_builder(panel)

    hist, tgt_ts, truth, train_raw, meta = {}, {}, {}, {}, {}

    for t in panel.targets:
        item = f"{t.ticker}::{t.metric_label}"
        levels = builder.levels(t.ticker, t.metric_label, t.units, grain_of(t.period))
        obs = sorted(((p, float(v)) for p, v in levels.items()
                      if p.sort_key < t.period.sort_key), key=lambda kv: kv[0].sort_key)
        if len(obs) < 3:
            continue
        holdout_period, holdout_value = obs[-1]
        train = obs[:-1]

        meta[item] = (t, holdout_period)
        truth[item] = holdout_value
        train_raw[item] = train
        hist[item] = [(fiscal_timestamp(p.fy, p.quarter, p.half), v) for p, v in train]
        tgt_ts[item] = fiscal_timestamp(holdout_period.fy, holdout_period.quarter,
                                        holdout_period.half)

    ts_out = forecast_batch(hist, tgt_ts)

    rows = []
    for item, (t, hp) in meta.items():
        base_pred, base_method, _ = baseline_forecast(train_raw[item], hp)
        ts_pred = ts_out[item].point if item in ts_out else None
        rows.append((t, hp, truth[item], base_pred, ape(base_pred, truth[item]),
                     ts_pred, ape(ts_pred, truth[item]),
                     len(train_raw[item]), base_method))

    w = max(len(t.metric_label) for t, *_ in rows)
    print(f"\n  {'CO':<4} {'METRIC':<{w}} {'HELD OUT':<9} {'ACTUAL':>11} "
          f"{'BASELINE':>11} {'APE%':>7} {'TABPFN-TS':>11} {'APE%':>7}  n")
    print("  " + "-" * (w + 76))
    for t, hp, actual, bp, bape, tp, tape in [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]:
        n = [r[7] for r in rows if r[0] is t][0]
        f = lambda v: "—" if v is None else f"{v:,.2f}"
        g = lambda v: "—" if v is None else f"{v:6.1f}"
        print(f"  {t.ticker:<4} {t.metric_label:<{w}} {str(hp):<9} {f(actual):>11} "
              f"{f(bp):>11} {g(bape):>7} {f(tp):>11} {g(tape):>7}  {n}")

    both = [(r[4], r[6]) for r in rows if r[4] is not None and r[6] is not None]
    print(f"\n  targets where both engines produced a number: {len(both)}")
    if both:
        mb = sum(b for b, _ in both) / len(both)
        mt = sum(t for _, t in both) / len(both)
        wins = sum(1 for b, t in both if t < b)
        print(f"  mean APE  baseline {mb:6.2f}%   tabpfn-ts {mt:6.2f}%")
        print(f"  median APE baseline {sorted(b for b,_ in both)[len(both)//2]:6.2f}%"
              f"   tabpfn-ts {sorted(t for _,t in both)[len(both)//2]:6.2f}%")
        print(f"  tabpfn-ts closer on {wins}/{len(both)}")
    only_base = [r for r in rows if r[6] is None]
    print(f"  baseline-only (below MIN_TS_POINTS={MIN_TS_POINTS}): {len(only_base)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
