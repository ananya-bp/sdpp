# Phase 5 — Completion Status (AI/ML: Forecasting, Risk Scoring, Anomaly Detection)
Project: AI-Enhanced University Document Issuance, Tracking and Administrative Analytics Portal (SDP 20ECSW401, Team 27).
Builds on Phase 4 (`PHASE_4_STATUS.md`). Details per session: `PHASE_5_1_STATUS.md`, `PHASE_5_2_STATUS.md`, `PHASE_5_3_STATUS.md`.
All models are trained on SIMULATED data; nothing here is real KLE Tech data.

## 1. Phase Goal
Train, evaluate, save and expose the three ML components as admin decision support (never automated decisions): demand & TAT
forecasting, eligibility risk scoring (probability of manual review; rule-based eligibility untouched), payment anomaly detection.

## 2. What Was Completed
| Component | Model | Key TEST result vs baseline |
|---|---|---|
| 5.1 Demand forecast (per doc-type/day) | LightGBM (Poisson) | MAE 1.816 / RMSE 2.425 vs 2.547 (train mean), 2.554 (lag-7) |
| 5.1 TAT forecast (hours) | LightGBM (L1) | MAE 19.89 / RMSE 34.146 vs 34.79 (train median) |
| 5.2 Manual-review risk | Logistic Regression | ROC-AUC 0.8196 (oracle 0.8518, Phase 4 throwaway 0.8152); F1 0.576 @0.5, 0.633 @0.28 |
| 5.3 Payment anomaly | Isolation Forest + amount rule | IF-only ROC-AUC 0.946, F1 0.406; IF+rule P 0.610 / R 0.676 / F1 0.641 |
Three saved artifacts, plain-Python prediction functions, four admin-only endpoints, one internal service layer for Phase 6.
Chronological splits from Phase 4 used everywhere; test scored once after all decisions; datasets unchanged (checksums verified).

## 3. Files Created (Phase 5)
`ml/forecasting.py`, `ml/risk_scoring.py`, `ml/score_dev_seed.py`, `ml/anomaly.py`; `ml/models/{forecasting_lgbm,risk_scoring_logistic,anomaly_isolation_forest}.joblib`
and `*_metrics.json`; `ml/tests/test_{forecasting,risk_scoring,anomaly}.py`; `backend/app/api/routes/{forecast,risk,anomaly}.py`;
`backend/app/services/ml_services.py`; `backend/tests/test_{forecast,risk,anomaly,ml_services}.py`; `PHASE_5_{1,2,3}_STATUS.md`, this file.

## 4. Files Modified
`backend/app/main.py` (3 routers registered), `backend/requirements.txt` (ML runtime pins), `ml/requirements.txt` (lightgbm, joblib),
`README.md` (Phase 5 section, structure). Phase 1–4 code, datasets and eligibility rules untouched.

## 5. Current Project Structure
`backend/` (FastAPI: app/{core,db,models,services,api/routes,schemas}, alembic, tests) · `frontend/` (Next.js, unchanged) ·
`ml/` (config, simulate, features, prepare, validate_datasets, make_datasets, forecasting, risk_scoring, anomaly, score_dev_seed,
models/, data/{raw,labels,processed,figures}, tests) · `docs/` (PROJECT_CONTEXT, DATA_DICTIONARY) · status files · README.

## 6. Database Changes
None in Phase 5 (last migration still `2d9f0673822c`, add ocr results). Models read saved artifacts, not the database.

## 7. APIs / Endpoints Added (all admin-only; 401 no token, 403 student)
`GET /api/forecast/demand` · `POST /api/forecast/tat` · `POST /api/risk/score` · `POST /api/anomaly/score`.
Internal (for Phase 6): `app/services/ml_services.py` → `forecast_demand`, `forecast_tat_hours`, `score_manual_review_risk`, `score_payment_anomaly`.

## 8. Features Currently Working (verified)
Everything from Phases 1–4 (backend suite) plus the three models, prediction functions and four endpoints, reloadable in fresh processes.

