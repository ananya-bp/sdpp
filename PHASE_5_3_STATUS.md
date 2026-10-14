# Phase 5 — Session 5.3 Status: Anomaly Detection
All data is SIMULATED (no real KLE Tech data). Every number comes from `python -m ml.anomaly`
(saved in `ml/models/anomaly_metrics.json`) or from the test commands listed. See `PHASE_5_STATUS.md` for the Phase 5 checkpoint.

## Goal
Flag unusual payment attempts for administrator review with an unsupervised Isolation Forest. Decision support only: nothing is
blocked, rejected or status-changed. The `label_*` columns are used for evaluation and one threshold choice only, never as inputs.

## Dataset
`ml/data/processed/anomaly_transactions.csv` (unchanged; checksum verified against `dataset_summary.json`). 14,887 rows, 0 missing.
**Grain: one row per payment attempt** (`transaction_id`). Chronological split (existing column, not reshuffled):
train 9,542 (232 anomalous, 2.4%) / valid 2,378 (80, 3.4%) / test 2,967 (74, 2.5%). Anomaly types: AMOUNT_MISMATCH, DUPLICATE_REQUEST,
FREQUENCY_BURST, RAPID_RETRIES (test: 23 / 8 / 19 / 24 rows). Benign look-alikes (normal retries) exist by design.

## Decision on the RAPID_RETRIES first-attempt issue (guide open decision)
**Accepted as a known miss; grain NOT changed.** ~1 in 6 RAPID_RETRIES rows is a burst's first attempt (data: 25 of 150 have
`attempt_index=1`); at that moment the burst has not happened, so its row is identical to a normal first attempt. A lookahead feature
would use information that does not exist when the payment occurs, and a lookback-only feature cannot help the first attempt either.
So `prepare.py` and the dataset were left untouched. Measured result: **first attempts caught 0 of 4 (test), 0 of 5 (valid)**;
later attempts caught 12 of 20 (test), 16 of 26 (valid). The model does not detect first attempts and we do not claim it does.

