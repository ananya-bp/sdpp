# Phase 3 — Completion Status

Project: AI-Enhanced University Document Issuance, Tracking and Administrative Analytics Portal
(SDP, Course 20ECSW401, Team 27). Checkpoint date: 26 Sep 2026. Builds on Phase 2
(see `PHASE_2_STATUS.md`); nothing from Phase 1/2 was rebuilt without reason (see section 11).

## 1. Phase Goal

Implement OCR extraction from uploaded supporting documents, rule-based eligibility checking
(academic condition, fee status, required documents), and sandbox/mock payment linked to an
application. Expected output: an application moves SUBMITTED → OCR_COMPLETED → ELIGIBLE /
NOT_ELIGIBLE → PAYMENT_PENDING → PAYMENT_COMPLETED, each transition recorded in
`application_status_history`.

## 2. What Was Completed

* **OCR:** `POST /applications/{id}/ocr` extracts text from every attached file (PDF/JPG/PNG) using
  Tesseract (via `pytesseract`), rasterizing PDFs first with `pdf2image`/`poppler`. Stores raw text
  plus a handful of regex-extracted fields (USN, CGPA-shaped numbers, dates) per file in a new
  `ocr_results` table. A single unreadable/corrupt file is recorded as FAILED on that file only and
  does not block the rest of the application or the request.
* **Eligibility:** `POST /applications/{id}/eligibility` runs a deterministic rule engine
  (`app/services/eligibility.py`) — NOT the Phase 5 ML risk-scoring model. Conditions: fee status
  must be CLEAR (every document type); a Provisional Degree Certificate additionally requires zero
  backlogs; every document type requires at least one attached supporting document; no CGPA
  minimum. Thresholds are an explicitly-labelled placeholder policy (see section 11.1) — the team
  had no real KLE Tech thresholds to give.
