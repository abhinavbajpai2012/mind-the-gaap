"""Model selection by walk-forward backtest.

The discipline here matters more than the model list. Financial panels of this
size hold 15-50 quarters. A gradient booster with 40 features and 30 rows will
fit the training set perfectly and forecast nothing, so:

  * every score is out-of-sample, from an expanding window that never sees the
    future — no shuffled k-fold, which would leak later quarters into earlier
    training and flatter every model;
  * features are lagged. A quarter's own revenue cannot predict that quarter's
    revenue; only information available before the print is admissible;
  * the seasonal-naive baseline competes on the same footing. If nothing beats
    it, the baseline is the answer, and that is a result rather than a failure;
  * candidate models are capped in complexity relative to n, and a model needing
    more rows than exist is not run at all.

Selection is by median absolute percentage error across the walk-forward folds,
with the mean as a tie-break, because a single bad quarter should not decide it.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

warnings.filterwarnings("ignore")

from sklearn.dummy import DummyRegressor                      # noqa: E402
from sklearn.ensemble import (ExtraTreesRegressor,            # noqa: E402
                              GradientBoostingRegressor, RandomForestRegressor)
from sklearn.linear_model import (BayesianRidge, ElasticNetCV,  # noqa: E402
                                  HuberRegressor, LinearRegression, RidgeCV)
from sklearn.pipeline import Pipeline                          # noqa: E402
from sklearn.preprocessing import StandardScaler               # noqa: E402

MIN_TRAIN = 6          # fewest observations we will fit anything on
MIN_FOLDS = 3          # fewest out-of-sample folds for a score to mean anything


# ---------------------------------------------------------------------------
# baselines — the bar every learned model has to clear
# ---------------------------------------------------------------------------
class SeasonalNaive:
    """Last year's same quarter, grown by the recent year-on-year rate."""

    name = "seasonal_naive"

    def __init__(self, season: int = 4):
        self.season = season
        self._y = None

    def fit(self, X, y):
        self._y = np.asarray(y, dtype=float)
        return self

    def predict_next(self) -> float:
        y, s = self._y, self.season
        if len(y) > s:
            base = y[-s]
            ratios = [y[i] / y[i - s] for i in range(s, len(y))
                      if y[i - s] not in (0,) and y[i] * y[i - s] > 0]
            if ratios:
                return float(base * np.median(ratios[-4:]))
            return float(base)
        return float(y[-1])


class DriftNaive:
    name = "drift"

    def fit(self, X, y):
        self._y = np.asarray(y, dtype=float)
        return self

    def predict_next(self) -> float:
        y = self._y
        if len(y) < 3:
            return float(y[-1])
        return float(y[-1] + np.median(np.diff(y[-5:])))