## Features
Used (12): `amount_deviation` = |amount_ratio − 1| (transform chosen on validation: AUC 0.9385→0.9470), `attempt_index`,
`failed_attempts_before`, `seconds_since_prev_attempt`, `student_txns_prior_24h`, `student_other_apps_24h`, `student_other_apps_7d`,
`same_doc_other_apps_7d`, `same_doc_other_paid_apps_7d`, and one-hot `payment_status` (this attempt's own outcome; legitimate).
Excluded: `label_is_anomaly`, `label_anomaly_type` (evaluation only); ids; `transacted_at`, `split`; `document_type`, `amount`,
`expected_amount` (redundant with the ratio); `hour`, `dow`, `minutes_since_submission` (no validation gain).
Trees are scale-invariant, so no scaling.

## Leakage checks
Tests assert: no `label_*`/"anomaly" feature; every CSV column is either a feature source or explicitly excluded; **scrambling all
labels gives a bit-identical fitted model** (proves labels never reach `fit`); the test split is scored once after all decisions.

## Model, parameters, threshold
`IsolationForest(n_estimators=200, max_samples=1024, random_state=42)`, fit on train features only (train contains its ~2.4% anomalies,
as a real unlabeled stream would). Small validation-only choices: 3 feature sets × 2 `max_samples` (6 fits), then the transform above.
Score = −`score_samples` (higher = more anomalous). **Threshold 0.670369 = the top 1.5% of TRAIN scores**; the 1.5% was picked as the best
validation F1 among 11 candidate percentiles (the only place labels influence a decision; validation labels, not test). Phase 4's
prevalence (~2.5%) was known but not used to set it directly.

## Rule layer (added after a finding; not part of the Isolation Forest)
Diagnosis: AMOUNT_MISMATCH rows differ from normal in exactly 1 of 12 features; Isolation Forest chooses split features at random, so
that single deviation is diluted (median mismatch score 0.506 vs normal 98th percentile 0.612). **IF-only recall on AMOUNT_MISMATCH is 0%
on every split** (0/23 test, 0/15 valid). Even `|ratio−1|` did not fix it. So a transparent deterministic rule was added: flag when
|amount/fee − 1| > 0.005 (the fee schedule is known from Phase 3). Reported separately so the ML model is not credited for it.
`is_anomaly = model_flagged OR rule_flags`.

## Metrics (real)
| Split | System | Flagged | TP/FP/FN | Precision | Recall | F1 | ROC-AUC | Avg-prec |
|---|---|---|---|---|---|---|---|---|
| valid | IF only | 46 | 39/7/41 | 0.848 | 0.488 | 0.619 | 0.947 | 0.669 |
| valid | IF + rule | 61 | 54/7/26 | 0.885 | 0.675 | 0.766 | 0.947 | 0.669 |
| **test** | IF only | 59 | 27/32/47 | 0.458 | 0.365 | 0.406 | **0.946** | 0.471 |
| **test** | IF + rule | 82 | 50/32/24 | **0.610** | **0.676** | **0.641** | 0.946 | 0.471 |
(test confusion, IF+rule: TP 50, FP 32, FN 24, TN 2861; overall detection rate = recall 67.6%; flag rate 2.8%.) ROC-AUC/avg-precision
measure the Isolation Forest score alone. Phase 4 best single-feature AUCs (for scale): 1.0 / 0.975 / 0.932 / 0.911.

## By anomaly type (test; counts are small, so read recall as ±large)
| Type | Injected | IF-only detected | IF+rule detected | Recall (IF+rule) | valid recall |
|---|---|---|---|---|---|
| AMOUNT_MISMATCH | 23 | 0 | 23 | 1.00 (rule) | 15/15 |
| FREQUENCY_BURST | 19 | 14 | 14 | 0.74 | 19/25 |
| RAPID_RETRIES | 24 | 12 | 12 | 0.50 (later attempts 12/20 = 0.60; **first attempts 0/4**) | 16/31 |
| DUPLICATE_REQUEST | 8 | 1 | 1 | 0.125 | 4/9 |
Flagged test rows by true type: NONE 32, AMOUNT_MISMATCH 23, FREQUENCY_BURST 14, RAPID_RETRIES 12, DUPLICATE_REQUEST 1.
False-positive rate on normal rows: 1.1% overall (test), **4.2% on benign look-alike retries** (attempt_index>1) vs 0.9% on first attempts.
Verified through the real prediction function on all 2,967 test rows: per-type counts identical to the metrics file.

## Limitations
- DUPLICATE_REQUEST is mostly missed: it needs cross-application comparison the row features only partly encode.
- Test false positives (32) are far above validation (7): the threshold was tuned on a very clean validation split, so validation
  precision (0.885) was optimistic; expect ~0.6 precision at the same threshold.
- RAPID_RETRIES first attempts are undetectable by design (above). Type-level results rest on 8–24 test rows each.
- Trained on train only; threshold in score units belongs to this model/data.

## Saved model / prediction / API
`ml/models/anomaly_isolation_forest.joblib` (~650 KB; model + feature list + threshold + fee schedule), `ml/models/anomaly_metrics.json`.
`predict_anomaly(*, document_type, amount, payment_status, attempt_index=1, failed_attempts_before=0,
seconds_since_prev_attempt=86400.0, student_txns_prior_24h=0, student_other_apps_24h=0, student_other_apps_7d=0,
same_doc_other_apps_7d=0, same_doc_other_paid_apps_7d=0) -> {anomaly_score, threshold, model_flagged, rule_flags, is_anomaly, label}`.
It never returns an anomaly type. Real outputs: normal successful TRANSCRIPT ₹200 → score 0.3143 NORMAL; 4th failed attempt 20 s after
the previous → 0.6833 ANOMALOUS (model_flagged); ₹750 paid for a DUPLICATE_GRADE_CARD → ANOMALOUS via `AMOUNT_MISMATCH` rule.
API: `POST /api/anomaly/score` (`backend/app/api/routes/anomaly.py`, via `services/ml_services.py`), admin-only.

## Tests run
ML suite **36 passed** (26 earlier + 10 new in `ml/tests/test_anomaly.py`). Backend **97 passed, 0 failed** on real PostgreSQL 16
(includes 17 ML/API tests: forecast 5, risk 5, anomaly 6, `test_ml_services.py` 1 — all three models in one process, interleaved,
identical results). Also verified over real HTTP with real JWT logins (uvicorn + DB): all four ML endpoints return 200 for an admin,
401 without a token, 403 for a student; `/api/health`, `/auth/login`, `/auth/me` unaffected.

## Not implemented / not tested
Frontend (Phase 6); no UI was run or changed. DB wiring of history features (risk) and of live transaction features (anomaly).
No admin-registration endpoint exists: the admin used for the HTTP test was inserted directly into the DB.
