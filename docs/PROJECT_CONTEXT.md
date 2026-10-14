# Project context (source of truth for every phase)

Derived from the team's SDP deck (`sdp_project_r1.pptx`) and the project brief. If a later request
conflicts with this file, ask before changing scope.

## What we are building
An improvement of the existing KLE Tech online academic-document application workflow
(exam.kletech.ac.in), NOT an unrelated generic portal. Document types: transcripts, migration
certificates, duplicate grade cards (the deck also says "duplicate mark cards"), provisional degree
certificates.

## Workflow (deck architecture, slide 13) + payment (from the project brief)
Student -> Application & Documents -> OCR & Data Extraction -> Eligibility -> Payment ->
AI/ML Processing -> Admin -> Verification -> Document Generation -> Live Tracking -> Student.
PostgreSQL is the central data store. The AI/ML components are NOT sequential steps: they read
application/transaction/history data and feed the admin workflow and analytics dashboard.
Note: the deck diagram itself does not draw a Payment box (payment appears in the deck text).

## AI/ML components (exactly three) + OCR
1. Demand & TAT Forecasting: one primary model, chosen from the actual data (candidates in the
   deck: SARIMA, Prophet, XGBoost, LightGBM, LSTM/GRU).
2. Eligibility Risk Scoring: probability (0-1) that an application needs MANUAL REVIEW. It does not
   decide eligibility. Start with Logistic Regression; Random Forest only if justified.
3. Anomaly Detection: duplicate requests, amount mismatches, rapid payment retries. Start with
   Isolation Forest. Output: Normal, or Anomalous -> Admin Review.
OCR is a supporting component (extracts fields from uploaded documents), not a core ML component.
Rule-based eligibility (academic condition, fee status, required documents) is separate and
deterministic. The administrator always makes the final decision (human-in-the-loop).

## Out of scope unless the team explicitly asks
Blockchain, SHA-256 document hashing, QR verification, cryptocurrency, LLM agents / multi-agent
systems / multiple LLMs, facial recognition, biometrics, other unrelated AI features.

## Data rules
* No real KLE Tech student data exists for this project. Never claim models were trained on it.
* Student/application data is SIMULATED. The payment dataset is a PUBLIC Kaggle payment/credit-card
  dataset. Keep these (and any engineered data) clearly labelled as such. Do not invent real
  institutional statistics.

## Stack
Next.js, FastAPI, PostgreSQL, SQLAlchemy + Alembic, pandas/NumPy/scikit-learn (XGBoost where
appropriate), a practical Python OCR library, JWT for auth, Git/GitHub.

## Phases
1 Setup & database | 2 Student portal | 3 OCR + eligibility + payment | 4 Dataset preparation |
5 AI/ML (5A forecasting, 5B risk scoring, 5C anomaly detection) | 6 Admin dashboard |
7 Admin review + document generation + tracking | 8 Integration & testing.
Work one phase at a time; each ends with PHASE_<N>_STATUS.md and PHASE_<N>_COMPLETE.zip.

## Decisions carried from Phase 2 (see PHASE_2_STATUS.md section 11 for the reasoning)
* Registration links a login to a PRE-LOADED simulated student record by USN (12 seeded students,
  `app/db/seed_students.py`); a student cannot self-report their CGPA/backlogs/etc.
* Application status vocabulary is fixed in `app/core/statuses.py`
  (`ApplicationStatus`): SUBMITTED, OCR_COMPLETED, ELIGIBLE, NOT_ELIGIBLE, PAYMENT_PENDING,
  PAYMENT_COMPLETED, UNDER_REVIEW, VERIFIED, REJECTED, DOCUMENT_GENERATED. Every status change goes
  through `services/applications.set_status()`, which also writes `application_status_history`.
* Uploads: PDF/JPG/PNG only, verified by file content (magic bytes), not filename or the
  browser-supplied content type; 5 MB per file (`MAX_UPLOAD_MB`); at most 5 files per application;
  stored under `backend/uploads/<application_id>/<random-name>.<ext>`, original filenames are
  metadata only, never used as a path.

## Decisions carried from Phase 3 (see PHASE_3_STATUS.md for the reasoning)
* OCR library: `pytesseract` (wraps the system `tesseract` binary) + `pdf2image` (wraps the system
  `pdftoppm` binary, from `poppler-utils`) — both binaries were already present in the build
  environment and both Python wrappers installed cleanly, so no alternative was needed. A failed
  OCR on one file is recorded on that file (`ocr_results.status = FAILED`) and does not block the
  rest of the application.