def _candidates(n_rows: int, n_feats: int) -> list[tuple[str, object]]:
    """Model list, gated on how much data actually exists."""
    out: list[tuple[str, object]] = [
        ("ridge", Pipeline([("s", StandardScaler()),
                            ("m", RidgeCV(alphas=np.logspace(-3, 3, 25)))])),
        ("bayes_ridge", Pipeline([("s", StandardScaler()), ("m", BayesianRidge())])),
    ]
    if n_rows >= 10:
        out.append(("elasticnet", Pipeline([("s", StandardScaler()),
                                            ("m", ElasticNetCV(cv=3, max_iter=5000))])))
        out.append(("huber", Pipeline([("s", StandardScaler()),
                                       ("m", HuberRegressor(max_iter=500))])))
    if n_rows >= 12:
        out.append(("random_forest", RandomForestRegressor(
            n_estimators=300, max_depth=3, min_samples_leaf=2, random_state=0)))
        out.append(("extra_trees", ExtraTreesRegressor(
            n_estimators=300, max_depth=3, min_samples_leaf=2, random_state=0)))
    if n_rows >= 16:
        out.append(("grad_boost", GradientBoostingRegressor(
            n_estimators=200, max_depth=2, learning_rate=.05,
            subsample=.9, random_state=0)))
    if n_rows >= 8 and n_feats <= max(2, n_rows // 4):
        out.append(("ols", Pipeline([("s", StandardScaler()),
                                     ("m", LinearRegression())])))
    out.append(("mean", DummyRegressor(strategy="mean")))
    return out


# ---------------------------------------------------------------------------
@dataclass
class FeatureReport:
    selected: list[str] = field(default_factory=list)
    considered: int = 0
    reason: str = ""


@dataclass
class ModelScore:
    name: str
    mape: float
    mae: float
    folds: int

    def __repr__(self) -> str:
        return f"{self.name}: MAPE {self.mape:.2%} over {self.folds} folds"


@dataclass
class Fit:
    target: str
    best: str
    scores: list[ModelScore]
    features: FeatureReport
    prediction: float | None
    n_rows: int
    season: int
    baseline_mape: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "target": self.target, "best_model": self.best,
            "prediction": None if self.prediction is None else round(self.prediction, 4),
            "n_rows": self.n_rows, "season": self.season,
            "features": self.features.selected,
            "features_considered": self.features.considered,
            "baseline_mape": None if self.baseline_mape is None else round(self.baseline_mape, 4),
            "scores": [{"model": s.name, "mape": round(s.mape, 4), "mae": round(s.mae, 4),
                        "folds": s.folds} for s in self.scores],
            "note": self.note,
        }


# ---------------------------------------------------------------------------
def select_features(X: np.ndarray, y: np.ndarray, names: list[str],
                    max_features: int) -> FeatureReport:
    """Rank lagged features by |Spearman| against the target, then decorrelate.

    Rank correlation rather than Pearson because these series are trending and
    heavy-tailed. The cap is tied to the number of observations: with 20 rows,
    admitting 15 features is fitting noise with extra steps.
    """
    n, m = X.shape
    if m == 0:
        return FeatureReport([], 0, "no candidate features")
    from scipy.stats import spearmanr

    scored = []
    for j in range(m):
        col = X[:, j]
        if np.all(np.isnan(col)) or np.nanstd(col) == 0:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho, _ = spearmanr(col, y, nan_policy="omit")
        if rho is not None and np.isfinite(rho):
            scored.append((abs(float(rho)), j))
    scored.sort(reverse=True)

    chosen: list[int] = []
    for _, j in scored:
        if len(chosen) >= max_features:
            break
        # drop a feature that duplicates one already taken
        dup = False
        for k in chosen:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r, _ = spearmanr(X[:, j], X[:, k], nan_policy="omit")
            if r is not None and np.isfinite(r) and abs(r) > 0.92:
                dup = True
                break
        if not dup:
            chosen.append(j)
    return FeatureReport([names[j] for j in chosen], len(scored),
                         f"capped at {max_features} for {n} observations")


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = np.where(np.abs(actual) < 1e-9, np.nan, np.abs(actual))
    return float(np.nanmedian(np.abs(actual - pred) / denom))


def walk_forward(series: list[float], feats: np.ndarray | None,
                 season: int) -> tuple[list[ModelScore], str]:
    """Expanding-window backtest. Every prediction is genuinely out of sample."""
    y = np.asarray(series, dtype=float)
    n = len(y)
    if n < MIN_TRAIN + MIN_FOLDS:
        return [], f"only {n} observations; need {MIN_TRAIN + MIN_FOLDS}"

    results: dict[str, list[tuple[float, float]]] = {}

    def record(name: str, actual: float, pred: float) -> None:
        if np.isfinite(pred):
            results.setdefault(name, []).append((actual, pred))

    for cut in range(MIN_TRAIN, n):
        y_tr, y_te = y[:cut], y[cut]

        for cls in (SeasonalNaive, DriftNaive):
            mdl = cls(season) if cls is SeasonalNaive else cls()
            mdl.fit(None, y_tr)
            record(mdl.name, y_te, mdl.predict_next())

        if feats is None or feats.shape[1] == 0:
            continue
        X_tr, X_te = feats[:cut], feats[cut:cut + 1]
        if np.isnan(X_tr).any() or np.isnan(X_te).any():
            continue
        for name, model in _candidates(cut, feats.shape[1]):
            try:
                model.fit(X_tr, y_tr)
                record(name, y_te, float(model.predict(X_te)[0]))
            except Exception:
                continue

    scores = []
    for name, pairs in results.items():
        if len(pairs) < MIN_FOLDS:
            continue
        a = np.array([p[0] for p in pairs])
        p = np.array([p[1] for p in pairs])
        scores.append(ModelScore(name, _mape(a, p),
                                 float(np.nanmean(np.abs(a - p))), len(pairs)))
    scores.sort(key=lambda s: (s.mape, s.mae))
    return scores, ""