* **Payment:** `POST /applications/{id}/payment/initiate` and `/payment/complete` implement a
  sandbox/mock payment (no real gateway, per the project's stated boundaries) against a placeholder
  fee schedule. A failed outcome updates that transaction and leaves the application at
  PAYMENT_PENDING so the student can retry — it is never silently marked completed. Every attempt
  (failed or successful) is kept in `transactions` for the audit trail.
* **Database:** one new table (`ocr_results`, 1:1 with `uploaded_documents`) via an Alembic
  migration on top of Phase 2; `transactions` (existing since Phase 1, unused until now) gets real
  rows; `Application.transactions` relationship added.
* **Frontend:** the application detail page gained a "Next step" action card (Run OCR → Check
  eligibility → Start/simulate payment, one action at a time based on current status), OCR results
  shown per uploaded file, and a payments table.
* **Tests:** 31 new backend tests (8 OCR — real Tesseract/poppler runs against generated sample
  images/PDFs, no mocking; 14 eligibility — against the real seeded students, showing different,
  correct outcomes; 9 payment — success, failure, retry, the not-eligible-can't-pay guard, and a regression test that
  the initiate response contains the new PENDING transaction), for 80 total.

## 3. Files Created

| File | Purpose |
|---|---|
| `backend/app/models/ocr_result.py` | `OcrResult` model (1:1 with `UploadedDocument`) |
| `backend/app/services/ocr.py` | OCR extraction (pytesseract + pdf2image) and per-application runner |
| `backend/app/services/eligibility.py` | Deterministic rule engine + per-application runner |
| `backend/app/services/payments.py` | Sandbox/mock payment (initiate/complete) |
| `backend/alembic/versions/*_add_ocr_results.py` | Migration: `ocr_results` table only |
| `backend/tests/test_ocr.py`, `test_eligibility.py`, `test_payments.py` | New tests |

## 4. Files Modified

| File | Change |
|---|---|
| `backend/requirements.txt` | Added `pytesseract`, `pdf2image` |
| `backend/app/models/__init__.py` | Registered `OcrResult` |
| `backend/app/models/uploaded_document.py` | Added `ocr_result` relationship |
| `backend/app/models/application.py` | Added `transactions` relationship |
| `backend/app/schemas/application.py` | Added `OcrResultOut`, `TransactionOut`, `PaymentCompleteIn`; `DocumentOut` now includes `ocr_result`; `ApplicationDetail` now includes `transactions` |
| `backend/app/services/applications.py` | `load_application` now eager-loads `ocr_result` per document and `transactions` |
| `backend/app/api/routes/applications.py` | Added `/ocr`, `/eligibility`, `/payment/initiate`, `/payment/complete` |
| `frontend/lib/api.js` | Added `apiPostAuth` (authenticated JSON/no-body POST, for the new action endpoints) |
| `frontend/app/applications/[id]/page.js` | Added the "Next step" action card, per-file OCR result display, payments table |
| `frontend/app/globals.css` | Added `.actions-row`, `button.secondary`, `.ocr-result`, `.ocr-text` styles |
| `README.md`, `docs/PROJECT_CONTEXT.md` | Updated for Phase 3 (Prerequisites: Tesseract/poppler; usage walkthrough; Phase 3 decisions section) |

## 5. Current Project Structure

```
sdp-portal/
├── PHASE_1_STATUS.md
├── PHASE_2_STATUS.md
├── PHASE_3_STATUS.md
├── docs/PROJECT_CONTEXT.md
├── backend/
│   ├── alembic/versions/
│   │   ├── 20260920_10866ea4850c_initial_schema.py
│   │   ├── <ts>_4f0afcfbe2f6_add_uploaded_documents.py
│   │   └── 20260925_2d9f0673822c_add_ocr_results.py
│   ├── app/
│   │   ├── main.py
│   │   ├── core/{config,statuses,security}.py
│   │   ├── db/{base,session,seed,seed_students}.py
│   │   ├── models/{user,student,document_type,application,uploaded_document,ocr_result,transaction}.py
│   │   ├── services/{uploads,applications,ocr,eligibility,payments}.py
│   │   ├── schemas/{document_type,auth,application}.py
│   │   └── api/{deps.py, routes/{health,document_types,auth,applications}.py}
│   └── tests/{conftest,test_api,test_schema,test_auth,test_applications,test_uploads,
│               test_statuses,test_ocr,test_eligibility,test_payments}.py
└── frontend/
    ├── lib/{api,auth,status}.js
    └── app/
        ├── {layout,page,nav-bar,globals.css}
        ├── register/, login/, dashboard/, apply/
        └── applications/[id]/
```

## 6. Database Changes

Migration `2d9f0673822c` ("add ocr results"), on top of Phase 2's `4f0afcfbe2f6`. Verified: upgrade
from the Phase 2 database, downgrade one step, upgrade again, and upgrade on a brand-new empty
database (clean-room rebuild, section 9).

| Table | Change |
|---|---|
| `ocr_results` (new) | id, uploaded_document_id (FK → uploaded_documents, CASCADE, UNIQUE — one result per file), status (SUCCESS/FAILED), raw_text, extracted_fields (JSONB), error_message, processed_at |

No Phase 1/2 table's columns changed. `transactions` (Phase 1) is used for the first time, exactly
as it was already defined: `application_id`, `amount`, `payment_status`, `transacted_at`.

## 7. APIs / Endpoints Added

| Method | Endpoint | Purpose | Status |
|---|---|---|---|
| POST | `/api/applications/{id}/ocr` | Run OCR on every attached file; advances to OCR_COMPLETED | Working, tested |
| POST | `/api/applications/{id}/eligibility` | Evaluate rule-based eligibility; sets ELIGIBLE/NOT_ELIGIBLE | Working, tested |
| POST | `/api/applications/{id}/payment/initiate` | Start a sandbox payment attempt (PENDING transaction); sets PAYMENT_PENDING | Working, tested |
| POST | `/api/applications/{id}/payment/complete` | Record the mock gateway's outcome; SUCCESS → PAYMENT_COMPLETED, FAILURE → stays PAYMENT_PENDING | Working, tested |

Phase 1/2 endpoints (health, document-types, auth, application submit/list/detail) are unchanged;
`GET /applications/{id}` now additionally returns `documents[].ocr_result` and `transactions`.

## 8. Features Currently Working

* OCR correctly extracts real text from both a generated PNG and a generated PDF (the PDF is
  rasterized page-by-page first), and correctly finds a USN, a CGPA-shaped number, and a date in
  that text via regex.
* A blank image OCRs successfully with empty text (not treated as a failure); a corrupt/unreadable
  PDF is recorded as a FAILED result on that one file, and the request still returns 200 with the
  rest of the application intact.
* Eligibility gives different, correct outcomes for different real seeded students: a student with
  a fee due is NOT_ELIGIBLE for every document type; a student with backlogs is NOT_ELIGIBLE only
  for a Provisional Degree Certificate (other types don't check backlogs); a clean student with no
  attached documents is still NOT_ELIGIBLE (documents-required rule); every reason is recorded in
  the status-history note.
* Payment cannot be started unless the application is ELIGIBLE (NOT_ELIGIBLE and SUBMITTED
  applications are rejected with 400). A failed payment leaves the application payable again; the
  detail page then offers a "Retry payment" button (added in review, section 9b), which creates a
  new transaction row while keeping the failed one; only a successful outcome
  advances the application to PAYMENT_COMPLETED.
* A student cannot run any Phase 3 action on another student's application (404).
* The full flow works through real browser-style interaction on the application detail page: Run
  OCR → Check eligibility → Start payment → Simulate successful/failed payment, one button at a
  time depending on current status.

## 9. Testing Performed

| Test | Result | Notes |
|---|---|---|
| `pytest` (80 tests total: 49 from Phase 1/2 + 31 new) | 80 passed | Real PostgreSQL 16; OCR tests run the real Tesseract/poppler pipeline (no mocking) against generated sample files |
| Migration: Phase-2 DB → upgrade → downgrade → upgrade; and on a brand-new empty DB | Pass | |
| `alembic check` after adding the `transactions` relationship | No new upgrade operations detected | Confirms `transactions` needed no schema change, as expected |
| Live server, `curl` walk-through: register/login → submit with a real generated image → OCR → eligibility → payment initiate → failed payment → retry → successful payment | Pass | Manual test data (registration) cleaned up from the dev database afterwards |
| Live server, `curl` walk-through: application with no eligibility-passing documents → NOT_ELIGIBLE → payment correctly refused | Pass | |
| **Clean-room rebuild**: fresh copy of only the files a `git` checkout would contain (no `.venv`, `node_modules`, `.env`, caches), brand-new database/role with a password containing `@`, `:` and `%`, followed the README literally end to end (venv, install, `.env`, generate `SECRET_KEY`, migrate, both seeds, `pytest`, `npm install`, `npm run build`), then a full live `curl` walkthrough (register → submit with a real image → OCR → eligibility → payment initiate → payment complete) against the freshly rebuilt server | Pass | 79/79 tests at submission (80/80 after the review fixes, see 9b); full flow reached PAYMENT_COMPLETED; database and role dropped afterwards |
| Frontend production build (`npm run build`) | Pass | No warnings/errors, both in the main working copy and the clean-room copy |
| Manual database state checked before and after every run | Pass | No leftover test/smoke-test rows in the working (`sdp_portal`) database |

**No bugs found during this testing that required a fix** — unlike Phase 2, nothing was left broken
in a working file by the time of this checkpoint. (Process note, not a product bug: running a local
background `uvicorn` process across separate tool invocations in this environment did not persist
between calls, and starting it without redirecting `stdin` from `/dev/null` caused the invoking
shell to hang; both were worked around by keeping start-server/test/kill-server together in one
step with `< /dev/null` redirection — noted here in case a future phase automates this further.)

**Not tested because:**
* Windows and macOS (same limitation as Phase 1/2; only Ubuntu was used).
* `npm run dev` (development server) — only the production build was run, plus the manual detail-page
  code review; the original submission did no headless-browser click-through (curl-level API
  verification was used instead). A real headless-browser pass was done afterwards during review
  and found two bugs - see 9b.
* Concurrent OCR/eligibility/payment requests on the same application (each service call is a
  normal request/response; no explicit locking was added, matching Phase 1/2's scope).
* OCR on a genuinely low-quality scanned image (all test files here were clean generated text) —
  Tesseract's accuracy on real messy scans is a known general limitation, not something this
  checkpoint re-verified.

## 9b. Review corrections (found by a real headless-browser pass after submission)

The submission's own status file said a browser click-through was not done. Doing it found two
bugs that the API-level tests could not see. Both are fixed in this checkpoint.

1. **Frontend dead end after a failed payment** (`frontend/app/applications/[id]/page.js`).
   `nextAction()` chose the button from `status` alone, but `PAYMENT_PENDING` is also the state
   right after a *failed* payment, when no pending transaction is left. The page kept offering
   "Simulate successful/failed payment", which answered 400 "No pending transaction to complete.",
   and a student could not retry through the UI. Fix: `nextAction(app)` now checks
   `app.transactions` for a PENDING row, otherwise offers "Retry payment" (calls
   `/payment/initiate` again).
2. **Stale `transactions` in the `payment/initiate` response**
   (`backend/app/services/applications.py`). Routes reload the application for their response, but
   the production session uses `expire_on_commit=False`, so the reload returned the already-loaded,
   pre-change collection and `payment/initiate` answered with `transactions: []` although a PENDING
   row had just been committed (a fresh GET showed it). This was latent until fix 1 started
   depending on that list. Fix: `load_application` uses
   `.execution_options(populate_existing=True)`.
3. **Why 79 green tests missed it.** `tests/conftest.py` built the test session with SQLAlchemy's
   defaults (`expire_on_commit=True`), unlike production, so every commit expired objects and hid
   the staleness. The fixture now uses `expire_on_commit=False, autoflush=False` to match
   production, and a new test (`test_initiate_response_includes_the_new_pending_transaction`)
   asserts the response contents. Verified both ways: with the fix disabled, 3 tests fail (the new
   one plus the existing payment-success and retry flows); with it enabled, all 80 pass.

Verified in a real headless browser after the fixes: submit → OCR (extracted "SIM23CSE001 CGPA
8.90" from a generated PDF) → eligibility → Start payment → failed payment (only "Retry payment"
offered) → Retry (Payments table shows FAILED then PENDING) → successful payment
(PAYMENT_COMPLETED, table FAILED + SUCCESS). The not-eligible path was re-run in the browser too:
a fee-DUE student with no documents is blocked with both reasons shown and no payment button.

## 10. Known Issues

* Eligibility thresholds and the payment fee schedule are placeholders (section 11.1/11.2) — must
  be replaced with real KLE Tech policy before this could be used for anything beyond the course
  project.
* The mock payment's `outcome` field is supplied directly by the caller (student's browser) rather
  than by a real gateway callback — acceptable for a sandbox, but flagged so it isn't mistaken for
  a real integration later.
* `frontend/lib/status.js`'s manual status-class mapping (noted in Phase 2 as a known issue) was not
  changed; the new statuses (OCR_COMPLETED, PAYMENT_PENDING, PAYMENT_COMPLETED) fall through to the
  default "in progress" pill style, which is correct, but the duplication with
  `backend/app/core/statuses.py` still exists.
* On a payment retry the status timeline shows two identical "Payment pending — Payment initiated:
  200.00" entries (one per attempt). Correct, but the note does not say which attempt it is —
  cosmetic; a future phase could add the attempt number to the note.
* The test suite assumes the target database has no committed leftovers from manual testing: it
  rolls back its own writes but cannot hide rows already committed (e.g. a manually registered
  simulated student). Two eligibility tests failed for exactly this reason when run against a
  database used for manual/browser testing; clean it (or use a fresh database) before `pytest`.
* Pytest still prints the same harmless Starlette/anyio deprecation warning noted in Phase 1/2.

## 11. Important Decisions

1. **Eligibility thresholds are a placeholder policy, not real institutional policy.** Asked
   directly which thresholds to use (simple defaults / stricter defaults / custom); no specific
   values were given, so the "simple defaults" option was used: fee CLEAR required everywhere,
   zero-backlogs required only for a Provisional Degree Certificate, no CGPA minimum, at least one
   document required everywhere. `RULES_BY_DOCUMENT_TYPE` in `app/services/eligibility.py` is
   structured so the real policy can be swapped in later without touching the engine.
2. **Payment fee schedule is likewise a placeholder** (`FEE_BY_DOCUMENT_TYPE` in
   `app/services/payments.py`) — round, clearly-fake numbers, since no real KLE Tech fee circular
   was available (same situation as Phase 2's "transactions.amount has no source of truth yet").
3. **OCR library:** `pytesseract` + `pdf2image`, chosen because both underlying system binaries
   (`tesseract`, `pdftoppm` from `poppler-utils`) were already present in the build environment and
   both Python wrappers installed and worked correctly with real generated sample files on the
   first attempt — no alternative library was needed.
4. **Mock payment takes its outcome as direct input**, not a webhook, since there's no real gateway
   to call back from (documented boundary: "sandbox/mock payment, no real gateway"). This is
   flagged in code and above as the one piece a real integration would need to replace.
5. **A per-file OCR failure never blocks the application.** One corrupt upload shouldn't stop a
   student's whole request; it's recorded on that file (`ocr_results.status = FAILED`) and surfaced
   to the student, while the rest of the application proceeds normally.
6. **A failed payment never silently completes the application.** `complete_payment()` only calls
   `set_status(PAYMENT_COMPLETED)` on outcome `"success"`; a `"failure"` updates the transaction row
   and nothing else, so the application stays exactly where a student can retry from.
7. **Nothing in Phase 1/2 was rebuilt without reason.** Every change to an existing file (section 4)
   is additive (a new relationship, a new route, a new schema field) required by Phase 3, not a
   rewrite of working logic.
8. **No admin functionality yet, no ML components yet.** Rule-based eligibility here is explicitly
   NOT the Phase 5 Eligibility Risk Scoring model — that's a separate, later, probabilistic
   component; this phase's eligibility check is deterministic and final for the student-facing flow.

## 12. Environment / Setup Requirements

Same as Phase 1/2 (Python 3.11+, Node 20.9+, PostgreSQL 15+), plus:
* System packages `tesseract-ocr` and `poppler-utils` must be installed (`sudo apt-get install
  tesseract-ocr poppler-utils` on Debian/Ubuntu) — required for OCR to work and for the OCR tests to
  pass.
* `backend/requirements.txt` gained `pytesseract` and `pdf2image` (installed via the usual `pip
  install -r requirements.txt`).

## 13. How to Run This Phase

```bash
# Backend
cd backend
source .venv/bin/activate          # after the Phase 1/2 venv/install steps
pip install -r requirements.txt    # picks up pytesseract, pdf2image
alembic upgrade head               # applies the Phase 3 migration on top of Phase 1+2
python -m app.db.seed
python -m app.db.seed_students
pytest                             # expect: 80 passed
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> → Register with a seeded USN → New application (attach a PDF/JPG/PNG
for eligibility's "at least one document" rule to pass) → Submit → on the application's status
page, use the "Next step" card: Run OCR → Check eligibility → Start payment → simulate a
successful or failed payment.

## 14. What Is NOT Implemented Yet

ML datasets (Phase 4), the three ML components — Demand & TAT Forecasting, Eligibility Risk
Scoring, Anomaly Detection (Phase 5), admin dashboard (Phase 6), admin review/verification/document
generation/live-tracking UI (Phase 7 — the status history model already supports it), integration
testing (Phase 8). No admin login/role UI. No password reset.

## 15. NEXT PHASE

* **Phase 4 — Dataset preparation.**
* To implement: prepare the datasets the Phase 5 ML components will train on — demand/TAT history
  (can now be partly seeded from real `application_status_history` timestamps generated by using
  this portal, plus synthetic volume), eligibility risk-scoring features (student CGPA/backlogs/fee
  status from `students`, application outcomes from Phase 3's eligibility decisions), and the
  anomaly-detection dataset (the project brief specifies a public Kaggle payment/credit-card
  dataset for this, kept clearly labelled as such per `docs/PROJECT_CONTEXT.md`'s data rules).
* Depends on: `application_status_history` (Phase 1/2, now populated through OCR_COMPLETED /
  ELIGIBLE / NOT_ELIGIBLE / PAYMENT_PENDING / PAYMENT_COMPLETED by this phase), `transactions`
  (Phase 1, now populated by this phase), `students` (Phase 1, CGPA/backlogs/fee_status for
  eligibility-risk features), `ocr_results` (Phase 3, `extracted_fields` may be a useful feature
  source later).
* Decisions needed before/at the start of Phase 4: (a) how much synthetic volume is needed on top
  of what this dev environment's own testing has generated, to make demand/TAT forecasting
  meaningful; (b) confirm the specific Kaggle payment/credit-card dataset to use for anomaly
  detection and how its columns map onto this project's `transactions` shape; (c) whether
  eligibility-risk labels come from Phase 3's own ELIGIBLE/NOT_ELIGIBLE outcomes or need a separate
  "needed manual review" label not yet captured anywhere.

## 16. HANDOFF INSTRUCTIONS

1. Unzip `PHASE_3_COMPLETE.zip` (it supersedes `PHASE_2_COMPLETE.zip`; all status files are kept
   for history). Follow section 13 and confirm `pytest` shows 80 passed and the full
   register → apply → OCR → eligibility → payment flow works in a browser before writing new code.
2. Re-read `docs/PROJECT_CONTEXT.md`, updated with the Phase 3 decisions section.
3. Add new tables/columns only through new Alembic migrations, as in Phase 1/2. Do not edit the
   three existing migration files.
4. Reuse `services/applications.set_status()` for every status change so
   `application_status_history` stays authoritative — don't set `Application.status` directly. The
   Phase 3 services (`ocr.py`, `eligibility.py`, `payments.py`) all do this already; follow the same
   pattern for Phase 4/5 if any status changes are needed there.
5. Keep `backend/.env`, `frontend/.env.local`, and `backend/uploads/` out of Git and out of ZIPs
   (already in `.gitignore`); add any new setting to `.env.example` with a placeholder.
6. Before treating any new dataset or ML output as real, check `docs/PROJECT_CONTEXT.md`'s data
   rules — student/application data is simulated, and Phase 4's anomaly-detection dataset must be a
   clearly-labelled public source, not invented statistics.
7. Record new decisions in `PHASE_4_STATUS.md`; don't rebuild working Phase 1/2/3 pieces without a
   stated reason, per the phase-handoff rule.
