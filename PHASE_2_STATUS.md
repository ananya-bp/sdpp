# Phase 2 — Completion Status

Project: AI-Enhanced University Document Issuance, Tracking and Administrative Analytics Portal
(SDP, Course 20ECSW401, Team 27). Checkpoint date: 25 Sep 2026. Builds on Phase 1
(see `PHASE_1_STATUS.md`); nothing from Phase 1 was rebuilt without reason (see section 11).

## 1. Phase Goal

Implement the basic student workflow: registration/login, student dashboard, application form
with document-type selection, supporting-document upload, application submission, and basic
application status. Expected output: Student → Application → Upload → Status.

## 2. What Was Completed

* **Auth:** register (linking a login to a pre-loaded simulated student record by USN), login,
  `/auth/me`. Passwords hashed with Argon2; JWT bearer tokens.
* **Applications:** submit an application (document type + up to 5 optional PDF/JPG/PNG files in
  one multipart request), list my applications, view one application's detail (status timeline +
  files). All scoped to the signed-in student; ownership enforced server-side.
* **Uploads:** validated by actual file content (not filename or browser-claimed type), size-capped,
  stored outside the web root with randomised names; a failure partway through an upload rolls back
  the database and deletes any files already written.
* **Database:** one new table (`uploaded_documents`) via an Alembic migration on top of Phase 1;
  application/document relationships (cascading delete) added to the existing models; a status
  vocabulary and a `set_status()` helper that also writes `application_status_history`, ready for
  later phases to reuse; 12 simulated student records seeded for development and testing.
* **Frontend:** register, login, dashboard (list + status pills), new-application form (file
  picker with client-side type/count pre-checks), application detail page (status timeline, file
  list), and a nav bar that reflects sign-in state.
* **Tests:** 37 new backend tests (auth, applications, uploads, status vocabulary, schema/cascade),
  for 49 total.
* **Two real bugs found by testing and fixed** (details in section 9) before this checkpoint.

## 3. Files Created

| File | Purpose |
|---|---|
| `backend/app/core/statuses.py` | `ApplicationStatus` enum + human-readable labels |
| `backend/app/core/security.py` | Argon2 password hashing, JWT create/decode, timing-safe login |
| `backend/app/models/uploaded_document.py` | `UploadedDocument` model |
| `backend/app/services/uploads.py` | File validation (magic-byte check), storage, cleanup |
| `backend/app/services/applications.py` | Create application + files as one unit; status/history helper; ownership-scoped queries |
| `backend/app/schemas/auth.py` | Register/login/me request+response models |
| `backend/app/schemas/application.py` | Application list/detail response models (incl. status labels) |
| `backend/app/api/deps.py` | `get_current_user`, `get_current_student` (JWT auth dependencies) |
| `backend/app/api/routes/auth.py` | `/auth/register`, `/auth/login`, `/auth/me` |
| `backend/app/api/routes/applications.py` | `/applications` (submit, list, detail) |
| `backend/app/db/seed_students.py` | 12 simulated student records (idempotent) |
| `backend/alembic/versions/*_add_uploaded_documents.py` | Migration: `uploaded_documents` table only |
| `backend/tests/test_auth.py`, `test_applications.py`, `test_uploads.py`, `test_statuses.py` | New tests |
| `frontend/lib/auth.js` | Token storage (localStorage) |
| `frontend/lib/status.js` | Status → CSS class mapping for the dashboard/detail pills |
| `frontend/app/nav-bar.js` | Sign-in-aware navigation, shared by the root layout |
| `frontend/app/register/page.js`, `login/page.js` | Auth forms |
| `frontend/app/dashboard/page.js` | Application list |
| `frontend/app/apply/page.js` | New-application form with file picker |
| `frontend/app/applications/[id]/page.js` | Application detail: status timeline + files |

## 4. Files Modified

