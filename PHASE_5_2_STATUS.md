# Phase 5 — Session 5.2 Status: Eligibility Risk Scoring (no Phase 5 checkpoint yet; 5.3 not started)
All data is SIMULATED (no real KLE Tech data). Every number below was produced by `python -m ml.risk_scoring`
(saved in `ml/models/risk_scoring_metrics.json`) or by the test commands listed.

## Goal
Logistic Regression that outputs a 0–1 probability that an already-eligible application will need **manual review**
(guide §1.4). It is **not** an eligibility decision; rule-based `services/eligibility.py` is untouched and still alone
decides ELIGIBLE / NOT_ELIGIBLE. The administrator always decides.

## Inspected
Guide §1.4/§1.5/§1.8/Session 5.2, `PHASE_5_1_STATUS.md`, `docs/DATA_DICTIONARY.md` §6c, `ml/prepare.py` (risk builder),
`ml/features.py` (causal history features), `ml/validate_datasets.py`, `backend/app/db/seed_students.py`,
`backend/app/services/eligibility.py`, `backend/app/main.py`. Before coding: 15 ML tests + 5 forecast API tests passed;
5.1 model still gave the same numbers.
Note: the risk dataset is at `ml/data/processed/risk_scoring.csv` (not `ml/data/risk_scoring.csv`).

## Dataset
13,104 rows, no missing values, no duplicate application_id. Chronological split (existing `split` column, not reshuffled):
train 8,459 (2023-09-01…2025-08-31, 17.9% positive) / valid 2,097 (26.8%) / test 2,548 (2026-03-01…2026-08-26, 29.1%).
Prevalence drifts upward over time (a property of the simulated data) — see Limitations.

## Features (13) / excluded
Used: `document_type`, `department` (one-hot, first level dropped: DUPLICATE_GRADE_CARD, CIV); count features
`backlog_count`, `past_fee_delays_12m`, `prior_apps_count`, `prior_review_count_lagged` (log1p then standardised);
standardised `semester`, `is_alumni`, `cgpa`, `num_documents`, `ocr_failed`, `ocr_cgpa_found`, `ocr_cgpa_mismatch`.
Excluded: `label_needs_manual_review` (target), `application_id`, `student_id` (identifiers), `submitted_at` (timestamp, used
only for the split), `split`. Not in the CSV by design: `fee_status` (constant once eligible), `sim_true_review_probability`,
`status`, `decided_at`, TAT, payment retries. A test asserts every CSV column is either a feature or explicitly excluded.

