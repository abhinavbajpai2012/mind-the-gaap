"""End-to-end run: corpus -> cited history -> signals -> forecast -> table.

This is the orchestration layer, and the run script `agent/forecast` deliberately
does not provide. It owns no financial logic of its own beyond the baseline
forecaster below; the numbers come from the aggregator, the framing from
`forecast.features`, and the forecast from `forecast.model`.

Two paths, and which one ran is always recorded:

1. **The model.** `FeatureBuilder` turns a target into a `Frame` — a pooled,
   backfilled matrix in year-on-year space — and `forecast.model` predicts the
   transform, which `Frame.invert()` turns back into a level. This is the
   intended path and covers ten of the twelve challenge targets.

2. **The baseline**, below, for a frame `Frame.usable` refuses. Two of the twelve
   land here: Home Depot's adjusted diluted EPS and comparable sales each resolve
   for only two periods in this corpus, which is not enough year-on-year rows to
   train on. The frame's own note says so, and it is carried into `notes` so the
   fallback is never mistaken for the model.

The call-tone tilt applies **only to the baseline path**. On the model path the
signal is already in the matrix — `features._covariates` folds the call-tone
channels in as columns, rebuilt at each row's own print date — so tilting the
output as well would count the same evidence twice.

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
    because: str = ""                    # the rationale carried into Panel.push
    # --- model path only; the baseline reports no interval it could defend ----
    model: str = ""                      # "tabpfn", "neighbours", or "" for baseline
    low: float | None = None             # 10th/90th percentile, as levels
    high: float | None = None
    n_train: int = 0                     # rows the model saw...
    n_own: int = 0                       # ...and how many were this metric's own

    def to_dict(self) -> dict:
        return {
            "company": self.company, "ticker": self.ticker, "period": self.period,
            "metric": self.metric, "units": self.units,
            "value": None if self.value is None else round(self.value, 4),
            "method": self.method, "basis": self.basis, "cites": self.cites[:8],
            "tilt": round(self.tilt, 4), "tone": self.tone,
            "notes": self.notes, "error": self.error, "because": self.because,
            "model": self.model,
            "low": None if self.low is None else round(self.low, 4),
            "high": None if self.high is None else round(self.high, 4),
            "n_train": self.n_train, "n_own": self.n_own,
        }


@dataclass
class RunResult:
    started_at: str
    finished_at: str = ""
    results: list[MetricResult] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # run-wide, e.g. which model

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at, "finished_at": self.finished_at,
            "companies": self.companies, "notes": self.notes,
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


def _load_forecast():
    """Import the forecast package lazily, for the same reason as the signal.

    It pulls in pydantic through `forecast.signals`, and `forecast.model` will
    reach for torch if tabpfn is installed. Neither is needed to run the
    baseline, so an environment missing them degrades instead of failing to
    import — the run says which forecaster produced each number anyway.
    """
    try:
        from .forecast.features import FeatureBuilder
        from .forecast.model import choose, preflight
        return FeatureBuilder, choose, preflight
    except Exception:
        return None, None, None


def _one_line(message: str) -> str:
    """A note fit for a table row.

    `preflight` quotes the library's own failure verbatim, and tabpfn's licence
    error is a ten-line block with numbered setup steps. The first line names
    the failure and the hint after the dash says what to do about it; the middle
    is the library repeating itself.
    """
    head, dash, hint = message.partition(" — ")
    head = head.splitlines()[0].rstrip()
    return f"{head}{dash}{hint}" if dash else head


def _pick_forecaster(choose, preflight, prefer: str, notes: list[str]):
    """Settle on one forecaster before the run, not once per target.

    `TabPFNForecaster` falls back per call, which is the right behaviour for a
    fit that dies halfway — but when the cause is a missing licence it is the
    same failure twelve times over, twelve stack unwinds and twelve warnings
    deep into a run that is already committed. `preflight` answers it once, on a
    toy table, before any frame is built.
    """
    if choose is None:
        return None
    if prefer == "neighbours":
        notes.append("neighbour forecaster requested")
        return choose("neighbours")

    working, why = preflight(prefer)
    notes.append(_one_line(why))
    if working:
        return choose(prefer)
    if prefer == "tabpfn":
        # The caller insisted. Downgrading silently would defeat the point of
        # having asked for it by name.
        raise RuntimeError(why)
    return choose("neighbours")


def _tone(panel: Panel, builder, frame, target,
          tone_cache: dict, SignalInput, SentimentSignal,
          res: MetricResult) -> dict | None:
    """The call-tone output for the period being forecast.

    Taken off the builder's own fan-out cache when there is one — the same run
    of the signal that produced the matrix columns, not a second one. Only when
    the forecast package is unavailable does this score the calls itself.
    """
    if builder is not None and frame is not None:
        as_of = frame.target_row.as_of if frame.target_row else None
        output = builder.fan_out(target.ticker, target.period, as_of).outputs.get("calltone")
        return output.model_dump() if output is not None else None

    key = (target.ticker, str(target.period))
    if key not in tone_cache:
        tone_cache[key] = None
        if SignalInput and SentimentSignal:
            try:
                payload = panel.signal_input(target.ticker, target.period)
                tone_cache[key] = SentimentSignal().run(SignalInput(**payload)).model_dump()
            except Exception as exc:
                res.notes.append(f"call-tone signal unavailable: {exc}")
    return tone_cache[key]


def _from_model(res: MetricResult, frame, forecaster) -> None:
    """Fill `res` from the model.

    `res.tilt` deliberately stays at zero. The call-tone channels are already
    columns of `frame.X`, so the signal has had its say before this point.
    """
    fc = forecaster.fit_predict(frame.X, frame.y, frame.x_pred,
                                categorical_indices=frame.categorical)
    unit = "pp" if frame.kind == "diff" else "%"
    scale = 1.0 if frame.kind == "diff" else 100.0

    res.value = frame.invert(fc.point)
    res.model = fc.model
    res.method = f"{fc.model} · {frame.n_self}/{len(frame.y)} rows"
    res.low = None if fc.low is None else frame.invert(fc.low)
    res.high = None if fc.high is None else frame.invert(fc.high)
    res.n_train, res.n_own = fc.n_train, frame.n_self
    res.cites = list(frame.cites)
    res.because = frame.because(fc)
    res.basis = [
        {"label": "prior-year base", "value": round(frame.base, 4)},
        {"label": f"forecast YoY ({unit})", "value": round(fc.point * scale, 4)},
    ]
    if fc.low is not None:
        res.basis += [
            {"label": f"p10 YoY ({unit})", "value": round(fc.low * scale, 4)},
            {"label": f"p90 YoY ({unit})", "value": round(fc.high * scale, 4)},
        ]
    res.notes += fc.notes + frame.notes


def _from_baseline(res: MetricResult, panel: Panel, target,
                   history_periods: int) -> None:
    """Fill `res` from the seasonal baseline, tilted by the call-tone signal.

    Reached only when the frame is unusable, so the history is pulled here
    rather than up front — on the model path `frame.cites` already carries the
    documents the forecast rests on, and `Panel.history` is not cheap.
    """
    hist = panel.history(target.ticker, target.metric_label, target.units,
                         periods=history_periods, like=target.period)
    series = [(p, float(v)) for p, v in hist]
    res.cites = [v.cites[0] for _, v in hist if v.cites]
    if not series:
        res.error = "no citable history for this metric"
        return

    point, method, basis = baseline_forecast(series, target.period)
    if point is None:
        res.error = method
        return

    tilt, tilt_notes = tone_tilt(res.tone)
    res.value = apply_tilt(point, target.units, tilt)
    res.method = f"{method} (baseline)"
    res.tilt = tilt
    res.basis = basis + [{"label": "pre-tilt forecast", "value": round(point, 4)}]
    res.notes += tilt_notes
    res.because = f"{method}; tone tilt {tilt:+.2%}"


def make_builder(panel: Panel):
    """A `FeatureBuilder` for this panel, or None if the package is unavailable.

    Worth holding on to. Its caches — metric levels, the signal fan-out per
    print date, each series' backfilled rows — are what the ~40s of a first run
    buys, and none of it depends on which companies were asked for. A second run
    that reuses the builder is seconds; one that rebuilds it pays in full again.
    """
    FeatureBuilder, _, _ = _load_forecast()
    return FeatureBuilder(panel) if FeatureBuilder else None


def run(panel: Panel, companies: Iterable[str] | None = None,
        on_event: Callable[[str, str, dict], None] | None = None,
        history_periods: int = 10, prefer: str = "auto",
        builder=None) -> RunResult:
    """Run the whole pipeline and return the filled table.

    `prefer` is passed to `forecast.model.choose`: "auto" uses TabPFN when it
    imports and falls back per call, "neighbours" skips it, "tabpfn" insists.

    `builder` is an optional `FeatureBuilder` to reuse across runs — see
    `make_builder`. One is made here when it is not supplied.
    """

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
    _, choose, preflight = _load_forecast()
    tone_cache: dict[tuple[str, str], dict | None] = {}
    guidance_cache: dict[tuple[str, str], list] = {}

    if builder is None:
        builder = make_builder(panel)
    forecaster = _pick_forecaster(choose, preflight, prefer, out.notes)
    if builder is None or forecaster is None:
        out.notes.append("forecast package unavailable; every row uses the baseline")
    scored: set[str] = set()   # companies whose fan-out has been announced

    for target in targets:
        res = MetricResult(
            company=panel.profiles[target.ticker].company, ticker=target.ticker,
            period=str(target.period), metric=target.metric_label, units=target.units,
        )
        try:
            # --- frame: history, backfill and the signal fan-out ------------
            # One call does all three. It is the expensive step (~40s for the
            # twelve targets), and it is where the as-of cutoff is enforced.
            emit("history", f"{target.ticker} · {target.metric_label}")
            frame = None
            if builder is not None:
                if target.ticker not in scored:
                    scored.add(target.ticker)
                    emit("tone", f"{target.ticker} · scoring earnings calls")
                try:
                    frame = builder.build_target(target)
                except Exception as exc:
                    res.notes.append(
                        f"frame build failed, falling back to the baseline: "
                        f"{type(exc).__name__}: {exc}"
                    )

            res.tone = _tone(panel, builder, frame, target, tone_cache,
                             SignalInput, SentimentSignal, res)

            emit("forecast", f"{target.ticker} · {target.metric_label}")
            if frame is not None and frame.usable and forecaster is not None:
                _from_model(res, frame, forecaster)
            else:
                if frame is not None and not frame.usable:
                    # The frame's own explanation of why it refused. It names the
                    # metric label and the aggregator gap behind it, so this is
                    # the note worth keeping.
                    res.notes += frame.notes
                _from_baseline(res, panel, target, history_periods)

            # Adversarial check: does the company's own guidance for this exact
            # period contradict the forecast? Guidance can veto a model; a model
            # cannot veto guidance. ADI published "third quarter of fiscal 2026
            # ... revenue of $3.9 billion, +/- $100 million" — a model output of
            # 3.26bn is not conservative, it is wrong against a public number.
            if res.value is not None:
                try:
                    from .guidance import challenge, extract_guidance
                    guides = guidance_cache.get(key_gp := (target.ticker,
                                                           str(target.period)))
                    if guides is None:
                        guides = extract_guidance(panel, target.ticker, target.period)
                        guidance_cache[key_gp] = guides
                    verdict = challenge(res.value, target.metric_label,
                                        target.units, guides)
                    if verdict.action == "overridden":
                        res.notes.append(f"ADVERSARIAL: {verdict.reason}")
                        res.notes += verdict.notes
                        res.value = verdict.value
                        res.method = f"company guidance (overrode {res.method})"
                        if verdict.guided:
                            res.cites = [verdict.guided.cite] + list(res.cites)
                            res.because = (f"company guided {verdict.guided.mid:g} "
                                           f"for this period")
                    elif verdict.action == "kept" and verdict.guided:
                        res.notes.append(
                            f"guidance check: within company guidance "
                            f"{verdict.guided.mid:g} ({verdict.guided.cite})")
                except Exception as exc:
                    res.notes.append(f"guidance check unavailable: {exc}")

            if res.tone and res.tone.get("notes"):
                res.notes += list(res.tone["notes"])[:2]
            if res.value is None:
                out.results.append(res)
                continue

            panel.push(target.ticker, target.period, target.metric_label,
                       value=res.value,
                       origin=f"pipeline:{res.model}" if res.model
                              else "pipeline:baseline+calltone",
                       because=res.because,
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
    modelled = sum(1 for r in rows if r.model)
    lines += ["", f"  {filled}/{len(rows)} forecasts produced "
                  f"({modelled} from the model, {filled - modelled} from the baseline)"]
    lines += [f"  note: {n}" for n in run_result.notes]
    lines += [""]
    return "\n".join(lines)