| File | Change |
|---|---|
| `backend/app/core/config.py` | Added `secret_key` (validated: rejects the placeholder / anything under 32 chars), `jwt_algorithm`, `access_token_expire_minutes`, `upload_dir`, `max_upload_mb` |
| `backend/.env.example` | Added `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `UPLOAD_DIR`, `MAX_UPLOAD_MB` |
| `backend/requirements.txt` | Added PyJWT, argon2-cffi, python-multipart, email-validator |
| `backend/app/models/application.py` | Added `document_type`, `documents`, `history` relationships (cascading delete for the two child tables) |
| `backend/app/models/__init__.py` | Registered `UploadedDocument` |
| `backend/app/main.py` | Registered `auth` and `applications` routers; version bumped to 0.2.0 |
| `backend/tests/conftest.py` | Rebuilt: fixtures for an isolated per-test DB session + temp upload dir wired into the FastAPI app, a registered-student fixture, sample PDF/PNG bytes |
| `backend/tests/test_schema.py` | Added `uploaded_documents` to the expected-tables set and two tests (cascade delete, size constraint) |
| `frontend/app/page.js` | Eyebrow text updated; added a "Student portal" section linking to Register/Sign in |
| `frontend/app/layout.js` | Renders `<NavBar />` above page content |
| `frontend/app/globals.css` | Added styles for the nav bar, forms, application table, status pills, timeline |
| `frontend/lib/api.js` | Added `apiGet(..., {auth})`, `apiPostForm`; see section 9 for the 401-handling fix |
| `README.md`, `docs/PROJECT_CONTEXT.md` | Updated for Phase 2 (see git-style diff in the repo; not repeated here) |

## 5. Current Project Structure

```
sdp-portal/
├── PHASE_1_STATUS.md
├── PHASE_2_STATUS.md
├── docs/PROJECT_CONTEXT.md
├── backend/
│   ├── alembic/versions/
│   │   ├── 20260920_10866ea4850c_initial_schema.py
│   │   └── <ts>_4f0afcfbe2f6_add_uploaded_documents.py
│   ├── app/
│   │   ├── main.py
│   │   ├── core/{config,statuses,security}.py
│   │   ├── db/{base,session,seed,seed_students}.py
│   │   ├── models/{user,student,document_type,application,uploaded_document,transaction}.py
│   │   ├── services/{uploads,applications}.py
│   │   ├── schemas/{document_type,auth,application}.py
│   │   └── api/{deps.py, routes/{health,document_types,auth,applications}.py}
│   └── tests/{conftest,test_api,test_schema,test_auth,test_applications,test_uploads,test_statuses}.py
└── frontend/
    ├── lib/{api,auth,status}.js
    └── app/
        ├── {layout,page,nav-bar,globals.css}
        ├── register/, login/, dashboard/, apply/
        └── applications/[id]/
