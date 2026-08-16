"""End-to-end run: corpus -> cited history -> signals -> forecast -> table.

This is the orchestration layer. It owns no financial logic of its own beyond
the baseline forecaster below; the numbers come from the aggregator and the
tilt comes from the signal subagents.

Every forecast records the base figures it was built from and their citations,
so a row in the final table can always be taken apart.
"""

from __future__ import annotations

import statistics
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from .aggregator.fiscal import FiscalPeriod
from .aggregator.panel import AmbiguousMetric, NotReported, Panel, Value

#: how far the call-tone signal is allowed to move a number. Its own docstring
#: says it is "a tilt on a forecast ... not a driver of the level", so it is
#: capped hard rather than trusted.
MAX_TILT = 0.03           # 3% for absolute metrics
MAX_TILT_PP = 0.5         # half a percentage point for rates and margins

STAGES = (
    ("index", "Index corpus"),
    ("periods", "Resolve periods"),
    ("history", "Extract history"),
    ("tone", "Call-tone signal"),
    ("forecast", "Forecast"),
    ("table", "Results"),
)


@dataclass
class MetricResult:
    company: str
    ticker: str
    period: str
    metric: str
    units: str
    value: float | None = None
    method: str = ""
    basis: list[dict] = field(default_factory=list)   # the figures it was built from
    cites: list[str] = field(default_factory=list)
    tilt: float = 0.0
    tone: dict | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "company": self.company, "ticker": self.ticker, "period": self.period,
            "metric": self.metric, "units": self.units,
            "value": None if self.value is None else round(self.value, 4),
            "method": self.method, "basis": self.basis, "cites": self.cites[:8],
            "tilt": round(self.tilt, 4), "tone": self.tone,
            "notes": self.notes, "error": self.error,
        }


@dataclass
class RunResult:
    started_at: str
    finished_at: str = ""
    results: list[MetricResult] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at, "finished_at": self.finished_at,
            "companies": self.companies,
            "results": [r.to_dict() for r in self.results],
            "filled": sum(1 for r in self.results if r.value is not None),
            "total": len(self.results),
        }


# ---------------------------------------------------------------------------
# baseline forecaster
# ---------------------------------------------------------------------------
def _yoy_ratios(series: list[tuple[FiscalPeriod, float]], lag: int) -> list[float]:
    by_period = {p: v for p, v in series}
    out = []
    for p, v in series:
        prior = FiscalPeriod(p.fy - 1, quarter=p.quarter, half=p.half)
        base = by_period.get(prior)
        if base and abs(base) > 1e-9 and v * base > 0:   # same sign, non-zero
            out.append(v / base)
    return out[-lag:]


def baseline_forecast(series: list[tuple[FiscalPeriod, float]],
                      target: FiscalPeriod) -> tuple[float | None, str, list[dict]]:
    """Seasonal year-on-year where possible, trend otherwise.

    Financial series are strongly seasonal — Home Depot's Q2 is its spring peak
    — so a plain trend on the raw sequence is wrong. Prefer the same period a
    year earlier, grown by the company's recent year-on-year rate.
    """
    if not series:
        return None, "no history", []
    series = sorted(series, key=lambda kv: kv[0].sort_key)
    by_period = {p: v for p, v in series}

    prior = FiscalPeriod(target.fy - 1, quarter=target.quarter, half=target.half)
    same_period_last_year = by_period.get(prior)
    ratios = _yoy_ratios(series, lag=4)

    if same_period_last_year is not None and ratios:
        growth = statistics.median(ratios)
        basis = [
            {"label": f"{prior} actual", "value": round(same_period_last_year, 4)},
            {"label": f"median YoY over {len(ratios)} periods",
             "value": round(growth, 4)},
        ]
        return same_period_last_year * growth, "seasonal YoY", basis

    if same_period_last_year is not None:
        return (same_period_last_year, "same period last year",
                [{"label": f"{prior} actual", "value": round(same_period_last_year, 4)}])

    # no seasonal anchor: trend the tail
    tail = [v for _, v in series][-5:]
    if len(tail) >= 3:
        deltas = [b - a for a, b in zip(tail, tail[1:])]
        est = tail[-1] + statistics.median(deltas)
        return est, "median drift", [
            {"label": f"{series[-1][0]} actual", "value": round(tail[-1], 4)},
            {"label": f"median change over {len(deltas)} steps",
             "value": round(statistics.median(deltas), 4)},
        ]
    return (tail[-1], "last reported",
            [{"label": f"{series[-1][0]} actual", "value": round(tail[-1], 4)}])


def tone_tilt(tone: dict | None) -> tuple[float, list[str]]:
    """Turn the call-tone ordinals into a small, signed adjustment.

    Ordinals are ordered but not metric, so they are mapped to fixed weights
    rather than used arithmetically. A channel that abstained contributes
    nothing — None means "not measured", never "neutral".
    """
    if not tone:
        return 0.0, []
    weights, notes = 0.0, []
    neg = tone.get("qa_neg_ord")
    if neg is not None:
        w = {0: +0.010, 1: 0.0, 2: -0.010, 3: -0.020}.get(neg, 0.0)
        weights += w
        notes.append(f"Q&A negativity {tone.get('qa_neg')} ({w:+.1%})")
    chg = tone.get("qa_neg_change_ord")
    if chg is not None:
        w = {0: +0.008, 1: 0.0, 2: -0.008, 3: -0.015}.get(chg, 0.0)
        weights += w
        notes.append(f"tone change {tone.get('qa_neg_change')} ({w:+.1%})")
    guide = tone.get("guidance_language_ord")
    if guide is not None:
        w = {0: -0.010, 1: 0.0, 2: +0.010}.get(guide, 0.0)
        weights += w
        notes.append(f"guidance language {tone.get('guidance_language')} ({w:+.1%})")
    return max(-MAX_TILT, min(MAX_TILT, weights)), notes


