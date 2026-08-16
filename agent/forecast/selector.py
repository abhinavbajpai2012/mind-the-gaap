"""A forecaster that picks its own model by walk-forward backtest.

Implements the same `fit_predict(X, y, x_pred, categorical_indices)` contract as
NeighbourForecaster and TabPFNForecaster, so it drops into `choose()` and the
rest of the pipeline never learns which model produced a number.

What it adds is the selection step. Eleven regression families compete against
the neighbour model and against two naive baselines, scored on an expanding
window that never sees the future. The winner is refit on everything and
predicts once. If nothing beats the incumbent neighbour model out of sample,
the neighbour model is returned — a backtest that cannot beat the thing it is
replacing is a reason to keep the incumbent, not to override it.

The matrix arrives in year-on-year space from features.py, already lagged, so
there is no leakage to guard against here beyond respecting row order: the rows
are chronological and every fold trains only on rows before the one it scores.
"""

from __future__ import annotations

import warnings
from typing import Optional, Sequence

import numpy as np

warnings.filterwarnings("ignore")

from .model import Forecast, NeighbourForecaster  # noqa: E402

MIN_TRAIN = 8      # below this a fold's training set is not worth fitting
MIN_FOLDS = 4      # below this a score is noise
MAX_FOLDS = 40     # cap the work; recent folds matter most


def _families(n_rows: int, n_cols: int):
    """Candidates, gated on how much data there actually is."""
    from sklearn.dummy import DummyRegressor
    from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                                  RandomForestRegressor)
    from sklearn.linear_model import BayesianRidge, ElasticNetCV, HuberRegressor, RidgeCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    def scaled(m):
        return Pipeline([("s", StandardScaler()), ("m", m)])

    out = [("ridge", scaled(RidgeCV(alphas=np.logspace(-3, 3, 25)))),
           ("bayes_ridge", scaled(BayesianRidge())),
           ("median", DummyRegressor(strategy="median"))]
    if n_rows >= 20:
        out += [("elasticnet", scaled(ElasticNetCV(cv=3, max_iter=5000))),
                ("huber", scaled(HuberRegressor(max_iter=500)))]
    if n_rows >= 30:
        out += [("random_forest", RandomForestRegressor(
                    n_estimators=300, max_depth=3, min_samples_leaf=3, random_state=0)),
                ("extra_trees", ExtraTreesRegressor(
                    n_estimators=300, max_depth=3, min_samples_leaf=3, random_state=0))]
    if n_rows >= 45:
        out += [("grad_boost", GradientBoostingRegressor(
                    n_estimators=200, max_depth=2, learning_rate=.05,
                    subsample=.9, random_state=0))]
    return out


def _clean(X, y, x_pred):
    """Numeric matrix with NaN columns dropped and remaining NaNs median-filled.

    Dropping whole columns rather than rows because the call-tone channels
    abstain on most early rows: imputing them would invent a tone for calls
    that were never scored, and dropping the rows would delete the history.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    xp = np.asarray(x_pred, dtype=float).reshape(1, -1)
    keep = [j for j in range(X.shape[1])
            if np.isfinite(X[:, j]).sum() >= max(6, int(0.6 * len(y)))
            and np.isfinite(xp[0, j])]
    if not keep:
        return None, None, None
    X, xp = X[:, keep], xp[:, keep]
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    X = np.where(np.isfinite(X), X, med)
    xp = np.where(np.isfinite(xp), xp, med)
    ok = np.isfinite(y)
    return X[ok], y[ok], xp


class BacktestSelector:
    """Chooses among model families by expanding-window backtest."""

    name = "selector"

    def __init__(self, incumbent: Optional[object] = None):
        self.incumbent = incumbent or NeighbourForecaster()
        self.report: list[tuple[str, float, int]] = []

    # -- the contract -------------------------------------------------------
    def fit_predict(self, X, y, x_pred, categorical_indices: Sequence[int] = ()) -> Forecast:
        base = self.incumbent.fit_predict(X, y, x_pred,
                                          categorical_indices=categorical_indices)
        Xc, yc, xp = _clean(X, y, x_pred)
        if Xc is None or len(yc) < MIN_TRAIN + MIN_FOLDS:
            base.notes = list(base.notes) + [
                f"selector: {0 if yc is None else len(yc)} usable rows, "
                f"need {MIN_TRAIN + MIN_FOLDS} — kept {base.model}"]
            return base

        n = len(yc)
        start = max(MIN_TRAIN, n - MAX_FOLDS)
        errs: dict[str, list[float]] = {}

        for cut in range(start, n):
            X_tr, y_tr, y_te, x_te = Xc[:cut], yc[:cut], yc[cut], Xc[cut:cut + 1]

            # the incumbent is scored on exactly the same folds
            try:
                p = self.incumbent.fit_predict(
                    X_tr.tolist(), y_tr.tolist(), x_te[0].tolist()).point
                errs.setdefault(self.incumbent.name, []).append(abs(y_te - p))
            except Exception:
                pass
            errs.setdefault("last_value", []).append(abs(y_te - y_tr[-1]))
            errs.setdefault("median", []).append(abs(y_te - float(np.median(y_tr))))

            for name, model in _families(cut, Xc.shape[1]):
                try:
                    model.fit(X_tr, y_tr)
                    errs.setdefault(name, []).append(
                        abs(y_te - float(model.predict(x_te)[0])))
                except Exception:
                    continue

        scored = [(k, float(np.median(v)), len(v))
                  for k, v in errs.items() if len(v) >= MIN_FOLDS]
        if not scored:
            base.notes = list(base.notes) + ["selector: no model scored on enough folds"]
            return base
        scored.sort(key=lambda t: t[1])
        self.report = scored

        winner, win_mae, folds = scored[0]
        incumbent_mae = next((m for k, m, _ in scored if k == self.incumbent.name), None)

        # a tie goes to the incumbent: a new model must earn the swap
        if (winner in (self.incumbent.name, "last_value", "median")
                or (incumbent_mae is not None and win_mae >= incumbent_mae * 0.98)):
            base.notes = list(base.notes) + [
                f"selector: {len(scored)} models backtested over {folds} folds; "
                f"{base.model} retained (MAE {incumbent_mae:.4f})"
                if incumbent_mae is not None else
                f"selector: {base.model} retained"]
            return base

        model = dict(_families(n, Xc.shape[1]))[winner]
        model.fit(Xc, yc)
        point = float(model.predict(xp)[0])

        # residual spread on the backtest folds, as an honest interval
        resid = np.array(errs[winner], dtype=float)
        spread = float(np.quantile(resid, 0.8)) if len(resid) >= MIN_FOLDS else None

        notes = [f"selector: {winner} won a walk-forward backtest of {len(scored)} "
                 f"models over {folds} folds (MAE {win_mae:.4f}"
                 + (f" vs {self.incumbent.name} {incumbent_mae:.4f})" if incumbent_mae
                    is not None else ")")]
        notes.append("runners-up: " + ", ".join(
            f"{k} {m:.4f}" for k, m, _ in scored[1:4]))
        return Forecast(
            point=point,
            low=None if spread is None else point - spread,
            high=None if spread is None else point + spread,
            model=winner,
            n_train=n,
            notes=notes,
        )