```

## 6. Database Changes

Migration `4f0afcfbe2f6` ("add uploaded documents"), on top of Phase 1's `10866ea4850c`. Verified:
upgrade from the Phase 1 database, downgrade one step, upgrade again, and upgrade on a brand-new
empty database (all in the clean-room rebuild, section 9).

| Table | Change |
|---|---|
| `uploaded_documents` (new) | id, application_id (FK → applications, CASCADE), original_filename, stored_path, content_type, size_bytes (> 0), uploaded_at |

No Phase 1 table's columns changed. `applications`, `students`, `document_types`, `users`,
`transactions` are exactly as Phase 1 left them.

Seed data (via `python -m app.db.seed_students`, idempotent): 12 simulated students across 5
departments, with varied CGPA, backlog counts and fee status, `user_id` left `NULL` until
registration links one. Not real KLE Tech data — see `docs/PROJECT_CONTEXT.md`.

## 7. APIs / Endpoints Added

| Method | Endpoint | Purpose | Status |
|---|---|---|---|
| POST | `/api/auth/register` | Link a login to an existing (simulated) student record by USN; returns a token | Working, tested |
| POST | `/api/auth/login` | Email + password → token | Working, tested |
| GET | `/api/auth/me` | Signed-in user + their student record | Working, tested |
| POST | `/api/applications` | Submit an application (multipart: document_type_id + optional files) | Working, tested |
| GET | `/api/applications` | List the signed-in student's applications | Working, tested |
| GET | `/api/applications/{id}` | One application's detail, only if it belongs to the caller | Working, tested |

Phase 1 endpoints (`/api/health`, `/api/health/db`, `/api/document-types`) are unchanged.

## 8. Features Currently Working

* A student registers against a seeded USN, is issued a token, and can sign in again later.
* Wrong password / unknown email / unknown USN / duplicate USN / duplicate email are all rejected
  with clear, correct-status-code responses, and the login failure message is identical whether
  the email doesn't exist or the password is wrong (no user enumeration via timing or message).
* A signed-in student submits an application with 0–5 files; only PDF/JPG/PNG are accepted, checked
  by file content; oversized files are rejected; if anything fails, nothing is partially saved (no
  orphan application row, no orphan file on disk).
* A student sees only their own applications and cannot read another student's application (404,
  not 403, so existence isn't leaked).
* The dashboard, apply form, and detail page all work through real browser interaction (clicks,
  file picker, form submit), not just direct API calls.
* An admin-role account (created directly in the DB; there's no admin UI yet) is correctly refused
  by the student-only endpoints.

## 9. Testing Performed

| Test | Result | Notes |
|---|---|---|
| `pytest` (49 tests total: 12 from Phase 1 + 37 new) | 49 passed | Real PostgreSQL 16; every test rolls back its DB writes; uploads go to a temp dir |
| Migration: Phase-1 DB → upgrade → downgrade → upgrade; and on a brand-new empty DB | Pass | |
| Seed scripts run twice each | Pass | Idempotent |
| Live server, `curl` walk-through (register/me/login/document-types/submit-with-real-file/list/reject-fake-file) | Pass | Manual test data cleaned up afterwards |
| Headless-browser end-to-end: register → dashboard → apply with a real PDF (client-side navigation throughout) → detail page → dashboard → sign out | Pass | No console/page errors |
| Headless-browser: wrong-password login and unknown-USN register show the inline error message | Pass | Screenshots inspected |
| **Clean-room rebuild**: fresh copy of only the files a `git` checkout would contain (no `.venv`, `node_modules`, `.env`, caches), brand-new database/role with a password containing `%` and `:`, followed the README literally end to end (venv, install, `.env`, generate `SECRET_KEY`, migrate, both seeds, `pytest`, `npm install`, `npm run build`, then the full browser walk-through against the live rebuilt servers) | Pass | 49/49 tests; full browser flow succeeded; DB and role dropped afterwards |
| Manual + automated database state checked before and after every run | Pass | No leftover test rows in the working database |

**Two real bugs were found during this testing and are fixed in this checkpoint (not left as known
issues):**

1. **Nav bar showed "Sign in / Register" right after a successful register/login**, until a full
   page reload. Cause: the nav bar lives in the root layout, which client-side navigation
   (`router.push`) does not remount, so its one-time `useEffect` never re-read the token. Fix:
   `frontend/app/nav-bar.js` now re-checks the token on every route change via `usePathname()`.
   Verified with a test that only uses in-app link clicks (no `page.goto`), which reproduced the
   bug before the fix and passes after it.
2. **A failed login or register (expected 401, e.g. wrong password) was treated as an expired
   session**, clearing the token and force-navigating to `/login` instead of showing the actual
   error on the form. Cause: the shared response handler in `frontend/lib/api.js` redirected on any
   401. Fix: the redirect now only fires for calls that actually sent a bearer token
   (`/auth/me`, applications); `/auth/login` and `/auth/register` always show their error inline.
   Verified with a browser test asserting the error text appears on the login and register forms.

**Not tested because:**
* Windows and macOS (same limitation as Phase 1; only Ubuntu was used).
* `npm run dev` (development server) — only the production build/start was run.
* Concurrent registration races on the same USN/email (the code handles this with a database
  `IntegrityError` catch, but it was not exercised with actual concurrent requests).
* Token behaviour across a browser refresh/new tab (localStorage persistence itself is standard
  browser behaviour and wasn't separately re-verified here).

## 10. Known Issues

* `updated_at` on `applications` still only updates via the ORM (unchanged from Phase 1).
* No password-reset or email-verification flow (out of scope for a student SDP portal; not
  requested).
* No rate limiting on `/auth/login` (brute-force protection); acceptable for a course project but
  worth naming if asked about production-readiness.
* The frontend's allowed-extension list (`frontend/app/apply/page.js`) is a client-side
  pre-check only, for a faster error message; the backend's content-based check
  (`backend/app/services/uploads.py`) is the actual authority and cannot be bypassed by editing the
  frontend.
* `frontend/lib/status.js` duplicates the "done / rejected" grouping from
  `backend/app/core/statuses.py` by hand (different languages, so it can't share the enum). If the
  status list changes, both files need updating — noted here for Phase 3+.
* Pytest still prints the same 2 harmless Starlette/anyio deprecation warnings noted in Phase 1.

## 11. Important Decisions

1. **Auth is stateless JWT via `Authorization: Bearer`**, token stored in the browser's
   `localStorage` on the frontend. This is a reasonable choice for a student project; a production
   app would more likely use an httpOnly cookie set by the server. Documented in `lib/auth.js`.
2. **Student matching:** registration requires an existing simulated student record (matched by
   USN); a student cannot self-report CGPA/backlogs/department. This was the default proposed at
   the end of Phase 1 (not overridden), so it's what was built.
3. **Status vocabulary:** the 10-value list in section 6/9 above was chosen (also the Phase-1
   default) to cover every stage through Phase 7 without needing another migration later. Only
   `SUBMITTED` is used by Phase 2 itself.
4. **Uploads:** PDF/JPG/PNG, 5 MB each, 5 files per application (Phase-1 defaults, not overridden).
   Validated by content, not extension or browser-supplied MIME type, and stored with randomised
   filenames outside the served path — both are standard practice against disguised/malicious
   uploads and path traversal, not something the brief asked for specifically.
5. **`create_application` is one unit of work**: the application row, its first history row, and
   every file are committed together, or none are (with any already-written files deleted on
   failure). This avoids "phantom" applications with missing files, which matters once Phase 3
   starts reading application state for OCR/eligibility.
6. **Nothing in Phase 1 was rebuilt without reason.** The two fixes in section 9 are the only
   changes to Phase-1-era files beyond what Phase 2 required (adding relationships/routers); both
   are documented there with cause and verification, per the phase-handoff rule.
7. **No admin functionality yet** (no admin UI, no admin endpoints beyond what's needed to test
   role enforcement) — that's Phase 6/7, not Phase 2.

## 12. Environment / Setup Requirements

Same as Phase 1 (Python 3.11+, Node 20.9+, PostgreSQL 15+), plus:
* `backend/.env` needs a real `SECRET_KEY` (see README) — a missing or placeholder value now fails
  fast with a clear error instead of starting insecurely.
* Run `python -m app.db.seed_students` once, in addition to `python -m app.db.seed`, to have any
  USN available to register against.

## 13. How to Run This Phase

```bash
# Backend
cd backend
source .venv/bin/activate          # after the Phase 1 venv/install steps
alembic upgrade head               # applies the Phase 2 migration on top of Phase 1
python -m app.db.seed
python -m app.db.seed_students     # NEW: simulated students to register against
pytest                             # expect: 49 passed
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> → Register with a seeded USN (e.g. `SIM23CSE001`) → you land on the
dashboard → New application → pick a document type, optionally attach a PDF/JPG/PNG → Submit → you
land on the application's status page. Dashboard lists it with a "Submitted" pill.