* Eligibility thresholds (`app/services/eligibility.py`) are an explicitly-labelled PLACEHOLDER
  policy (asked; no real thresholds were given): fee status must be CLEAR for every document type;
  a Provisional Degree Certificate additionally requires zero backlogs; no CGPA minimum anywhere;
  every document type requires at least one attached supporting document. Swap
  `RULES_BY_DOCUMENT_TYPE` when the real policy is known — the engine itself doesn't change.
* Payment fee schedule (`app/services/payments.py` `FEE_BY_DOCUMENT_TYPE`) is likewise a
  PLACEHOLDER (round numbers, not a real KLE Tech fee circular). Payment is sandbox/mock only, per
  the "no real gateway" boundary above: `POST /payment/complete` takes the outcome
  (`"success"`/`"failure"`) directly instead of a real gateway callback — a real integration would
  replace that input with an actual webhook. A failed attempt never marks the application
  completed; the application stays PAYMENT_PENDING so the student can retry, and every attempt
  (failed or not) stays in `transactions` for the audit trail / later anomaly-detection signal.

## Decisions carried from Phase 4 (see PHASE_4_STATUS.md for the reasoning)
* Phase 4 (`ml/`) is a standalone subproject: it never touches the running app's database or code,
  and generates data by SIMULATING the Phase 1-3 workflow forward in time (students -> seasonal
  application arrivals -> OCR -> the real placeholder eligibility rule -> the real fee schedule ->
  a finite-capacity FIFO admin queue -> a latent manual-review model -> VERIFIED/REJECTED), not by
  sampling each table independently. Turnaround time EMERGES from the queue simulation rather than
  being assigned by a formula.
* The public Kaggle payment dataset named in the brief was NOT included: this sandbox's network
  egress cannot reach kaggle.com (confirmed via curl: a 403 "not in allowlist" proxy block, not a
  Kaggle-side error). Anomaly detection (Phase 5C) will train only on the simulated
  `anomaly_transactions.csv`. See `docs/DATA_DICTIONARY.md` §0/§6 for what a team member with
  normal network access should do instead of just merging the Kaggle dataset in (its features are
  anonymised with no application_id linkage, so it can't replace the application-linked features
  here even if fetched).
* Injected anomalies (duplicate requests, rapid payment retries, frequency bursts, amount
  mismatches) are seeded alongside deliberate BENIGN look-alikes (legitimate alumni multi-document
  bundles, honest re-applications after a rejection, single accidental payment retries) so Phase 5C
  isn't trivially easy. One documented, unresolved limitation: the first payment attempt of a
  rapid-retry burst is indistinguishable from a normal first attempt at the row level - a row-level
  model cannot flag it from that row alone. Worth raising with the team before Phase 5C starts.
* Eligibility risk scoring (Phase 5B) is trained only on DECIDED (VERIFIED/REJECTED), ELIGIBLE
  applications - still-open ones are right-censored and excluded, matching what training from the
  live database would actually look like. The label is deliberately noisy (a latent probability,
  not a deterministic rule), giving an oracle AUC ceiling of ~0.83-0.85 rather than 1.0 - Phase 5B
  should not expect or chase a higher number than that on this data.
* Every processed dataset carries a chronological `train`/`valid`/`test` split
  (`ml/config.py: SimConfig.train_end/valid_end`); never shuffle across the split boundary in
  Phase 5, or the chronological guarantee (and the forecasting lag/rolling features) breaks.

## Decisions carried from the student-portal / Docker update (README sections 1-2)
* Student workflow is automatic: after submission the portal calls `POST /api/applications/{id}/process`
  (`app/services/processing.py`), which chains the existing OCR and eligibility services through `set_status()`.
  Idempotent and serialised per application (PostgreSQL advisory lock); eligibility runs only when OCR succeeded
  for every file; OCR retry is explicit (`?retry_ocr=true`); payment is never started automatically.
* The status vocabulary has no "OCR failed" state, so a failed file leaves the application at OCR_COMPLETED with the
  per-file `ocr_results.status = FAILED` shown to the student; the history note records how many files could not be read.
* `ApplicationDetail.fee_amount` exposes the placeholder fee from `payments.FEE_BY_DOCUMENT_TYPE` (single source of truth).
* Docker: `compose.yaml` (db + backend + frontend), named volumes `pgdata` and `uploads`, backend image keeps the
  `/srv/sdp/backend` + `/srv/sdp/ml` layout that `ml_services.py` expects. The admin side is still not built.