def fit_target(panel_rows: list[dict], target: str, season: int = 4,
               feature_keys: list[str] | None = None) -> Fit:
    """Backtest every candidate for one target and return the winner."""
    rows = [r for r in panel_rows if r.get(target) not in ("", None)]
    rows.sort(key=lambda r: (r["fiscal_year"], r["fiscal_quarter"] or 5))
    y = [float(r[target]) for r in rows]
    n = len(y)
    if n < MIN_TRAIN + MIN_FOLDS:
        return Fit(target, "insufficient_history", [], FeatureReport(), None, n, season,
                   note=f"{n} observations; need {MIN_TRAIN + MIN_FOLDS}")

    # --- candidate features, LAGGED so nothing from the printed quarter leaks
    keys = feature_keys or sorted(
        {k for r in rows for k, v in r.items()
         if k not in ("fiscal_period", "fiscal_year", "fiscal_quarter", "period_end")
         and v not in ("", None)}
    )
    raw, names = [], []
    for k in keys:
        col = []
        ok = True
        for r in rows:
            v = r.get(k, "")
            try:
                col.append(float(v))
            except (TypeError, ValueError):
                ok = False
                break
        if ok and len(col) == n and np.std(col) > 0:
            raw.append(col)
            names.append(k)
    feats = None
    report = FeatureReport([], 0, "no usable numeric features")
    if raw:
        M = np.array(raw, dtype=float).T                 # n x m, aligned to y
        lagged = M[:-1]                                  # predict y[t] from t-1
        y_lag = np.asarray(y[1:], dtype=float)
        max_f = max(1, min(4, len(y_lag) // 5))
        report = select_features(lagged, y_lag, names, max_f)
        if report.selected:
            idx = [names.index(s) for s in report.selected]
            # Align by DROPPING the first period rather than padding it with
            # NaN: walk_forward refuses any fold containing NaN, so a padded
            # row silently disqualified every learned model from every fold.
            feats = M[:-1][:, idx]
            y = y[1:]
            rows = rows[1:]
            n = len(y)

    scores, why = walk_forward(y, feats, season)
    if not scores:
        sn = SeasonalNaive(season).fit(None, np.array(y))
        return Fit(target, "seasonal_naive", [], report, sn.predict_next(), n, season,
                   note=why or "no model scored on enough folds")

    best = scores[0]
    base = next((s.mape for s in scores if s.name == "seasonal_naive"), None)

    # refit the winner on everything and predict one step ahead
    pred = None
    if best.name in ("seasonal_naive", "drift"):
        mdl = SeasonalNaive(season) if best.name == "seasonal_naive" else DriftNaive()
        pred = mdl.fit(None, np.array(y)).predict_next()
    elif feats is not None:
        try:
            X = feats[1:]
            model = dict(_candidates(n, feats.shape[1]))[best.name]
            model.fit(X, np.array(y[1:]))
            pred = float(model.predict(feats[-1:])[0])
        except Exception:
            pred = SeasonalNaive(season).fit(None, np.array(y)).predict_next()

    note = ""
    if base is not None and best.name != "seasonal_naive":
        note = (f"beat the seasonal baseline by "
                f"{(base - best.mape) / base:.0%} MAPE" if base > best.mape
                else "did not beat the baseline")
    return Fit(target, best.name, scores[:6], report, pred, n, season, base, note)