def apply_tilt(value: float, units: str, tilt: float) -> float:
    """A percentage metric moves in percentage points, not proportionally.

    A 3% proportional tilt on a 69.2% gross margin is 2.1pp, which is far more
    than this signal has earned. Rates get an absolute cap instead.
    """
    if "%" in units or units.strip().lower() in ("pct", "percent"):
        return value + max(-MAX_TILT_PP, min(MAX_TILT_PP, tilt * 100 * 0.25))
    return value * (1.0 + tilt)


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def _load_sentiment():
    """Import the signal subagent lazily; it needs pydantic, the aggregator does not."""
    try:
        from .signal_subagents.abc_subagent import SignalInput
        from .signal_subagents.sentiment import SentimentSignal
        return SignalInput, SentimentSignal
    except Exception:
        return None, None


def run(panel: Panel, companies: Iterable[str] | None = None,
        on_event: Callable[[str, str, dict], None] | None = None,
        history_periods: int = 10) -> RunResult:
    """Run the whole pipeline and return the filled table."""

    def emit(stage: str, message: str, **extra) -> None:
        if on_event:
            on_event(stage, message, extra)

    out = RunResult(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    wanted = None
    if companies:
        wanted = {panel._ticker(c) for c in companies}
    targets = [t for t in panel.targets if wanted is None or t.ticker in wanted]
    out.companies = sorted({t.ticker for t in targets})
    for t in targets:
        t.values.clear()      # a re-run replaces its own pushes, never stacks them

    emit("index", f"{len(panel.profiles)} companies indexed", count=len(panel.profiles))
    emit("periods", f"{sum(len(v) for v in panel._docs.values())} documents resolved")

    SignalInput, SentimentSignal = _load_sentiment()
    tone_cache: dict[tuple[str, str], dict | None] = {}

    for target in targets:
        res = MetricResult(
            company=panel.profiles[target.ticker].company, ticker=target.ticker,
            period=str(target.period), metric=target.metric_label, units=target.units,
        )
        try:
            emit("history", f"{target.ticker} · {target.metric_label}")
            hist = panel.history(target.ticker, target.metric_label, target.units,
                                 periods=history_periods, like=target.period)
            series = [(p, float(v)) for p, v in hist]
            res.cites = [v.cites[0] for _, v in hist if v.cites]
            if not series:
                res.error = "no citable history for this metric"
                out.results.append(res)
                continue

            # --- call-tone signal, once per (company, period) ---------------
            key = (target.ticker, str(target.period))
            if key not in tone_cache:
                tone_cache[key] = None
                if SignalInput and SentimentSignal:
                    try:
                        emit("tone", f"{target.ticker} · scoring earnings calls")
                        payload = panel.signal_input(target.ticker, target.period)
                        result = SentimentSignal().run(SignalInput(**payload))
                        tone_cache[key] = result.model_dump()
                    except Exception as exc:
                        tone_cache[key] = None
                        res.notes.append(f"call-tone signal unavailable: {exc}")
            res.tone = tone_cache[key]

            emit("forecast", f"{target.ticker} · {target.metric_label}")
            point, method, basis = baseline_forecast(series, target.period)
            if point is None:
                res.error = method
                out.results.append(res)
                continue

            tilt, tilt_notes = tone_tilt(res.tone)
            res.value = apply_tilt(point, target.units, tilt)
            res.method = method
            res.tilt = tilt
            res.basis = basis + [{"label": "pre-tilt forecast", "value": round(point, 4)}]
            res.notes += tilt_notes
            if res.tone and res.tone.get("notes"):
                res.notes += list(res.tone["notes"])[:2]

            panel.push(target.ticker, target.period, target.metric_label,
                       value=res.value, origin="pipeline:baseline+calltone",
                       because=f"{method}; tone tilt {tilt:+.2%}",
                       cites=res.cites or ["no-citation"], unit=target.units)
        except (NotReported, AmbiguousMetric) as exc:
            res.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # a broken metric must not sink the run
            res.error = f"{type(exc).__name__}: {exc}"
            res.notes.append(traceback.format_exc(limit=2))
        out.results.append(res)

    emit("table", f"{sum(1 for r in out.results if r.value is not None)}"
                  f"/{len(out.results)} forecasts produced")
    out.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def format_table(run_result: RunResult) -> str:
    """The plain-text table, for the terminal and the run log."""
    rows = run_result.results
    w_company = max((len(r.ticker) for r in rows), default=6)
    w_metric = max((len(r.metric) for r in rows), default=20)
    lines = [
        "",
        f"  {'CO':<{w_company}}  {'PERIOD':<10}  {'METRIC':<{w_metric}}  "
        f"{'FORECAST':>13}  {'UNITS':<12}  METHOD",
        f"  {'-' * (w_company + w_metric + 60)}",
    ]
    for r in rows:
        if r.value is None:
            shown, method = "—", (r.error or "")[:44]
        else:
            shown = f"{r.value:,.2f}"
            method = r.method + (f"  tilt {r.tilt:+.1%}" if r.tilt else "")
        lines.append(
            f"  {r.ticker:<{w_company}}  {r.period:<10}  {r.metric:<{w_metric}}  "
            f"{shown:>13}  {r.units:<12}  {method}"
        )
    filled = sum(1 for r in rows if r.value is not None)
    lines += ["", f"  {filled}/{len(rows)} forecasts produced", ""]
    return "\n".join(lines)
