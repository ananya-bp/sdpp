# University Document Portal

An AI-enhanced academic-document application portal (transcripts, migration certificates, duplicate
grade cards, provisional degree certificates) - SDP (Course 20ECSW401), Team 27.

A student registers, submits an application with supporting documents, and the portal **automatically**
reads the documents (OCR), checks eligibility with deterministic rules, shows the fee, and lets the student
make a **sandbox** payment while following a status timeline.

> **Prototype limitations - please read**
> * All student records and applications are **simulated**. No real university data is used.
> * Payment is a **mock/sandbox**: no gateway is contacted and no money moves. The student chooses
>   "success" or "failure" to simulate the gateway's answer.
> * Eligibility rules and the fee schedule are **placeholder values**, not official policy.
> * This is a student project, **not** an official university service.
> * The admin side (review, dashboard, document generation) is not built yet; after payment an application
>   simply stays at "Payment completed". The three ML components (forecasting, risk scoring, anomaly detection)
>   exist as admin-only API endpoints and are not part of the student screens.

**Stack:** Next.js (React, JavaScript) - FastAPI - PostgreSQL - SQLAlchemy + Alembic - Tesseract OCR - scikit-learn / LightGBM.

---

## 1. Run with Docker Desktop (Windows)

### Prerequisites
* **Windows 10/11** with **Docker Desktop** installed and running (WSL 2 backend is the default; wait until the
  whale icon says "Engine running"). Check in PowerShell: `docker --version` and `docker compose version`.
* Free ports **3000** (frontend) and **8000** (backend). Change them in `.env` if needed (see below).
* Nothing else: PostgreSQL, Python, Node.js, Tesseract and Poppler all run **inside** the containers.

### Step 1 - Create `.env` (secrets)
Open PowerShell **in the project folder** (the one containing `compose.yaml`) and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1
```

This copies `.env.example` to `.env` and fills in a random `POSTGRES_PASSWORD` and `SECRET_KEY`. (Manual
alternative: `Copy-Item .env.example .env`, then replace both `CHANGE_ME...` values yourself; `SECRET_KEY` must be
random and 32+ characters, `POSTGRES_PASSWORD` letters/digits only.) `.env` is git-ignored and never copied into images.

| Variable | Meaning | Default |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_DB` | Database user / name inside the `db` container | `sdp_user` / `sdp_portal` |
| `POSTGRES_PASSWORD` | Database password (letters and digits only) | *you set it* |
| `SECRET_KEY` | Signs login tokens (32+ random characters) | *you set it* |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Login lifetime | `60` |
| `MAX_UPLOAD_MB` | Max size per uploaded file | `5` |
| `CORS_ORIGINS` | Browser origins allowed to call the API | `http://localhost:3000,http://127.0.0.1:3000` |
| `FRONTEND_PORT` / `BACKEND_PORT` | Ports published on your PC | `3000` / `8000` |
| `NEXT_PUBLIC_API_BASE_URL` | Address **the browser** uses for the API (compiled into the frontend) | `http://localhost:8000` |

### Step 2 - Build and start

```powershell
docker compose up --build -d
docker compose ps
```

The first build downloads images and installs everything (several minutes). Start-up order is automatic:
`db` becomes healthy -> `backend` runs migrations + seeding and becomes healthy -> `frontend` starts.
`docker compose ps` should show all three services `running`/`healthy`.

* Student portal: <http://localhost:3000>
* API documentation (Swagger UI): <http://localhost:8000/docs>
* Health checks (diagnostics only): <http://localhost:8000/api/health> and <http://localhost:8000/api/health/db>

### What happens on every start (migrations and seeding)
`backend/docker-entrypoint.sh` runs, in order: `alembic upgrade head` -> `python -m app.db.seed` (4 document
types) -> `python -m app.db.seed_students` (12 simulated students) -> API server. All steps are **idempotent**: a
restart applies no migration twice and adds only missing seed rows, so records are never duplicated.
Container-to-container, the backend reaches PostgreSQL at host `db` (the Compose service name), not `localhost`.