## Leakage checks
(1) column-level: no label/oracle/sim_/status columns among features (test). (2) Phase 4 already independently recomputes
`prior_apps_count` / `prior_review_count_lagged` to prove they only use history before submission. (3) Chronological split,
no shuffling; all choices made on validation; test scored once after they were fixed. (4) **Test AUC 0.8196 < test oracle 0.8518**
(guide's leak alarm: above the oracle would mean a bug) — asserted in a test. 963 students appear in both train and test,
which is expected (same students re-apply over time; their history features are causal).

## Model / preprocessing / decisions
Logistic Regression only (no RF/XGBoost: signal is near the oracle ceiling, so nothing to justify a complex model).
Validation-only decisions (8 fits, no CV): log1p on count features (yes) × C ∈ {0.01,0.1,1,10} → log1p, C=1.0
(valid AUC 0.809 vs 0.805 without log1p; differences between all 8 settings are ≤0.006 — not tuning-sensitive).
Trained on train only (not refit on train+valid). Review-flag threshold **0.28** = F1-optimal on validation.

## Metrics (real)
| Split | Threshold | Acc | Prec | Recall | F1 | ROC-AUC | Brier |
|---|---|---|---|---|---|---|---|
| train | 0.5 | 0.847 | 0.661 | 0.297 | 0.410 | 0.7969 | 0.114 |
| valid | 0.5 | 0.797 | 0.673 | 0.469 | 0.553 | 0.8090 | 0.146 |
| valid | 0.28 | 0.749 | 0.523 | 0.713 | 0.603 | 0.8090 | 0.146 |
| **test** | 0.5 | 0.789 | 0.693 | 0.493 | 0.576 | **0.8196** | 0.148 |
| **test** | 0.28 | 0.753 | 0.558 | 0.732 | 0.633 | 0.8196 | 0.148 |

Reference points: oracle AUC (best possible) train/valid/test = 0.8345 / 0.8383 / **0.8518**; Phase 4 throwaway LR test
AUC 0.8152; majority-class ("never needs review") test accuracy 0.7088. Test AUC is in the low 0.80s, below the ceiling,
slightly above the throwaway baseline. Mean predicted probability vs actual rate: test 0.287 vs 0.291 (well calibrated
overall). Prediction range on test 0.016–0.988. Accuracy at 0.5 is only modestly above majority-class, which is why
precision/recall/F1/AUC matter here.

## Coefficients (standardised features; odds ratio = per +1 SD, or vs the dropped category)
Association in this simulated data, **not causation**; the simulator's own latent weights are invented.
| Feature | Coef | Odds ratio | Direction |
|---|---|---|---|
| prior_review_count_lagged | +0.621 | 1.86 | raises |
| past_fee_delays_12m | +0.422 | 1.53 | raises |
| backlog_count | +0.321 | 1.38 | raises |
| prior_apps_count | +0.306 | 1.36 | raises |
| is_alumni | +0.290 | 1.34 | raises |
| ocr_cgpa_mismatch | +0.247 | 1.28 | raises |
| department_EEE | −0.236 | 0.79 | lowers (vs CIV) |
| ocr_failed | +0.193 | 1.21 | raises |
| document_type_MIGRATION_CERTIFICATE | +0.188 | 1.21 | raises (vs DUPLICATE_GRADE_CARD) |
| document_type_TRANSCRIPT | −0.154 | 0.86 | lowers |
| cgpa | −0.127 | 0.88 | lowers |
Remaining (|coef| < 0.06): MEC, PROVISIONAL cert, semester, ocr_cgpa_found, CSE, ECE, num_documents. Full list in the metrics JSON.
Note `ocr_failed` and `ocr_cgpa_found` are correlated by construction, so read them jointly.

## Artifact & prediction function
`ml/models/risk_scoring_logistic.joblib` (~2.5 KB; sklearn Pipeline + feature list + threshold). Code: `ml/risk_scoring.py`.
`predict_risk(*, document_type, department, semester, cgpa, backlog_count, is_alumni=False, past_fee_delays_12m=0,
prior_apps_count=0, prior_review_count_lagged=0, num_documents=1, ocr_failed=False, ocr_detected_cgpa=None) -> float` in [0,1]
(department accepts a code or the full name; invalid input raises ValueError). `review_flag_threshold()` → 0.28.
Real fresh-process output: low-risk profile (CGPA 9.3, 0 backlogs) 0.0162; high-risk profile (CGPA 5.9, 4 backlogs, 3 fee
delays, 5 prior apps / 2 prior reviews, OCR failed) 0.9644.

## API
`POST /api/risk/score` (`backend/app/api/routes/risk.py`, registered in `main.py`), admin-only (same `require_admin` as 5.1;
401 without login, 403 for students). Validated body → `{manual_review_probability, flag_threshold, flagged_for_review, note}`;
never returns ELIGIBLE/NOT_ELIGIBLE. It scores supplied features; it does not read the DB and no schema changed.

## 12 dev-seed students (`python -m ml.score_dev_seed`, reads seed_students.py without a DB)
The seed table only holds dept/semester/CGPA/backlogs/fee status. **Assumptions (not data):** TRANSCRIPT, non-alumni, 1
document, OCR succeeded and matched, prior_apps=0 and prior_reviews=0 (no history), past_fee_delays = 0 if CLEAR else 1
(a lower bound). DUE-fee students would be NOT_ELIGIBLE under the rules and never reach scoring in production.
| USN | CGPA | Backlogs | Fee | Risk |
|---|---|---|---|---|
| SIM23MEC002 | 9.10 | 0 | CLEAR | 0.0177 |
| SIM23CSE003 | 9.30 | 0 | CLEAR | 0.0181 |
| SIM23EEE002 | 7.80 | 0 | CLEAR | 0.0194 |
| SIM23CSE001 | 8.90 | 0 | CLEAR | 0.0199 |
| SIM23ECE001 | 8.05 | 0 | CLEAR | 0.0216 |
| SIM23CIV001 | 7.05 | 0 | CLEAR | 0.0245 |
| SIM23EEE001 | 8.60 | 0 | DUE | 0.0284 |
| SIM23MEC001 | 6.85 | 1 | CLEAR | 0.0627 |
| SIM23CSE002 | 7.45 | 1 | CLEAR | 0.0646 |
| SIM23ECE002 | 7.20 | 2 | CLEAR | 0.1062 |
| SIM23CSE004 | 6.10 | 3 | DUE | 0.2930 (≥0.28 flag) |
| SIM23CIV002 | 5.90 | 4 | DUE | 0.3722 (≥0.28 flag) |
Ordering is sensible (no backlogs lowest; 3–4 backlogs highest). Absolute values are low because these students have no
history, and history features are the strongest signals.

## Tests actually run (env below)
- `python -m pytest ml -q` → **26 passed** (15 from Phase 4/5.1 + 11 new in `ml/tests/test_risk_scoring.py`: artifact, features/
  leakage, split sizes & chronology, test AUC < oracle, reproducible metrics, numeric 0–1 output, reload, fresh subprocess,
  risky>fine, input validation, dev-seed ordering).
- `cd backend && pytest tests/test_forecast.py tests/test_risk.py -q` → **10 passed** (5 forecast + 5 new risk: 401, 403, valid
  probability-only response, riskier>safer, 422 validation). Auth overridden with fake users, no DB.
- Full `backend` suite: **15 passed, 3 failed, 72 errors** — all 75 non-passing are `psycopg OperationalError: Connection
  refused` on 127.0.0.1:5432 (no PostgreSQL in this sandbox). **Not tested because: PostgreSQL unavailable.** Please run
  the full backend suite locally (`alembic upgrade head`, seed, `pytest`). I changed only `main.py` (one import + one router).
- Not tested: the endpoint behind real JWT login on a live DB; the frontend (nothing added there).

## Limitations / known issues
- Simulated data; label noise is by design (ceiling ~0.83–0.85); the drivers are the simulator's invented weights.
- Prevalence drift 18%→27%→29%: 0.5 is a poor cutoff (recall 0.49); 0.28 (valid-F1) gives recall 0.73/precision 0.56 on test.
  Threshold is tied to this dataset and should be revisited if real data ever replaces it.
- In the live app, `prior_apps_count`, `prior_review_count_lagged`, `past_fee_delays_12m` are not stored anywhere yet; the
  endpoint accepts them as inputs (default 0). Wiring them from the DB is a Phase 6 concern, not done.
- [Superseded in Session 5.3: all artifacts were retrained under the pinned scikit-learn 1.9.1; metrics identical.]
- Artifact trained with scikit-learn 1.8.0 (sandbox); `ml/requirements.txt` pins 1.9.1 from Phase 4. If the versions
  differ on your machine, re-run `python -m ml.risk_scoring` (seconds) rather than trusting the pickle.
- Trained on train only; not refit on train+valid.

## Run
`python -m ml.risk_scoring` (train + save + metrics) · `python -m ml.score_dev_seed` · `python -m pytest ml -q` ·
`cd backend && pytest tests/test_risk.py -q` (needs `DATABASE_URL`/`SECRET_KEY` env values to import settings; no DB connection).
Environment: Python 3.12, scikit-learn 1.8.0, pandas 3.0.2, numpy 2.4.4, joblib 1.5.3, FastAPI 0.141.1, pytest 9.1.1.

## Files
New: `ml/risk_scoring.py`, `ml/score_dev_seed.py`, `ml/tests/test_risk_scoring.py`, `ml/models/risk_scoring_logistic.joblib`,
`ml/models/risk_scoring_metrics.json`, `backend/app/api/routes/risk.py`, `backend/tests/test_risk.py`, `PHASE_5_2_STATUS.md`.
Modified: `backend/app/main.py` (route registered), `ml/requirements.txt` (comment only). Datasets and 5.1 code untouched.

## NOT implemented
Anomaly detection (5.3), Random Forest/SHAP, DB wiring of history features, frontend, `PHASE_5_COMPLETE` checkpoint, Phase 6.

## Next: Session 5.3 — Anomaly Detection (Isolation Forest on `anomaly_transactions.csv`; read DATA_DICTIONARY §6d, incl. the
documented "first attempt of a retry burst" limitation, first).