## 14. What Is NOT Implemented Yet

OCR, rule-based eligibility, sandbox payment (Phase 3), ML datasets (Phase 4), the three ML
components (Phase 5), admin dashboard (Phase 6), admin review/verification/document
generation/live-tracking UI (Phase 7 — the status history model already supports it), integration
testing (Phase 8). No admin login/role UI. No password reset.

## 15. NEXT PHASE

* **Phase 3 — OCR + Eligibility + Payment.**
* To implement: OCR extraction from uploaded documents (store extracted fields); rule-based
  eligibility check against predefined conditions (academic condition, fee status, required
  documents — mark ELIGIBLE / NOT_ELIGIBLE); sandbox/mock payment linked to an application
  (PAYMENT_PENDING → PAYMENT_COMPLETED).
* Expected changes: a new OCR-results table and an eligibility-rules module in
  `backend/app/services/`; new routes under `/api/applications/{id}/...` (or similar) for
  triggering OCR/eligibility/payment; `transactions` table gets real use (it already exists from
  Phase 1); frontend gets an eligibility/payment step in the application flow.
* Depends on: `uploaded_documents` (Phase 2, for OCR input), `application_status_history` /
  `set_status()` (Phase 1/2, for recording each new stage), `students` (Phase 1, for eligibility
  conditions like CGPA/backlogs/fee_status), `transactions` (Phase 1, unused until now).
* Decisions needed before/at the start of Phase 3: (a) the exact rule-based eligibility conditions
  per document type (the brief lists "academic condition, fee status, required documents" but not
  specific thresholds), (b) which Python OCR library to use and whether uploaded images/PDFs in
  this dev environment are realistic enough to OCR meaningfully or whether Phase 4's synthetic data
  approach should extend to sample documents too, (c) mock payment amounts per document type
  (currently undefined — `transactions.amount` has no source of truth yet).

## 16. HANDOFF INSTRUCTIONS

1. Unzip `PHASE_2_COMPLETE.zip` (it supersedes `PHASE_1_COMPLETE.zip`; both status files are kept
   for history). Follow section 13 and confirm `pytest` shows 49 passed and the full
   register → apply → status flow works in a browser before writing new code.
2. Re-read `docs/PROJECT_CONTEXT.md`, updated with the Phase 2 decisions section.
3. Add new tables/columns only through new Alembic migrations, as in Phase 1. Do not edit the two
   existing migration files.
4. Reuse `services/applications.set_status()` for every status change so
   `application_status_history` stays authoritative — don't set `Application.status` directly.
5. Keep `backend/.env`, `frontend/.env.local`, and `backend/uploads/` out of Git and out of ZIPs
   (already in `.gitignore`); add any new setting to `.env.example` with a placeholder.
6. If you change the status vocabulary, update both `backend/app/core/statuses.py` and
   `frontend/lib/status.js` (see Known Issues #5 above).
7. Record new decisions in `PHASE_3_STATUS.md`; don't rebuild working Phase 1/2 pieces without a
   stated reason, per the phase-handoff rule.