### Step 3 - Register and sign in as a simulated student
1. Open <http://localhost:3000> and click **Register**.
2. Enter a seeded USN, any email (e.g. `student1@example.com`) and a password of 8+ characters. Registration links
   the login to the **pre-loaded simulated** student record; unknown USNs are rejected.
3. You are signed in and land on the dashboard. Next time use **Sign in**.

Seeded USNs and what they demonstrate (simulated data from `backend/app/db/seed_students.py`):

| USN | Fee status | Backlogs | Expected result |
|---|---|---|---|
| `SIM23CSE001`, `SIM23CSE003`, `SIM23ECE001`, `SIM23EEE002`, `SIM23MEC002`, `SIM23CIV001` | CLEAR | 0 | **Eligible** for every document type |
| `SIM23CSE002`, `SIM23ECE002`, `SIM23MEC001` | CLEAR | 1-2 | Eligible, **except** Provisional Degree Certificate (needs zero backlogs) |
| `SIM23CSE004`, `SIM23EEE001`, `SIM23CIV002` | **DUE** | - | **Not eligible** for any document |

(`SIM23CSE001` is the easiest to use for a first run.)

### Step 4 - Submit an application and watch the automatic flow
1. Click **New application**, choose a document type, and attach a supporting file. A ready-made **simulated**
   sample is included: `samples\sample_document_SIM23CSE001.png` (or `.pdf`). Any clear PDF/JPG/PNG works (max 5 files, 5 MB each).
2. Click **Submit application**. An upload progress bar appears, then you are taken to the application page.
3. Without clicking anything else, the **Progress** panel moves through *Application submitted -> Extracting
   document information -> Checking eligibility*, and the **Status timeline** gains `Documents processed` and then
   `Eligible` (or `Not eligible`) entries. Under *Submitted documents* you see the extracted USN / CGPA-like values / dates.
4. **Eligible:** the fee is shown and **Proceed to sandbox payment** appears. Then choose **Simulate failed payment**
   (a **Retry payment** button appears and the failed attempt stays in the payment table) or **Simulate successful payment**
   (status becomes *Payment completed*). Nothing is ever paid automatically.
5. **Not eligible** (e.g. register `SIM23CSE004`): the reasons are listed and no payment option exists.
6. Reload the page at any time: the saved state is shown and nothing is re-processed (processing is idempotent on the server).

If a file cannot be read (e.g. a corrupt PDF) the page says so, keeps your application and files, **does not run the
eligibility check**, and offers an explicit **Retry document processing** button.

### Logs, stopping, data

```powershell
docker compose logs -f                 # follow all services (Ctrl+C stops following, not the app)
docker compose logs -f backend         # just the backend (migrations, seeding, requests, errors)
docker compose logs db
docker compose ps

docker compose stop                    # stop, keep containers
docker compose down                    # stop and remove containers - database and uploads are KEPT
docker compose up -d                   # start again; add --build after code or NEXT_PUBLIC_API_BASE_URL changes
```

**Preserving data.** The database lives in the named volume `sdp-portal_pgdata` and uploaded documents in
`sdp-portal_uploads`. `docker compose down`, rebuilds and `docker compose up --build` keep both.

**Deliberate reset (deletes ALL demo data - applications, accounts, uploaded files):**

```powershell
docker compose down -v                 # -v removes the two named volumes
docker compose up --build -d           # fresh database: migrations + seeds run again
```

Run the backend tests inside the container (uses the real database, rolls back its writes, uses a temp upload folder):

```powershell
docker compose exec backend python -m pytest -q
```

> **Caveat:** several existing tests register the seeded USNs (e.g. `SIM23CSE001`) and expect them to be unregistered. Run the tests
> on a database where you have not registered those students yet (a fresh start, or after `docker compose down -v`); otherwise they fail with
> `409 This USN already has an account`. The tests themselves roll back and leave no rows behind.

