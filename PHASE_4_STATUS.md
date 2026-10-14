# Phase 4 — Completion Status

Project: AI-Enhanced University Document Issuance, Tracking and Administrative Analytics Portal
(SDP, Course 20ECSW401, Team 27). Checkpoint date: 28 Sep 2026. Builds on Phase 3
(`PHASE_3_STATUS.md`). Phase 4 is a standalone data-generation subproject under `ml/` — it does not
modify `backend/` or `frontend/` in any way (verified: see section 9).

## 1. Phase Goal

Prepare clean, model-ready data for the three Phase 5 ML components: create a simulated
university application/student dataset, prepare transaction/payment data, clean it, handle missing
values, engineer relevant features, and produce three separate model-ready datasets (demand/TAT
forecasting, eligibility risk scoring, anomaly detection). No models are trained in this phase.

## 2. What Was Completed

* A simulator (`ml/simulate.py`) that plays the real Phase 1-3 workflow forward in simulated time
  for 3,000 SIMULATED students over 3 simulated years (Sep 2023-Aug 2026): seasonal application
  arrivals, OCR outcomes, the actual placeholder eligibility rule, the actual fee schedule, sandbox
  payment behaviour (including retries and abandonment), a finite-capacity FIFO admin queue that
  makes turnaround time emerge from load rather than being assigned, and a latent manual-review
  model. Anomalies (duplicate requests, rapid payment retries, frequency bursts, amount mismatches)
  are injected at known rates alongside benign look-alikes.
* Three model-ready datasets built from the raw tables (`ml/prepare.py`):
  `forecast_daily.csv`, `tat_applications.csv` (Phase 5A), `risk_scoring.csv` (Phase 5B),
  `anomaly_transactions.csv` (Phase 5C) — each with a chronological train/valid/test split and an
  explicit, documented missing-value policy.
- A validator (`ml/validate_datasets.py`) checking referential integrity, consistency with the
  real Phase 3 eligibility rule and fee schedule, no future-dated rows, no answer-key columns
  leaking into features, chronological splits, and several signal-sanity numbers (oracle AUC,
  a throwaway logistic-regression baseline, single-feature AUCs, anomaly separability).
* A full data dictionary (`docs/DATA_DICTIONARY.md`) documenting every file, column, assumption,
  and known limitation.
* A pytest suite (`ml/tests/test_pipeline.py`) proving determinism (same seed -> byte-identical
  files) and running the validator on every test run.
* Three sanity-check plots (`ml/make_figures.py`).
* **Investigated and could not include:** the public Kaggle payment dataset named in the project
  brief — this sandbox cannot reach kaggle.com (confirmed, see section 9). Documented as a decision
  in `docs/PROJECT_CONTEXT.md`, not silently dropped.

## 3. Files Created

| File | Purpose |
|---|---|
| `ml/config.py` | Every generation assumption in one place (demand seasonality, admin capacity, anomaly rates, the risk-label model, chronological split boundaries) |
| `ml/features.py` | Shared, file-I/O-free feature helpers (calendar columns, epoch-seconds conversion, causal per-student history, chronological split) reusable by Phase 5/6 on live database data later |
| `ml/simulate.py` | The world simulator: students -> applications -> OCR/eligibility -> payments -> admin queue -> decision, plus injected anomalies and their benign look-alikes |
| `ml/prepare.py` | Raw tables -> the four processed, model-ready CSVs |
| `ml/validate_datasets.py` | All integrity / consistency / leakage / signal-sanity checks; returns a summary dict and a list of hard-check failures |
| `ml/make_datasets.py` | Orchestrator: simulate -> write raw CSVs -> **read them back** -> build processed CSVs -> validate what was actually written -> `dataset_summary.json` with SHA-256 checksums |
| `ml/make_figures.py` | Three PNG sanity plots (daily volume, TAT distribution, risk label separation) |
| `ml/requirements.txt` | Pinned: numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1 (validator only), pytest 9.1.1, matplotlib 3.11.2 (figures only) |
| `ml/pytest.ini` | Lets `pytest` find the `ml` package from within `ml/` |
| `ml/tests/test_pipeline.py` | 8 tests: determinism, leakage, chronological splits, cross-check against the real backend eligibility rule, and more (section 9) |
| `ml/README.md` | Quick-start: setup, generate, test, figures |
| `docs/DATA_DICTIONARY.md` | Full documentation: every table/column, generation assumptions, validation methodology, known limitations |
| `ml/data/raw/{students,applications,transactions}.csv` | Generated data (see Data Note below) |
| `ml/data/labels/{application_labels,transaction_labels}.csv` | Generated answer keys |
| `ml/data/processed/{forecast_daily,tat_applications,risk_scoring,anomaly_transactions}.csv` | Generated model-ready datasets |
| `ml/data/dataset_summary.json` | Generation config, checksums, sanity numbers |
| `ml/data/figures/*.png` | Generated sanity-check plots |

