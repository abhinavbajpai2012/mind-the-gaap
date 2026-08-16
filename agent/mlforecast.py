"""Data-scientist stage: choose a model per target, by backtest.

The target series comes from the aggregator's validated extraction path, not
from the wide CSV. Those two disagree for a reason: the wide table collapses
every row that parses to a concept, so its "revenue" column mixes the group's
net sales with incidental revenue lines, while `Panel.history` returns the
figure that survived ranking and unit checks. Targets must be right; features
only need to be informative, so the wide table is used for features alone.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .aggregator.corpus import REPO_ROOT
from .aggregator.panel import AmbiguousMetric, NotReported, Panel
from .datascientist import Fit, fit_target
from .export_csv import OUTPUT_ROOT, _slug

#: never offer a feature that is the target restated
_ALWAYS_DROP = {"fiscal_period", "fiscal_year", "fiscal_quarter", "period_end"}


def load_wide(company: str, annual: bool = False) -> list[dict]:
    name = "metrics_wide_annual.csv" if annual else "metrics_wide.csv"
    path = OUTPUT_ROOT / _slug(company) / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_panel_rows(panel: Panel, ticker: str, metric: str, units: str,
                     target_period, periods: int = 40) -> tuple[list[dict], str]:
    """Rows of {fiscal_period, target, ...features}, oldest first.

    The target column is the aggregator's cited value. Features are joined from
    the wide CSV on fiscal period, so a feature is only ever a figure that was
    already public when that period printed.
    """
    hist = panel.history(ticker, metric, units, periods=periods, like=target_period)
    if not hist:
        return [], "no citable history"
    company = panel.profiles[ticker].company
    annual = target_period.quarter is None and target_period.half is None
    wide = {r["fiscal_period"]: r for r in load_wide(company, annual=annual)}

    target_key = "__target__"
    rows = []
    for period, value in hist:
        src = wide.get(str(period), {})
        row = {"fiscal_period": str(period), "fiscal_year": period.fy,
               "fiscal_quarter": period.quarter or (period.half or 5),
               target_key: float(value)}
        for k, v in src.items():
            if k in _ALWAYS_DROP or v in ("", None):
                continue
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                continue
        rows.append(row)
    return rows, target_key


def fit_one(panel: Panel, ticker: str, metric: str, units: str, target_period) -> Fit:
    rows, key = build_panel_rows(panel, ticker, metric, units, target_period)
    if not rows:
        return Fit(metric, "no_history", [], type("F", (), {"selected": [], "considered": 0})(),
                   None, 0, 4, note=key)
    season = 4 if target_period.quarter else (2 if target_period.half else 1)
    fit = fit_target(rows, key, season=season)
    fit.target = metric
    return fit


def backtest_report(panel: Panel, targets=None) -> list[dict]:
    """Score every challenge target and report which method wins, honestly."""
    out = []
    for t in (targets or panel.targets):
        try:
            fit = fit_one(panel, t.ticker, t.metric_label, t.units, t.period)
        except (NotReported, AmbiguousMetric) as exc:
            out.append({"ticker": t.ticker, "metric": t.metric_label,
                        "best_model": "error", "note": str(exc)[:80]})
            continue
        d = fit.to_dict()
        d.update({"ticker": t.ticker, "metric": t.metric_label,
                  "period": str(t.period), "units": t.units})
        out.append(d)
    return out


def format_backtest(rows: list[dict]) -> str:
    w = max((len(r["metric"]) for r in rows), default=20)
    lines = ["",
             f"  {'CO':<5} {'METRIC':<{w}} {'N':>3} {'BEST MODEL':<16} "
             f"{'MAPE':>8} {'BASELINE':>9}  VERDICT",
             f"  {'-' * (w + 62)}"]
    for r in rows:
        scores = r.get("scores") or []
        mape = f"{scores[0]['mape']:.1%}" if scores else "—"
        base = r.get("baseline_mape")
        base_s = f"{base:.1%}" if base is not None else "—"
        lines.append(f"  {r['ticker']:<5} {r['metric']:<{w}} {r.get('n_rows', 0):>3} "
                     f"{r.get('best_model', '?'):<16} {mape:>8} {base_s:>9}  "
                     f"{(r.get('note') or '')[:38]}")
    return "\n".join(lines) + "\n"