### Troubleshooting
* **`docker compose` cannot connect / "error during connect"** - Docker Desktop is not running. Start it and wait for "Engine running".
* **`required variable POSTGRES_PASSWORD / SECRET_KEY is missing`** - there is no `.env` yet (Step 1).
* **Backend container keeps restarting** - `docker compose logs backend`. Typical causes: `SECRET_KEY` still the placeholder
  or shorter than 32 characters; a `POSTGRES_PASSWORD` changed after the database volume was first created (the old password
  is stored in the volume - either restore the old value or reset with `docker compose down -v`).
* **Port already in use** - set `FRONTEND_PORT` / `BACKEND_PORT` in `.env` (if you change `BACKEND_PORT`, also change
  `NEXT_PUBLIC_API_BASE_URL` to the same port, and add a custom frontend origin to `CORS_ORIGINS` if you change `FRONTEND_PORT`),
  then `docker compose up --build -d`.
* **Pages load but sign-in/registration says "Could not reach the server"** - the browser cannot reach the API address that was
  compiled in. Confirm <http://localhost:8000/api/health> opens, and that `NEXT_PUBLIC_API_BASE_URL` matches it; rebuild after changing it.
* **Browser console shows a CORS error** - open the site at `http://localhost:3000` (or add the origin you use to `CORS_ORIGINS`) and restart the backend.
* **"No student record found for this USN"** - use one of the seeded USNs above (letters are normalised to upper case).
* **OCR shows "Could not be read"** - the file is corrupt or not a genuine PDF/JPG/PNG; upload another and use *Retry document processing*.
* **Shell script errors like `\r: command not found`** - a CRLF checkout of `docker-entrypoint.sh`. The Dockerfile normalises it; if it still occurs, run `docker compose build --no-cache backend`.
* **Slow first build** - normal; later builds reuse cached layers.

---

## 2. What changed in the student portal
* New landing page, navigation that depends on sign-in state, a dashboard (welcome, counts, recent applications),
  a redesigned application form (type cards, drag-and-drop, per-file removal, validation, upload progress) and an application page
  (progress tracker, eligibility result, fee + sandbox payment, documents with OCR results, summary, timeline).
* **Automatic workflow.** New endpoint `POST /api/applications/{id}/process` chains the existing services
  (`run_ocr_for_application` -> `run_eligibility_for_application`), so every status change still goes through `set_status()` and is written
  to `application_status_history`. It is idempotent and serialised per application with a PostgreSQL advisory lock (tabs, refreshes and double
  clicks cannot cause duplicate OCR/eligibility runs); eligibility runs only if OCR succeeded for **every** file; `?retry_ocr=true` is the
  only way to re-run OCR; it never starts a payment. `ApplicationDetail` also exposes `fee_amount` so the UI shows the backend's fee.
* The existing `/ocr`, `/eligibility`, `/payment/*` endpoints and the database schema are unchanged. Eligibility is decided only by the backend.

---

# Appendices

## Appendix A - Tech stack
Next.js (React, JavaScript) · FastAPI (Python) · PostgreSQL · SQLAlchemy 2 + Alembic · pytest

## Appendix B - Manual (non-Docker) setup

Only needed if you do not use Docker. Prerequisites:

| Tool | Version used for testing |
|---|---|
| Python | 3.12 (3.11+ recommended) |
| Node.js | 22 (20.9+ required by Next.js 16) |
| PostgreSQL | 16 (15+ should work) |
| Tesseract OCR | 5.x (`tesseract-ocr` system package) — needed for Phase 3 OCR |
| Poppler | `poppler-utils` system package (provides `pdftoppm`) — needed to OCR PDF uploads |

On Debian/Ubuntu: `sudo apt-get install tesseract-ocr poppler-utils`.