**Data note:** the CSVs above are checked-in generated output, included so Phase 5 can start
immediately without waiting on a fresh generation. They are fully reproducible from the same seed
(`ml/config.py: SEED = 20260928`) via `python -m ml.make_datasets` — verified in section 9.

## 4. Files Modified

| File | Change |
|---|---|
| `README.md` | Status line updated to Phase 4; new "§5 ML datasets" section; `ml/` added to the project-structure diagram |
| `docs/PROJECT_CONTEXT.md` | Appended "Decisions carried from Phase 4" |

**`backend/` and `frontend/` were not touched** — confirmed with a diff against the Phase 3 zip
(section 9).

## 5. Current Project Structure

```
sdp-portal/
├── PHASE_1_STATUS.md ... PHASE_4_STATUS.md
├── docs/{PROJECT_CONTEXT.md, DATA_DICTIONARY.md}
├── backend/   (unchanged from Phase 3)
├── frontend/  (unchanged from Phase 3)
└── ml/
    ├── README.md, requirements.txt, pytest.ini
    ├── config.py, features.py, simulate.py, prepare.py, validate_datasets.py
    ├── make_datasets.py, make_figures.py
    ├── tests/test_pipeline.py
    └── data/
        ├── raw/{students,applications,transactions}.csv
        ├── labels/{application_labels,transaction_labels}.csv
        ├── processed/{forecast_daily,tat_applications,risk_scoring,anomaly_transactions}.csv
        ├── dataset_summary.json
        └── figures/{daily_volume,tat_distribution,risk_label_separation}.png
```

## 6. Database Changes

None. Phase 4 does not touch PostgreSQL, the running app, or any Phase 1-3 table.

## 7. APIs / Endpoints Added

None. Phase 4 produces flat files only; no new backend endpoints.

## 8. Features Currently Working

* `python -m ml.make_datasets` regenerates all 9 CSVs plus the summary/checksums in ~6 seconds and
  reports zero hard-check failures.
* `pytest` (from `ml/`) passes 8/8 in ~7 seconds, using a fast small-scale configuration separate
  from the full-size data.
* `python -m ml.make_figures` renders 3 real plots directly from the generated CSVs.
* The datasets are internally consistent with the live application's actual placeholder rules: a
  test independently recomputes `eligibility_result` from the raw columns using the same logic as
  `backend/app/services/eligibility.py` and requires an exact match; another test reads the actual
  backend source file and fails if its condition names ever change without `ml/config.py` being
  updated to match.

## 9. Testing Performed