## 9. Testing Performed (actual results)
- Working tree: ML **36 passed**; full backend **97 passed, 0 failed** on real PostgreSQL 16 (installed in the sandbox this session).
- **Clean-room check (guide §2):** unzip checkpoint → new venv → `pip install -r backend/requirements.txt -r ml/requirements.txt` (pinned
  versions) → brand-new database → `alembic upgrade head` → seeds → ML **36 passed**, backend **97 passed, 0 failed**.
  It found one real bug: artifacts pickled under scikit-learn 1.8.0 warned under the pinned 1.9.1 (and backend requirements lacked the
  ML libraries). Fixed: pins added to `backend/requirements.txt`, all three models retrained under the pinned versions; every reported
  metric reproduced identically; suites re-run with `InconsistentVersionWarning` as an error: pass.
- Real HTTP with real JWT logins against a running uvicorn + DB: 4 ML endpoints 200/401/403 as expected; health/auth unaffected.
- All three models called together in one process, interleaved: identical results (no interference).
- Dataset validation: `validate()` on the shipped files → 0 hard failures; 9/9 file checksums match `dataset_summary.json`.
- **Not tested:** the frontend (not changed, not run; no Node build in this sandbox check); OCR-heavy manual flows beyond the automated tests.

## 10. Known Issues / Limitations
Simulated data and hand-set generator weights. Test distribution shift for demand/TAT (larger error than validation). Risk: 0.5 is a poor
cutoff (drifting prevalence); history features not stored in the DB. Anomaly: DUPLICATE_REQUEST recall 1/8; RAPID_RETRIES first attempts
undetectable (0/4); amount mismatches are caught by a rule, not by the ML model; test FPs (32) ≫ validation FPs (7).
Backend tests register seeded student `SIM23CSE001`, so run them on a database where no login exists yet for that USN (otherwise 12 tests fail with 409 "USN already has an account" — observed after a manual HTTP test used that USN; existing test design, unchanged).
No admin-registration endpoint (admins must be inserted in the DB). ~1,200 third-party deprecation warnings in the backend test run (harmless).

## 11. Important Decisions
LightGBM for forecasting (not SARIMA/Prophet/LSTM); Logistic Regression only for risk; Isolation Forest for anomalies with a documented
rule layer for amount mismatch; first-attempt limitation accepted, grain not changed; thresholds chosen on validation only;
models trained on train split only; ML libraries added to the backend requirements; shared `require_admin` from the forecast route.

## 12. Environment / Setup
Python 3.12, PostgreSQL 16, pinned: numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1, lightgbm 4.7.0, joblib 1.5.3 (see requirements files).
If your library versions differ from the pins, retrain: `python -m ml.forecasting && python -m ml.risk_scoring && python -m ml.anomaly`.
Secrets: `.env` is NOT included; copy `backend/.env.example` and set `DATABASE_URL` and `SECRET_KEY`.

## 13. How to Run
`cd backend && pip install -r requirements.txt && alembic upgrade head && python -m app.db.seed && python -m app.db.seed_students && uvicorn app.main:app`
· ML tests: `python -m pytest ml -q` (project root) · backend tests: `cd backend && pytest -q` (needs the configured PostgreSQL)
· retrain: the three `python -m ml.<name>` commands above · frontend: unchanged (see README).

## 14. What Is NOT Implemented Yet
Admin dashboard and any UI for the ML outputs (Phase 6); wiring model inputs from live DB data; admin-registration flow; final
integration/deployment work.

## 15. Next Phase
Phase 6 — Admin Dashboard (call `ml_services.py`; needs an admin login flow and DB-derived inputs). Start only on your go-ahead.

## 16. Handoff Instructions
Attach `PHASE_5_COMPLETE.zip` + `PHASE_5_STATUS.md` + `SDP_BUILD_GUIDE.md`, then say "Start Session 6.1".
