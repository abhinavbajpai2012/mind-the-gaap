"""Forecast: aggregator + signal subagents -> a table -> a forecast.

Three modules, one dependency rule: `forecast` imports `aggregator` and
`signal_subagents`; neither of them ever imports `forecast`.

Named `forecast`, not `pipeline`, because `agent/pipeline.py` already owns
that name — it is the run script this package deliberately does not provide.

    signals.py    run every registered signal for one (company, period, as_of)
    features.py   Panel history + signal outputs -> the matrix (owns the backfill)
    model.py      matrix -> forecast. Imports nothing of ours, so it stays
                  swappable and testable without a Panel build.

The entry point is deliberately absent — it belongs to whoever owns the run
script. What it needs is two calls per target:

    from agent.aggregator.panel import Panel
    from agent.forecast.features import FeatureBuilder
    from agent.forecast.model import choose

    panel = Panel.challenge()
    builder = FeatureBuilder(panel)
    forecaster = choose()

    for target in panel.targets:
        frame = builder.build_target(target)
        if not frame.usable:
            continue                       # see frame.notes for why
        forecast = forecaster.fit_predict(frame.X, frame.y, frame.x_pred,
                                          categorical_indices=frame.categorical)
        panel.push(target.ticker, target.period, target.metric_label,
                   value=frame.invert(forecast.point),
                   origin="model",
                   because=frame.because(forecast),
                   cites=frame.cites,
                   unit=target.units)

`frame.invert()` is not optional: the model forecasts a scale-free transform
(year-on-year growth, or a percentage-point difference), never the level, so
that four companies in three currencies can share one table. The level comes
back only by re-applying the prior-year base the frame carries.
"""
