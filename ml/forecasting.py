"""Phase 5.1 - Demand & TAT forecasting (LightGBM, one model per target).

Train:    python -m ml.forecasting            (from project root)
Predict:  from ml.forecasting import predict_demand, predict_tat

Data is SIMULATED (see docs/DATA_DICTIONARY.md). Uses the existing chronological `split` column:
train -> fit, valid -> early stopping + model selection, test -> evaluated once at the end.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "forecasting_lgbm.joblib"
METRICS_PATH = MODEL_DIR / "forecasting_metrics.json"
SUMMARY = ROOT / "data" / "dataset_summary.json"

# Demand: same-day outcomes (mean_tat_hours, n_tat_observed, tat_censored) are NOT features -> leakage.
DEMAND_TARGET = "applications_submitted"
DEMAND_CAT = ["document_type", "academic_phase"]
DEMAND_NUM = ["dow", "month", "is_holiday", "is_working_day", "week_of_year", "days_since_start",
              "queue_open_at_day_start", "lag_1", "lag_7", "lag_14", "lag_364",
              "roll_mean_7", "roll_mean_28"]
DEMAND_FEATURES = DEMAND_CAT + DEMAND_NUM

# TAT: submission-time features only (ids / raw timestamp / split excluded).
TAT_TARGET = "tat_hours"
TAT_CAT = ["document_type", "submit_academic_phase"]
TAT_NUM = ["num_documents", "is_alumni", "submit_hour", "submit_dow", "submit_month",
           "submit_is_working_day", "submit_is_holiday", "queue_open_at_submission",
           "apps_prev_24h", "apps_prev_7d", "doc_apps_prev_7d"]
TAT_FEATURES = TAT_CAT + TAT_NUM


def _mae(y, p): return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))
def _rmse(y, p): return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


def _prep(df: pd.DataFrame, cat: list[str], cats: dict | None = None):
    X = df.copy()
    cats = cats or {c: sorted(df[c].unique()) for c in cat}
    for c in cat:
        X[c] = pd.Categorical(X[c], categories=cats[c])
    return X, cats


def _metrics(y, p):
    return {"n": int(len(y)), "mae": round(_mae(y, p), 3), "rmse": round(_rmse(y, p), 3),
            "target_min": round(float(np.min(y)), 2), "target_max": round(float(np.max(y)), 2),
            "pred_min": round(float(np.min(p)), 2), "pred_max": round(float(np.max(p)), 2)}


def _fit(Xtr, ytr, Xva, yva, params, n_max=2000):
    m = lgb.LGBMRegressor(n_estimators=n_max, verbose=-1, random_state=42, n_jobs=1, **params)
    m.fit(Xtr, ytr, eval_X=Xva, eval_y=yva, eval_metric="l1",
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return m


def train() -> dict:
    base = json.loads(SUMMARY.read_text())
    out: dict = {"baselines": {"demand": base["forecasting_sanity_baselines"],
                               "tat": base["tat_sanity_baseline"]}}
    artifact: dict = {}

    # ---------------- Demand ----------------
    d = pd.read_csv(DATA / "forecast_daily.csv", parse_dates=["date"]).sort_values(["date", "document_type"])
    s = {k: d[d.split == k] for k in ("train", "valid", "test")}
    Xtr, cats = _prep(s["train"][DEMAND_FEATURES], DEMAND_CAT)
    Xva, _ = _prep(s["valid"][DEMAND_FEATURES], DEMAND_CAT, cats)
    Xte, _ = _prep(s["test"][DEMAND_FEATURES], DEMAND_CAT, cats)
    ytr, yva, yte = (s[k][DEMAND_TARGET] for k in ("train", "valid", "test"))
    grid = [dict(objective="poisson", learning_rate=0.03, num_leaves=nl, min_child_samples=mc,
                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8)
            for nl in (7, 15) for mc in (20, 40)]
    cand = [(_mae(yva, (m := _fit(Xtr, ytr, Xva, yva, p)).predict(Xva)), p, m) for p in grid]
    v_mae, best_p, model = min(cand, key=lambda t: t[0])  # selection on VALID only
    out["demand"] = {"chosen_params": best_p, "best_iteration": int(model.best_iteration_),
                     "grid_valid_mae": [round(c[0], 3) for c in cand],
                     "train": _metrics(ytr, model.predict(Xtr)), "valid": _metrics(yva, model.predict(Xva))}
    pte = model.predict(Xte)  # test touched once, after selection
    out["demand"]["test"] = _metrics(yte, pte)
    out["demand"]["test_baselines_mae"] = {
        "train_mean": round(_mae(yte, np.full(len(yte), ytr.mean())), 3),
        "seasonal_naive_lag7": round(_mae(yte, s["test"]["lag_7"]), 3)}
    dt = s["test"].document_type.values
    out["demand"]["test_by_doc_type_mae"] = {
        k: round(_mae(yte.values[dt == k], pte[dt == k]), 3) for k in sorted(set(dt))}
    artifact["demand"] = {"model": model, "cats": cats}

    # ---------------- TAT ----------------
    t = pd.read_csv(DATA / "tat_applications.csv", parse_dates=["submitted_at"]).sort_values("submitted_at")
    s = {k: t[t.split == k] for k in ("train", "valid", "test")}
    Xtr, tcats = _prep(s["train"][TAT_FEATURES], TAT_CAT)
    Xva, _ = _prep(s["valid"][TAT_FEATURES], TAT_CAT, tcats)
    Xte, _ = _prep(s["test"][TAT_FEATURES], TAT_CAT, tcats)
    ytr, yva, yte = (s[k][TAT_TARGET] for k in ("train", "valid", "test"))
    # MAE-oriented objective (L1 = conditional median), matches the median baseline's metric
    grid = [dict(objective="regression_l1", learning_rate=0.03, num_leaves=nl, min_child_samples=mc,
                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8)
            for nl in (7, 15) for mc in (30, 60)]
    cand = [(_mae(yva, (m := _fit(Xtr, ytr, Xva, yva, p)).predict(Xva)), p, m) for p in grid]
    v_mae, best_p, model = min(cand, key=lambda t_: t_[0])
    out["tat"] = {"chosen_params": best_p, "best_iteration": int(model.best_iteration_),
                  "grid_valid_mae": [round(c[0], 3) for c in cand],
                  "train": _metrics(ytr, model.predict(Xtr)), "valid": _metrics(yva, model.predict(Xva))}
    pte = model.predict(Xte)
    out["tat"]["test"] = _metrics(yte, pte)
    out["tat"]["test_baseline_train_median_mae"] = round(_mae(yte, np.full(len(yte), ytr.median())), 3)
    out["tat"]["valid_baseline_train_median_mae"] = round(_mae(yva, np.full(len(yva), ytr.median())), 3)
    artifact["tat"] = {"model": model, "cats": tcats}

    MODEL_DIR.mkdir(exist_ok=True)
    artifact["features"] = {"demand": DEMAND_FEATURES, "tat": TAT_FEATURES}
    joblib.dump(artifact, MODEL_PATH, compress=3)
    METRICS_PATH.write_text(json.dumps(out, indent=2))
    return out


# ------------------------------- prediction -------------------------------
_ART = None


def _load():
    global _ART
    if _ART is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"{MODEL_PATH} not found - run `python -m ml.forecasting` first")
        _ART = joblib.load(MODEL_PATH)
    return _ART


def predict_tat(*, document_type: str, num_documents: int, is_alumni: int, submitted_at,
                queue_open_at_submission: int, apps_prev_24h: int, apps_prev_7d: int,
                doc_apps_prev_7d: int) -> float:
    """Expected turnaround (hours, median-style estimate) for one application, from submission-time info."""
    from .features import is_holiday, is_working_day
    from . import config as C
    ts = pd.Timestamp(submitted_at)
    row = pd.DataFrame([{
        "document_type": document_type, "submit_academic_phase": C.ACADEMIC_PHASE_BY_MONTH[ts.month],
        "num_documents": num_documents, "is_alumni": int(is_alumni), "submit_hour": ts.hour,
        "submit_dow": ts.dayofweek, "submit_month": ts.month,
        "submit_is_working_day": int(is_working_day(ts.date())), "submit_is_holiday": int(is_holiday(ts.date())),
        "queue_open_at_submission": queue_open_at_submission, "apps_prev_24h": apps_prev_24h,
        "apps_prev_7d": apps_prev_7d, "doc_apps_prev_7d": doc_apps_prev_7d}])
    a = _load()
    X, _ = _prep(row[TAT_FEATURES], TAT_CAT, a["tat"]["cats"])
    return float(max(a["tat"]["model"].predict(X)[0], 0.0))


def predict_demand(*, document_type: str, date, history: pd.DataFrame | None = None) -> float:
    """Expected number of applications for `document_type` on `date` (day-ahead).

    Uses forecast_daily.csv rows as history (or a DataFrame with the same columns). Lag/rolling features
    are read from the row for that date if present; otherwise the date must be the day right after the
    last history day (lags built from history only - nothing from `date` or later is used).
    """
    a = _load()
    day = pd.Timestamp(date).normalize()
    if history is None:
        history = pd.read_csv(DATA / "forecast_daily.csv", parse_dates=["date"])
    h = history[history.document_type == document_type].sort_values("date")
    hit = h[h.date == day]
    if len(hit):
        row = hit.iloc[[0]][DEMAND_FEATURES].copy()
    else:
        if day != h.date.max() + pd.Timedelta(days=1):
            raise ValueError("date must be inside history or exactly 1 day after its last day (day-ahead forecast)")
        from .features import is_holiday, is_working_day
        from . import config as C
        y = h.set_index("date").applications_submitted
        lag = lambda k: float(y.get(day - pd.Timedelta(days=k), np.nan))
        last = h.iloc[-1]
        row = pd.DataFrame([{
            "document_type": document_type, "academic_phase": C.ACADEMIC_PHASE_BY_MONTH[day.month],
            "dow": day.dayofweek, "month": day.month, "is_holiday": int(is_holiday(day.date())),
            "is_working_day": int(is_working_day(day.date())), "week_of_year": int(day.isocalendar().week),
            "days_since_start": int(last.days_since_start) + 1,
            "queue_open_at_day_start": int(last.queue_open_at_day_start),  # last known backlog (approximation)
            "lag_1": lag(1), "lag_7": lag(7), "lag_14": lag(14), "lag_364": lag(364),
            "roll_mean_7": float(y.loc[day - pd.Timedelta(days=7): day - pd.Timedelta(days=1)].mean()),
            "roll_mean_28": float(y.loc[day - pd.Timedelta(days=28): day - pd.Timedelta(days=1)].mean())}])
    X, _ = _prep(row[DEMAND_FEATURES], DEMAND_CAT, a["demand"]["cats"])
    return float(max(a["demand"]["model"].predict(X)[0], 0.0))


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