| Test | Result | Notes |
|---|---|---|
| `python -m ml.make_datasets` (full size: 3,000 students, 3 years) | Pass | 16,543 applications, 14,887 transactions; 0 hard-check failures; ~6s |
| `pytest` (8 tests, small/fast config) | 8 passed | ~7s |
| **Determinism**: two independent runs, same seed | Byte-identical | Every raw/label/processed CSV compared byte-for-byte |
| **Non-determinism sanity-check**: two runs, different seeds | Files differ | Confirms the determinism test isn't vacuously true |
| **Tests actually catch real regressions** (injected, then reverted): (a) added a column that leaked the true generating probability into `risk_scoring.csv`'s features - caught by both the leakage test and the validator; (b) made the simulator ignore its seed - caught by the determinism test | Both caught, both reverted before this checkpoint | Proves the tests have teeth, not just pass by construction |
| Eligibility consistency: re-derived `eligibility_result` from raw columns using the same rule as `backend/app/services/eligibility.py`, compared to every row | Exact match, all rows | |
| Payment amounts: every non-`AMOUNT_MISMATCH` transaction equals `FEE_BY_DOCUMENT_TYPE`; every `AMOUNT_MISMATCH` one does not | Pass | |
| Chronological splits: every processed dataset's split label is non-decreasing when sorted by time; no split is empty | Pass | |
| No leakage: every processed feature column checked against a banned-substring/exact-name list (`sim_`, `true_`, `oracle`, `decided`, exact `status`); risk-scoring's causal history features re-derived independently and compared to what shipped | Pass | |
| **Manual review of the sanity numbers** (not just "checks passed"): oracle AUC 0.83-0.85 across splits (not 1.0 - the label has genuine irreducible noise); single-feature AUCs all <= 0.70 (no accidental leak); a throwaway logistic-regression baseline reaches 0.815 test AUC (real, learnable signal); anomaly rate 2.6% with all 4 injected types present and well-separated (best single-feature AUC 0.91-1.0); median TAT rises monotonically across queue-length quintiles (19.7h -> 47.8h) | Reviewed, numbers recorded in `dataset_summary.json` | See `docs/DATA_DICTIONARY.md` §6 for what each number means and why it's in a healthy range, not suspiciously perfect |
| **Visual inspection** of the 3 generated plots | Reviewed | Daily volume shows plausible multi-year seasonality (not noise); TAT histogram is right-skewed/multi-modal as a real queue with review holds would look; risk-label histogram shows genuine class overlap (not degenerate separation) |
| Confirmed `backend/` and `frontend/` are untouched | Pass | Diffed this checkpoint's `backend/`/`frontend/` file lists and contents against `PHASE_3_COMPLETE.zip` (the corrected one) - no differences |
| Kaggle dataset reachability | Confirmed unreachable | `curl https://www.kaggle.com/` -> HTTP 403, body: "Host not in allowlist: www.kaggle.com" - a sandbox network-egress block, not a Kaggle-side error; documented rather than silently worked around |

**Not tested because:**
* This phase was not run on Windows or macOS (same limitation as every prior phase - only Ubuntu
  was used here).
* No attempt was made to fetch the Kaggle dataset from a network that isn't sandboxed (see above);
  a team member with normal internet access would need to do this separately if they want it.
* The full-size generation (3,000 students) was run and validated multiple times during
  development, but only once as the final, shipped version - re-running it again would reproduce
  byte-identical files per the determinism test, so this is not treated as a gap.

## 10. Known Issues

