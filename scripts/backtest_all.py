#!/usr/bin/env python3
"""Walk-forward comparison of every available forecaster, on identical folds.

    python3 scripts/backtest_all.py [n_folds]

Three families compete, and they do not see the same inputs — which is the
point of running them together rather than trusting each one's own scorecard:

  series-level   naive_last, seasonal_naive, drift, mean, baseline
                 own history only, no pooling
  time-series    tabpfn_ts            TabPFN-TS-3 over the hosted API
  frame-level    neighbours, selector, tabpfn3
                 the pooled year-on-year matrix from features.py

LEAKAGE GUARD. A held-out period's own figure exists in the corpus, so building
a Frame for it naively would train on the answer. Every fold sets
`as_of = print_date(P) - 1 day`, the day before that period's results reached
the corpus, and the builder enforces the cutoff. Series engines are handed only
periods strictly before P.

Scored on absolute percentage error against the reported figure.
"""

from __future__ import annotations

import statistics
import sys
import traceback
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.aggregator.panel import Panel                     # noqa: E402
from agent.forecast.features import grain_of, prior_year     # noqa: E402
from agent.forecast.model import choose, preflight           # noqa: E402
from agent.forecast.model_ts import (                        # noqa: E402
    MIN_TS_POINTS, eligible, fiscal_timestamp, forecast_batch)
from agent.pipeline import baseline_forecast, make_builder   # noqa: E402

N_FOLDS = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def ape(pred, truth):
    if pred is None or truth is None or abs(truth) < 1e-9:
        return None
    return abs(pred - truth) / abs(truth) * 100.0


# ---- series-level engines: (periods before P, P) -> level -----------------
def naive_last(train, P):
    return train[-1][1] if train else None


def seasonal_naive(train, P):
    return dict(train).get(prior_year(P))


def drift(train, P):
    if len(train) < 3:
        return None
    tail = [v for _, v in train][-5:]
    return tail[-1] + statistics.median(b - a for a, b in zip(tail, tail[1:]))


def mean_(train, P):
    return statistics.fmean(v for _, v in train[-8:]) if train else None


def baseline(train, P):
    return baseline_forecast(train, P)[0]


SERIES_ENGINES = {"naive_last": naive_last, "seasonal_naive": seasonal_naive,
                  "drift": drift, "mean": mean_, "baseline": baseline}


def main() -> int:
    print(f"walk-forward, {N_FOLDS} folds per target", flush=True)
    panel = Panel.challenge()
    builder = make_builder(panel)

    frame_engines = {"neighbours": choose("neighbours"), "selector": choose("selector")}

    # Local first, because it needs no network; it is expected to fail here with
    # TabPFNLicenseError until someone accepts the licence at ux.priorlabs.ai.
    # The client backend runs the identical estimator server-side on the token
    # alone, so TabPFN-3 is scored either way rather than silently missing.
    for backend in ("local", "client"):
        ok, why = preflight("tabpfn", backend=backend)
        print(f"tabpfn-3 preflight [{backend}]: {ok} — {why.splitlines()[0]}", flush=True)
        if ok:
            frame_engines[f"tabpfn3_{backend}"] = choose("tabpfn", backend=backend)
            break

    errs: dict[str, list[float]] = defaultdict(list)
    per_target: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    plan: list[tuple] = []

    for t in panel.targets:
        levels = builder.levels(t.ticker, t.metric_label, t.units, grain_of(t.period))
        obs = sorted(((p, float(v)) for p, v in levels.items()
                      if p.sort_key < t.period.sort_key), key=lambda kv: kv[0].sort_key)
        for i in range(1, min(N_FOLDS, max(0, len(obs) - 2)) + 1):
            P, truth = obs[-i]
            train = obs[:-i]
            if len(train) < 3:
                continue
            pd_ = builder.print_date(t.ticker, P)
            plan.append((i, t, P, truth, train, (pd_ - timedelta(days=1)) if pd_ else None))

    print(f"{len(plan)} (target, fold) pairs\n", flush=True)

    # ---- series + frame engines -------------------------------------------
    for i, t, P, truth, train, cutoff in plan:
        key = f"{t.ticker}::{t.metric_label}"
        for name, fn in SERIES_ENGINES.items():
            try:
                e = ape(fn(train, P), truth)
            except Exception:
                e = None
            if e is not None:
                errs[name].append(e); per_target[key][name].append(e)

        if not frame_engines:
            continue
        try:
            frame = builder.build(t.ticker, t.metric_label, t.units, P, as_of=cutoff)
        except Exception:
            continue
        if not frame.usable:
            continue
        for name, engine in frame_engines.items():
            try:
                fc = engine.fit_predict(frame.X, frame.y, frame.x_pred,
                                        categorical_indices=frame.categorical)
                e = ape(frame.invert(fc.point), truth)
            except Exception:
                e = None
            if e is not None:
                errs[name].append(e); per_target[key][name].append(e)
        print(".", end="", flush=True)

    # ---- tabpfn-ts, batched one call per fold index ------------------------
    for i in range(1, N_FOLDS + 1):
        hist, tgt, truths, keys = {}, {}, {}, {}
        for j, t, P, truth, train, _ in plan:
            if j != i:
                continue
            key = f"{t.ticker}::{t.metric_label}"
            series = [(fiscal_timestamp(p.fy, p.quarter, p.half), v) for p, v in train]
            if not eligible(series):
                continue
            hist[key] = series
            tgt[key] = fiscal_timestamp(P.fy, P.quarter, P.half)
            truths[key] = truth
            keys[key] = key
        if not hist:
            continue
        try:
            out = forecast_batch(hist, tgt)
        except Exception as exc:
            print(f"\ntabpfn-ts fold {i} failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        for key, fc in out.items():
            e = ape(fc.point, truths[key])
            if e is not None:
                errs["tabpfn_ts"].append(e); per_target[key]["tabpfn_ts"].append(e)
        print(f"\ntabpfn-ts fold {i}: {len(out)} forecasts", flush=True)

    # ---- report ------------------------------------------------------------
    print("\n\n=== overall (absolute percentage error) ===")
    print(f"  {'ENGINE':<16} {'FOLDS':>6} {'MEAN':>9} {'MEDIAN':>9} {'p90':>9}")
    print("  " + "-" * 54)
    ranked = sorted(errs.items(), key=lambda kv: statistics.median(kv[1]))
    for name, es in ranked:
        p90 = sorted(es)[int(0.9 * (len(es) - 1))]
        print(f"  {name:<16} {len(es):>6} {statistics.fmean(es):>8.2f}% "
              f"{statistics.median(es):>8.2f}% {p90:>8.2f}%")

    print("\n=== per-target winner (median APE, engines with >=3 folds) ===")
    for key in sorted(per_target):
        scored = {n: statistics.median(v) for n, v in per_target[key].items() if len(v) >= 3}
        if not scored:
            print(f"  {key:<52} — too few folds")
            continue
        best = min(scored, key=scored.get)
        rest = "  ".join(f"{n}={scored[n]:.1f}" for n in sorted(scored, key=scored.get)[1:4])
        print(f"  {key:<52} {best:<15} {scored[best]:6.2f}%   ({rest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