### B1. Create the database (once)
Open `psql` as the PostgreSQL admin user and run (choose your own password):

```sql
CREATE USER sdp_user WITH PASSWORD 'choose_a_password';
CREATE DATABASE sdp_portal OWNER sdp_user;
```

### B2. Backend (FastAPI)
From the project root:

```bash
cd backend
python -m venv .venv

# activate the virtual environment
#   Windows PowerShell:  .venv\Scripts\Activate.ps1
#   macOS / Linux:       source .venv/bin/activate

pip install -r requirements.txt

# create your local config, then edit DATABASE_URL, and set SECRET_KEY (see below)
#   Windows:  copy .env.example .env
#   macOS / Linux:  cp .env.example .env

alembic upgrade head          # create the tables
python -m app.db.seed          # insert the 4 document types (safe to re-run)
python -m app.db.seed_students # insert 12 SIMULATED student records (safe to re-run)
uvicorn app.main:app --reload --port 8000
```

If your password contains special characters, URL-encode them in `DATABASE_URL`
(e.g. `@` becomes `%40`, `%` becomes `%25`, `:` becomes `%3A`).

**`SECRET_KEY`** signs login tokens and must be a random value, not the placeholder. Generate one
and paste it into `backend/.env`:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

* API docs: <http://localhost:8000/docs>
* Health check: <http://localhost:8000/api/health> and <http://localhost:8000/api/health/db>

#### Sign in as a student
Student records are simulated (`python -m app.db.seed_students`); there is no real KLE Tech data.
Register a login for one of the seeded USNs (`SIM23CSE001` … `SIM23CIV002`, see
`app/db/seed_students.py` for the full list) at `/register` with any email and an 8+ character
password, then sign in at `/login`.

### B3. Frontend (Next.js)
In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. If your backend is not at `http://localhost:8000`, copy
`frontend/.env.example` to `frontend/.env.local` and change the URL.

From the home page, **Register** with a seeded USN, then from the dashboard start a **New
application**, optionally attach a PDF/JPG/PNG, and submit. You'll land on the application's
status page; **Dashboard** lists all of your applications.

#### How an application is processed
After a student submits an application, OCR and the eligibility check run automatically (see the
main guide above). The individual endpoints `POST /api/applications/{id}/ocr` and `/eligibility` still
exist for API users; the portal uses `POST /api/applications/{id}/process`.

### B4. Run the backend tests
With the backend virtual environment active and the database migrated and seeded:

```bash
cd backend
pytest
```

Expected: `106 passed`. The tests use the database from `backend/.env`; each test runs in a
transaction that is rolled back afterwards, and uploaded test files go to a temporary folder, so
running the suite never touches your real data or your real `backend/uploads/` folder. The OCR
tests run the real Tesseract/poppler pipeline against generated sample images/PDFs (no mocking),
so `tesseract-ocr` and `poppler-utils` must be installed for the full suite to pass.