* **Rapid-retry burst, first attempt:** about 1 in 6 `RAPID_RETRIES`-labelled transaction rows is
  the burst's first attempt, which is indistinguishable from a normal first attempt using only that
  row's own features (nothing about it is unusual until the next attempt happens seconds later). A
  row-level classifier (Phase 5C's planned approach) cannot flag these from the row alone. Worth
  discussing with the team before Phase 5C starts: either accept this as a known miss, or add a
  short lookback/lookahead window as a feature (which would change the "grain" of the dataset).
* **No real public dataset included** (see above) — Phase 5C will train only on the simulated
  `anomaly_transactions.csv`.
* **Duplicate-request anomaly count is small** (50 rows in the full-size run) — enough to validate
  separability, but a held-out test split will only see a handful of examples of this specific
  anomaly type; interpret Phase 5C's `DUPLICATE_REQUEST` metrics on the test split with that in
  mind.
* Every eligibility rule, fee amount, and processing-capacity assumption is exactly what section 8
  of `docs/DATA_DICTIONARY.md` lists as "worth a second opinion" — none of it is measured from real
  KLE Tech operations, because none exists for this project.

## 11. Important Decisions

See `docs/PROJECT_CONTEXT.md` → "Decisions carried from Phase 4" for the full list (workflow-driven
simulation instead of independent-table sampling; Kaggle dataset omitted with reasoning; anomalies
seeded alongside benign look-alikes; risk scoring restricted to decided applications with a
deliberately noisy, non-perfect-ceiling label; chronological splits are load-bearing for Phase 5).

## 12. Environment / Setup Requirements

Python 3.11+ (tested 3.12.3). `ml/` has its own virtual environment, independent of
`backend/.venv` — see `ml/requirements.txt`. No database, no `.env`, no secrets of any kind in this
phase.

## 13. How to Run This Phase

```bash
cd ml
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd ..                              # project root
python -m ml.make_datasets         # regenerates all 9 CSVs; expect: "hard checks failed: 0"

cd ml
pytest                             # expect: 8 passed

cd ..                              # project root
python -m ml.make_figures          # writes 3 PNGs to ml/data/figures/
```

## 14. What Is NOT Implemented Yet

No models are trained (that's Phase 5A/5B/5C). No admin dashboard consumption of any of this
(Phase 6). No integration with the live database — this phase is entirely offline, flat-file data
preparation, as scoped.

## 15. NEXT PHASE

* **Phase 5 — AI/ML** (5A Demand & TAT Forecasting, 5B Eligibility Risk Scoring,
  5C Anomaly Detection).
* To implement: pick and train one forecasting model on `forecast_daily.csv`/
  `tat_applications.csv` (candidates named in the brief: SARIMA, Prophet, XGBoost, LightGBM,
  LSTM/GRU - choose based on what the actual data looks like); a Logistic Regression baseline on
  `risk_scoring.csv` with real precision/recall/F1/AUC and feature importance; an Isolation Forest
  on `anomaly_transactions.csv` evaluated against the known injected anomaly types. Save each
  trained model and expose a plain prediction function/thin endpoint per component.
* Expected changes: a new `ml/models/` (or similar) for trained model artifacts; likely a new
  `backend/app/services/` module per component so Phase 6's admin dashboard can call them; probably
  no new database tables yet (predictions can be computed on demand) unless the team decides to
  cache them.
* Depends on: the four processed datasets and `dataset_summary.json` from this phase; the oracle
  AUC ceiling and single-feature AUCs recorded there, as a floor/ceiling to compare Phase 5B against
  rather than chasing an unrealistic AUC 1.0; the documented rapid-retry-first-attempt limitation
  for Phase 5C.
* Decisions needed before/at the start of Phase 5: (a) confirm the team is fine with the risk-model
  oracle-AUC ceiling of ~0.85 (i.e., that a real Phase 5B model in the low-to-mid 0.80s AUC range is
  the expected, correct outcome, not a sign the model needs more tuning); (b) how to handle the
  rapid-retry first-attempt limitation in Phase 5C (accept the miss, or change the anomaly
  dataset's grain to include a short lookback/lookahead window - the latter would mean revisiting
  `ml/prepare.py:build_anomaly_transactions`); (c) whether trained models are saved as files
  checked into the repo (simple, but can bloat the zip) or regenerated on demand from a training
  script (slower to demo, smaller checkpoint) - a call the team should make once they see how large
  the trained artifacts are.

## 16. HANDOFF INSTRUCTIONS

1. Unzip `PHASE_4_COMPLETE.zip`. `backend/` and `frontend/` are exactly Phase 3's — you do not need
   to re-verify those unless you suspect this checkpoint corrupted something (it didn't, per
   section 9's diff, but a `pytest` run in `backend/` costs nothing to double-check).
2. Follow section 13. Confirm `python -m ml.make_datasets` reports "hard checks failed: 0" and
   `pytest` (from `ml/`) shows 8 passed before writing any Phase 5 code.
3. Read `docs/DATA_DICTIONARY.md` in full before touching any processed dataset - it tells you
   exactly which columns are features vs. labels, what's already been checked, and the two open
   decisions in section 15 above that the team should make before Phase 5C in particular.
4. If you add a column to any processed dataset, add it to the leakage check in
   `ml/validate_datasets.py` (`FORBIDDEN_FEATURE_SUBSTRINGS` / the constant-column check) rather
   than skipping validation for it.
5. If you regenerate the data with a different `SEED` or different `SimConfig` values, note the new
   seed/config in `PHASE_5_STATUS.md` so results are reproducible by whoever reads it next.
