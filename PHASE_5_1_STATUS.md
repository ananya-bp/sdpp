# Phase 5 — Session 5.1 Status: Demand & TAT Forecasting (no checkpoint; 5.2 not started)
Data is SIMULATED (no real KLE Tech data). All numbers below come from `python -m ml.forecasting`
(saved in `ml/models/forecasting_metrics.json`).

**Model:** LightGBM (one regressor per target). Demand: Poisson objective (small non-negative counts).
TAT: L1 objective (conditional median; right-skewed, matches the MAE baseline). Not chosen: SARIMA/Prophet
(4 doc-type series + queue/lag features already engineered; they'd ignore queue backlog), LSTM/GRU
(only ~4.3k / 12.6k rows; no justification), XGBoost (equivalent to LightGBM, no benefit).
**Split:** existing chronological `split` column; train fits, valid does early stopping + a 4-point grid
per target, test evaluated once after selection. NaNs (`lag_364`) left as-is (LightGBM handles natively).
**Leakage control:** demand excludes same-day `mean_tat_hours/n_tat_observed/tat_censored`; TAT uses
submission-time features only; lag/rolling features verified causal (match shifted series, not incl. today).

| | Baseline (test MAE) | Model valid MAE | Model TEST MAE | TEST RMSE |
|---|---|---|---|---|
| Demand (per doc-type/day) | 2.547 (per-type train mean), 2.554 (lag-7) | 1.534 | **1.816** | 2.425 |
| TAT (hours) | 34.79 (train median) | 14.562 | **19.89** | 34.146 |
Sizes — demand 2812/724/736, TAT 8139/2019/2428 (train/valid/test; match Phase 4).
Ranges — demand test actual 0–22, predicted 0.74–11.29; TAT test actual 0.54–173.7h, predicted 0.94–87.9h.

**Artifact:** `ml/models/forecasting_lgbm.joblib` (~290 KB). **Code:** `ml/forecasting.py`
(`train()`, `predict_demand()`, `predict_tat()`), `backend/app/api/routes/forecast.py`
(`GET /api/forecast/demand`, `POST /api/forecast/tat`, admin-only), registered in `backend/app/main.py`.
**Tests:** `ml/tests/test_forecasting.py` (7), `backend/tests/test_forecast.py` (5, no DB needed).

**Known limitations:** test period is a distribution shift (test demand mean 4.53 vs 3.62 train; TAT median
~47h vs ~22h) so test error > valid error; trees can't extrapolate beyond training range (predictions cap
well below the largest actual spikes/delays). Demand is day-ahead only (needs history through the previous
day); `queue_open_at_day_start` is approximated by the last known value for a future day. Model is trained
on train only (not refit on train+valid). Backend DB-dependent tests were NOT run (no PostgreSQL here).