## Appendix C - Project structure
```
backend/
  app/
    main.py              FastAPI app + CORS
    core/                settings, application-status vocabulary, JWT/password helpers
    db/                  base, session, seed scripts (document types, simulated students)
    models/              SQLAlchemy models (8 tables)
    services/            upload validation/storage, application creation, OCR, eligibility, payments
    api/routes/          health, document_types, auth, applications (incl. /ocr, /eligibility, /payment/*)
    api/deps.py           get_current_user / get_current_student (JWT auth)
    schemas/             Pydantic request/response models
  alembic/               migrations (versions/ holds Phase 1 + 2 + 3 schema changes)
  tests/                 pytest suite (auth, applications, uploads, statuses, schema, ocr, eligibility, payments, forecast, risk, anomaly, ml_services)
  requirements.txt  .env.example
frontend/
  app/
    page.js               home / connectivity status
    register/, login/      auth pages
    dashboard/             student's application list
    apply/                 new application form (with file upload)
    applications/[id]/     one application's status, files, OCR/eligibility/payment actions
    nav-bar.js              sign-in-aware navigation
  lib/                    api.js (fetch + auth-aware 401 handling), auth.js (token storage), status.js
  package.json  .env.example
ml/
  config.py               every data-generation assumption, in one place
  simulate.py             the world simulator (students -> applications -> payments -> queue)
  features.py             shared, reusable feature helpers
  prepare.py              raw tables -> the 3 model-ready datasets
  validate_datasets.py    integrity / leakage / sanity checks
  make_datasets.py         `python -m ml.make_datasets` - runs all of the above
  make_figures.py         optional sanity-check plots
  forecasting.py          Phase 5.1: demand & TAT forecasting (LightGBM) - train + predict_demand()/predict_tat()
  risk_scoring.py         Phase 5.2: manual-review risk (Logistic Regression) - train + predict_risk()
  score_dev_seed.py       Phase 5.2: scores the 12 seeded students
  anomaly.py              Phase 5.3: payment anomaly detection (Isolation Forest + amount rule) - train + predict_anomaly()
  models/                 saved artifacts (*.joblib) + *_metrics.json for the three models
  data/                   generated CSVs (raw, labels, processed) + dataset_summary.json
  tests/                  pytest suite
docs/PROJECT_CONTEXT.md  scope, boundaries and data rules for future phases
docs/DATA_DICTIONARY.md  Phase 4: every dataset, column, assumption and validation check
PHASE_1_STATUS.md, PHASE_2_STATUS.md, PHASE_3_STATUS.md  exact state of each checkpoint
```

## Appendix D - ML datasets (Phase 4)

Phase 4 is a separate, standalone subproject under `ml/` — it does not touch the running
application, and generates only **simulated** data (no real KLE Tech records). See
`ml/README.md` for setup/run/test commands and `docs/DATA_DICTIONARY.md` for what every file and
column means.

## Appendix E - ML models and endpoints (Phase 5)

Three ML components, all trained on the **simulated** Phase 4 data and used as admin decision support only (they never
decide eligibility, reject payments or change a status). Train (from the project root, ~seconds each):
`python -m ml.forecasting`, `python -m ml.risk_scoring`, `python -m ml.anomaly`. Tests: `python -m pytest ml -q`.
Admin-only endpoints (each backed by `backend/app/services/ml_services.py`): `GET /api/forecast/demand`,
`POST /api/forecast/tat`, `POST /api/risk/score`, `POST /api/anomaly/score`. Details and metrics: `PHASE_5_STATUS.md`,
`PHASE_5_1_STATUS.md`, `PHASE_5_2_STATUS.md`, `PHASE_5_3_STATUS.md`. Install the ML libraries via `backend/requirements.txt`.

## Appendix F - Troubleshooting for the manual setup
* `password authentication failed`: the user/password in `backend/.env` does not match what you
  created in step 1.
* Frontend cards say "Failed": the backend is not running, or `NEXT_PUBLIC_API_BASE_URL` points to
  the wrong address. If the browser console mentions CORS, add your frontend URL to `CORS_ORIGINS`
  in `backend/.env` (comma-separated) and restart the backend.
* PowerShell blocks `Activate.ps1`: run `Set-ExecutionPolicy -Scope Process Bypass` in that window first.
* Backend won't start / `pydantic_core.ValidationError` mentioning `secret_key`: set a real
  `SECRET_KEY` in `backend/.env` (see the command above); the placeholder is rejected on purpose.
* Register says "No student record found for this USN": run
  `python -m app.db.seed_students` and use one of the seeded USNs.
* Upload rejected with a "does not match its ... extension" error: the file's actual content
  doesn't match its extension (the check reads the file's bytes, not just its name).
* OCR step fails / `tesseract is not installed` or similar: install `tesseract-ocr` and
  `poppler-utils` (see Prerequisites above) and restart the backend.
