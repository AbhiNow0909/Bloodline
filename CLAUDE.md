# CLAUDE.md — Bloodline

This file is the source of truth for how Bloodline is built. Read it fully at the start of every session, follow the workflow rules exactly, and keep the **Progress** section up to date.

---

## 1. What Bloodline is

Bloodline is a personal, family-scale web app that:

1. Accepts lab reports (blood/urine panels) as **digitally generated PDFs** (e.g. Thyrocare reports issued via Healthcare OnTime).
2. Extracts the text layer, structures it into metrics with an LLM, and asks the uploader to **review and confirm** the values before saving.
3. Stores each family member's results as a longitudinal history in Postgres.
4. Shows history and **per-metric trend charts** with the reference range drawn as a shaded band.
5. Answers **natural-language questions** about a family member's data through a tool-calling AI agent, with semantic search over report text (RAG).
6. **Flags and explains** out-of-range values and notable trends. It does **not** diagnose.

Users: a handful of family members with manually created accounts. It is also a portfolio project, so code quality, tests, Docker, and CI/CD matter as much as features.

---

## 2. Guiding principles (non-negotiable)

1. **Flag and explain, never diagnose.** The app may say a value is outside its reference range, describe what the marker generally relates to, show the trend, and suggest discussing it with a doctor. It must never state or imply a diagnosis ("you have X"), and never recommend medication or dosing. Every AI-generated health explanation shows a short "not medical advice — discuss with your doctor" note.
2. **Privacy by design.**
   - Never send patient names, addresses, phone numbers, barcodes, or referring-doctor names to any LLM. Parse identity/header fields locally, scrub them from the text before any LLM call, and reattach identity only on our own backend.
   - Never commit real reports or real patient data. `samples/` and any `*.pdf` outside `backend/tests/fixtures/` are gitignored. Test fixtures must be **synthetic** (fake names, fake addresses, made-up values in the same layout).
   - Every data access is scoped by `patient_id` and checked against the logged-in user's access. Vector searches **always** apply a hard `patient_id` filter in SQL; never rely on semantic similarity alone.
   - Secrets live only in environment variables. `.env` is gitignored; `.env.example` is committed with placeholders.
3. **Long-format metrics, never dynamic columns.** One row per metric reading. New biomarkers are new rows, not `ALTER TABLE`. Schema changes go through Alembic migrations only.
4. **Structured data for numbers, RAG for text.** Numeric and trend questions are answered from SQL via tools. Vector search is only for free text (report notes, method text, remarks) and never replaces exact values.
5. **Human in the loop.** Extracted values are saved as `pending_review` and only become part of the history after the user confirms or corrects them.
6. **Tools, not context stuffing.** The query agent calls typed backend tools; it never receives a raw dump of the database.
7. **Free tier only.** No paid services. Stay within Groq, Neon, Render, and Vercel free tiers.
8. **Simplicity over infrastructure.** No Celery, Redis, Kubernetes, reverse proxy, or OCR unless a real requirement appears. If you think one is needed, stop and ask.
9. **Dev/prod parity.** Development happens on Ubuntu. The backend runs in Docker locally exactly as it does on Render.
10. **Tests with every feature.** Each phase adds tests for what it builds. Integration tests use a real Postgres with pgvector, not mocks.

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind CSS | React Router, TanStack Query, Recharts for charts |
| Frontend hosting | Vercel (Hobby, free) | Git-connected; builds from `frontend/` |
| Backend | Python 3.12 + FastAPI | Pydantic v2 for schemas; `uv` for dependency management |
| Backend hosting | Render free web service (Docker) | Sleeps after ~15 min idle, ~1 min cold start; ~512 MB RAM |
| Database | Neon Postgres (free) + `pgvector` | Local dev uses the `pgvector/pgvector:pg16` Docker image |
| ORM / migrations | SQLAlchemy 2.x + Alembic | |
| PDF extraction | `pdfplumber` (primary), `PyMuPDF` (fallback) | Text layer only. **No OCR.** |
| Structuring LLM | `openai/gpt-oss-20b` via Groq | Raw scrubbed text → strict JSON |
| Query agent LLM | `openai/gpt-oss-120b` via Groq | Tool calling |
| LLM client | Groq Python SDK (OpenAI-compatible) | Retry with exponential backoff + jitter on 429/5xx |
| Embeddings | `BAAI/bge-small-en-v1.5` (384-dim), run locally | Prefer **`fastembed`** (ONNX, no PyTorch) to fit Render's memory limit; `sentence-transformers` is acceptable locally if memory is not an issue |
| Background work | FastAPI `BackgroundTasks` | No worker service, no queue |
| Auth | JWT (`pyjwt`) + Argon2 password hashing (`pwdlib[argon2]`) | Accounts created manually via a CLI script; no public sign-up |
| Testing | `pytest`, `httpx2` test client; `vitest` for frontend | Real Postgres service in CI |
| Lint / format | `ruff` (lint + format), `mypy` (backend); ESLint + Prettier (frontend) | |
| Containers | Docker (multi-stage backend image) + Docker Compose for local dev | Compose runs `api` + `db` only |
| CI/CD | GitHub Actions → GitHub Container Registry (GHCR) → Render deploy hook; Vercel via Git integration | |

Model IDs and SDK APIs change. Before writing integration code, confirm current Groq model IDs and library APIs using up-to-date docs (see Section 9).

---

## 4. Architecture

```
┌──────────────────────────┐
│ React SPA (Vercel)       │
│ upload · review · charts │
│ history · chat           │
└────────────┬─────────────┘
             │ HTTPS + JWT
┌────────────▼─────────────────────────────────────────────┐
│ FastAPI (Docker on Render)                               │
│                                                          │
│  /auth   /patients   /reports   /metrics   /chat         │
│                                                          │
│  Ingestion pipeline (BackgroundTasks):                   │
│   PDF → pdfplumber text → local header parse             │
│       → PII scrub → gpt-oss-20b structuring (JSON)       │
│       → validate + normalize (metric dictionary, units,  │
│         sex-specific reference range) → pending_review   │
│       → user confirms → metrics rows + text chunks       │
│       → local embeddings (bge-small) → pgvector          │
│                                                          │
│  Query agent: gpt-oss-120b + typed tools                 │
│   (SQL tools for numbers, vector search for text)        │
└───────┬───────────────────────────────┬──────────────────┘
        │                               │
┌───────▼───────────────────┐   ┌───────▼──────────────────┐
│ Neon Postgres + pgvector  │   │ Groq API                 │
│ relational + JSONB +      │   │ gpt-oss-20b (structuring)│
│ vector in one database    │   │ gpt-oss-120b (agent)     │
└───────────────────────────┘   └──────────────────────────┘
```

### 4.1 Ingestion pipeline (detail)

1. **Upload**: `POST /patients/{id}/reports` accepts a PDF (size limit, PDF MIME check). Store the file bytes' SHA-256 to reject duplicate uploads. Create a `reports` row with status `processing`.
2. **Text extraction**: `pdfplumber` page by page. If a page yields no text layer, mark the report `failed` with the reason "scanned/image PDF not supported yet". Do not add OCR.
3. **Local header parsing** (regex, no LLM): lab name, sample collected date/time, sample type, patient sex and age as printed (e.g. `(56Y/M)`). These are stored on the report. The printed patient name is only used to warn the user if it does not match the selected patient; it is never sent to an LLM.
4. **PII scrub**: remove name, address, phone numbers, emails, barcodes, and doctor names/signatures from the text. Drop boilerplate pages (cover page, "Conditions of Reporting", marketing).
5. **Structuring** (`gpt-oss-20b`, JSON output validated by Pydantic): for each test, return `raw_name`, `value` (numeric or text), `unit`, `reference_text`, `reference_low`, `reference_high`, `panel` (e.g. "DIABETES SCREEN (URINE)"), `method`, `technology`, `sample_type`. When the report prints sex-specific ranges (e.g. `Male: 39 - 259`, `Female: 28 - 217`), select the range matching the patient's recorded sex; keep the full `reference_text` too. `Less than 25` → `reference_high = 25`, `reference_low = null`.
6. **Validate and normalize**: numeric values parse cleanly; units recognized; map `raw_name` → canonical metric via `metric_dictionary` (aliases such as `HGB`, `Hb`, `Haemoglobin`). Unknown names are kept with `canonical_metric_id = null` and surfaced in review. Convert to the canonical unit when a conversion is known, preserving the original value and unit.
7. **Review**: report status `pending_review`. The frontend shows extracted rows next to the original PDF; the user edits and confirms.
8. **Commit**: on confirm, write `metrics` rows, compute flags, chunk the (scrubbed) report text, embed locally, store chunks. Status `confirmed`.

### 4.2 Data model (long format)

- `users` — id, email, password_hash, display_name, created_at
- `patients` — id, display_name, sex, date_of_birth (nullable), created_at
- `user_patient_access` — user_id, patient_id, role (`owner` | `viewer`). One user can manage several family members.
- `reports` — id, patient_id, lab_name, collected_at, file_sha256, file_path/blob, status (`processing` | `pending_review` | `confirmed` | `failed`), failure_reason, raw_extraction (JSONB), created_at
- `metric_dictionary` — id, canonical_name, category, canonical_unit, aliases (text[]), description, loinc_code (nullable)
- `metrics` — id, patient_id, report_id, canonical_metric_id (nullable), raw_name, value_numeric, value_text, unit, value_canonical, unit_canonical, reference_low, reference_high, reference_text, flag (`low` | `normal` | `high` | `unknown`), sample_type, method, collected_at
  - indexes on `(patient_id, canonical_metric_id, collected_at)`
- `report_chunks` — id, patient_id, report_id, chunk_index, content, embedding `vector(384)`
  - HNSW index on `embedding`; every query filters `WHERE patient_id = :pid`

Seed `metric_dictionary` with common panels (CBC, lipid profile, liver, kidney, thyroid, HbA1c/glucose, iron studies incl. ferritin, vitamins, urine albumin/creatinine/UACR) via a migration or seed script.

### 4.3 Query agent

- Endpoint `POST /patients/{id}/chat` (access-checked). Resolve the patient server-side; the model sees a pseudonymous label ("the patient"), never a name.
- Model: `gpt-oss-120b` with tool calling. Max tool-call iterations per question (e.g. 5).
- Tools (all implicitly scoped to the current patient_id, which the model cannot change):
  - `list_available_metrics()`
  - `get_metric_history(metric, start_date?, end_date?)`
  - `get_latest_values(metrics?)`
  - `get_out_of_range(since?)`
  - `compare_reports(report_a?, report_b?)`
  - `get_trend_summary(metric)` — deterministic stats computed in Python (change %, slope, direction), not by the LLM
  - `search_report_text(query, k)` — vector search over `report_chunks`
- System prompt enforces Principle 1 (no diagnosis) and requires answers to cite which report dates the numbers came from.
- Rate limits: retry with exponential backoff + jitter on 429; return a friendly "busy, try again" message if retries are exhausted.

### 4.4 Flagging and trends (deterministic)

- Flag each value against its reference range.
- Trend alerts computed in Python: e.g. value moved more than a configurable % across the last N reports while still in range, or crossed a range boundary. The LLM only phrases explanations; it does not compute them.

---

## 5. Repository layout

```
bloodline/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/            # routers
│   │   ├── services/
│   │   │   ├── extraction/ # pdf text, header parse, pii scrub
│   │   │   ├── structuring/
│   │   │   ├── normalization/
│   │   │   ├── embeddings/
│   │   │   ├── agent/      # tools + orchestrator
│   │   │   └── llm/        # groq client, retry
│   │   └── cli/            # create-user, seed
│   └── tests/
│       └── fixtures/       # SYNTHETIC reports only
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
└── .github/
    └── workflows/
        ├── ci.yml
        └── deploy.yml
```

### Environment variables (`.env.example`)

```
DATABASE_URL=postgresql+psycopg://bloodline:bloodline@localhost:5432/bloodline
GROQ_API_KEY=
STRUCTURING_MODEL=openai/gpt-oss-20b
AGENT_MODEL=openai/gpt-oss-120b
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
JWT_SECRET=
JWT_EXPIRE_MINUTES=1440
CORS_ORIGINS=http://localhost:5173
MAX_UPLOAD_MB=10
VITE_API_BASE_URL=http://localhost:8000
```

---

## 6. Workflow rules (read carefully)

The project is built **one phase at a time**. The user commits and pushes every phase manually.

1. **Never run** `git add`, `git commit`, `git push`, `git tag`, `git rebase`, `git reset`, or any history-changing git command, and never commit/push through any git or GitHub MCP tool. Read-only git commands (`git status`, `git diff`, `git log`) are fine.
2. Work on **exactly one phase** at a time, in order. Do not start the next phase until the user says so (e.g. "committed", "next phase").
3. **At the start of a phase**: restate the phase goal and a short plan of files you will create/change. If something in this file is ambiguous or seems wrong, ask before building.
4. **During a phase**: keep changes scoped to that phase. No drive-by refactors of unrelated code.
5. **At the end of a phase**, before stopping:
   - Run the relevant checks (tests, `ruff`, `mypy`, frontend lint/build, `docker compose build` where applicable) and report results honestly, including failures.
   - Update the **Progress** section of this file (tick the phase, add notes/decisions).
   - Output a phase summary: what was built, files changed, how to verify manually, and any follow-ups.
   - Propose a **Conventional Commit** message (e.g. `feat(extraction): add pdf text extraction and header parsing`) and list the files to stage.
   - Then **stop and wait**.
6. If a decision in this file needs to change (new dependency, different service, schema change), explain why and wait for approval, then record the decision in the **Decision log**.
7. Never paste secrets into code, logs, or this file.

---

## 7. Phased implementation plan

Each phase ends with a manual commit by the user.

### Phase 0 — Repository scaffolding
- Monorepo layout from Section 5, `.gitignore` (Python, Node, `.env`, `samples/`, `*.pdf` except `backend/tests/fixtures/`), `.env.example`, README with project summary and local setup.
- **Done when**: structure exists, README explains how to run things (even if placeholders).
- Commit: `chore: scaffold bloodline monorepo`

### Phase 1 — Backend skeleton + Docker
- FastAPI app with `/health`, settings via `pydantic-settings`, `uv` project, ruff + mypy config.
- Multi-stage `backend/Dockerfile` (slim runtime, non-root user).
- `docker-compose.yml` with `api` and `db` (`pgvector/pgvector:pg16`, named volume, healthcheck).
- **Done when**: `docker compose up` serves `/health` and the API can connect to the DB.
- Commit: `feat(backend): add fastapi skeleton with docker compose`

### Phase 2 — Continuous integration
- `.github/workflows/ci.yml`: ruff, mypy, pytest with a Postgres `pgvector/pgvector:pg16` service container; Docker image build check.
- **Done when**: the workflow is valid and passes on push (user verifies on GitHub).
- Commit: `ci: add lint, type check and test workflow`

### Phase 3 — Database models and migrations
- SQLAlchemy models for Section 4.2, Alembic setup, initial migration (including `CREATE EXTENSION IF NOT EXISTS vector`), seed for `metric_dictionary`.
- Tests: migrations apply cleanly; basic CRUD.
- Commit: `feat(db): add core schema, migrations and metric dictionary seed`

### Phase 4 — Authentication and patients
- Argon2 hashing, JWT login, `get_current_user` dependency, CLI `create-user`, patients CRUD, `user_patient_access` checks on every patient-scoped route.
- Tests: login, access denial across users/patients.
- Commit: `feat(auth): add jwt auth, patients and access control`

### Phase 5 — PDF text extraction, header parsing, PII scrubbing
- `pdfplumber` extraction, boilerplate page filtering, header regexes (dates, sample type, `(56Y/M)`-style age/sex), PII scrubber.
- Create a **synthetic** fixture PDF matching the Thyrocare layout (fake identity, sex-specific ranges, "Less than" ranges, µg/mL units).
- Tests: extraction, header parse, scrubber removes all PII fields.
- Commit: `feat(extraction): add pdf text extraction and pii scrubbing`

### Phase 6 — LLM structuring and normalization
- Groq client wrapper with retry/backoff; `gpt-oss-20b` structuring prompt with strict JSON output validated by Pydantic; sex-specific range selection; unit and name normalization against `metric_dictionary`; flag computation.
- Tests: normalization and range-selection logic with unit tests; LLM call mocked at the client boundary; one optional live test skipped unless `GROQ_API_KEY` is set.
- Commit: `feat(structuring): add groq structuring and metric normalization`

### Phase 7 — Upload, review and confirm API
- Upload endpoint (size/MIME checks, SHA-256 dedupe), `BackgroundTasks` pipeline, status polling, review payload, confirm/correct endpoint writing `metrics` rows.
- Commit: `feat(reports): add upload, review and confirm flow`

### Phase 8 — History and metrics API
- Report list/detail, metric catalog per patient, time series per metric (with reference ranges), latest values, out-of-range list.
- Commit: `feat(metrics): add history and time-series endpoints`

### Phase 9 — Frontend scaffold and auth
- Vite + React + TS + Tailwind, routing, API client, TanStack Query, login page, protected routes, patient switcher. Apply the frontend-design skill.
- Commit: `feat(frontend): scaffold app with auth and patient switcher`

### Phase 10 — Frontend upload and review
- Upload with progress/status polling, review table beside a PDF preview, inline edits, confirm.
- Commit: `feat(frontend): add report upload and review screen`

### Phase 11 — Frontend history and charts
- Report timeline, per-metric Recharts line charts with shaded reference band and flagged points, latest-values dashboard.
- Commit: `feat(frontend): add history dashboard and trend charts`

### Phase 12 — Embeddings and vector search
- Local `bge-small-en-v1.5` via fastembed, chunking of scrubbed report text on confirm, HNSW index, `search_report_text` service with hard `patient_id` filter.
- Tests: a search for patient A never returns patient B's chunks.
- Commit: `feat(rag): add local embeddings and patient-scoped vector search`

### Phase 13 — Query agent
- Tool definitions (Section 4.3), `gpt-oss-120b` orchestrator loop with iteration cap, deterministic trend helpers, no-diagnosis system prompt, `/chat` endpoint.
- Tests: tool functions; orchestrator with a mocked LLM; guardrail prompt present.
- Commit: `feat(agent): add tool-calling query agent`

### Phase 14 — Frontend chat
- Chat panel per patient, streaming or loading state, citations of report dates, disclaimer.
- Commit: `feat(frontend): add patient chat interface`

### Phase 15 — Flags and trend insights
- Deterministic trend alerts (Section 4.4), insights panel on the dashboard, LLM-phrased plain-language explanations with the disclaimer.
- Commit: `feat(insights): add range flags and trend alerts`

### Phase 16 — Deployment (CD)
- `deploy.yml`: on push to `main`, build and push the backend image to GHCR, then trigger the Render deploy hook. Neon setup notes, Vercel project config (`frontend/` root, `VITE_API_BASE_URL`), CORS for the Vercel domain, run Alembic migrations on deploy.
- Document every manual step the user must do in dashboards (Neon, Render, Vercel, GitHub secrets).
- Commit: `ci: add deployment pipeline to ghcr, render and vercel`

### Phase 17 — Hardening and polish
- Rate limiting on login, audit log of data access, database backup script (`pg_dump` to a local encrypted file, documented schedule), error pages, README with architecture diagram and screenshots.
- Commit: `chore: hardening, backups and documentation`

---

## 8. Progress

- [x] Planning and architecture finalized (in a Claude.ai chat)
- [x] Phase 0 — Repository scaffolding
  - Directory skeleton uses `.gitkeep` placeholders; phase-owned files (`docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `package.json`, workflows) are **not** stubbed — they arrive in their phases.
  - `.gitignore` also ignores `uploads/`, `backups/`, `*.dump`, `*.sql.gz` (defensive: patient data at rest) and `.claude/settings.local.json`. Rules verified with `git check-ignore`.
  - `backend/tests/fixtures/README.md` states the synthetic-only rule.
  - Phase 3: delete `backend/alembic/.gitkeep` before `alembic init` (it refuses a non-empty dir). Phase 9: delete `frontend/src/.gitkeep` before scaffolding Vite.
  - Local tooling at time of Phase 0: Docker 29.8 + Compose v5.5 present; `uv`, Python 3.12 and Node not yet installed (needed from Phase 1 / Phase 9).
- [x] Phase 1 — Backend skeleton + Docker
  - FastAPI app factory (`app/main.py`), settings (`app/config.py`, `DATABASE_URL` required, repo-root `.env` read for local runs), sync SQLAlchemy engine + `get_db` session dependency (`app/db.py`), CORS from `CORS_ORIGINS`.
  - `GET /health` runs `SELECT 1`: 200 `{"status":"ok","database":"ok"}`, or 503 `{"status":"error","database":"unreachable"}`. Verified end-to-end, including recovery after a DB restart (`pool_pre_ping`).
  - uv project without a build backend (app is not installed as a package; `pythonpath = ["."]` for pytest). Dev deps in `[dependency-groups] dev`. Ruff (line 100, E/W/F/I/N/B/UP/SIM/C4/S/PT/RUF), mypy `strict` + pydantic plugin.
  - Dockerfile follows uv's official multistage example: `python:3.12-slim-trixie` in both stages, uv pinned `0.12.18`, deps layer cached, code owned by root and run as uid 999 `app`, `${PORT:-8000}` for Render. Image ~296 MB.
  - Compose: `db` (`pgvector/pgvector:pg16`, `pgdata` volume, `pg_isready` healthcheck) and `api` (waits for healthy db, `.env` optional, `DATABASE_URL` forced to the `db` service). Ports bound to 127.0.0.1.
  - Tests (4): health ok, health 503 against a real unreachable engine, CORS parsing, `DATABASE_URL` required.
  - `uv` is not installed on the host yet, so `uv.lock` and checks were run through `ghcr.io/astral-sh/uv:0.12.18-python3.12-trixie-slim` (command in README).
  - Starlette 1.7's `TestClient` warned that `httpx` is deprecated in favour of `httpx2`; switched to `httpx2` in Phase 2 with user approval.
  - Phase 3 follow-up: tests that write data should use a dedicated test database, not the dev `bloodline` DB.
  - Phase 16 follow-up: Neon gives `postgresql://…?sslmode=require`; the scheme must be `postgresql+psycopg://`.
- [x] Phase 2 — Continuous integration
  - `.github/workflows/ci.yml` (push to `main`, pull requests, manual): `backend` job (setup-uv pinned to `0.12.18`, `uv sync --locked`, ruff lint with GitHub annotations, ruff format check, mypy, pytest against a `pgvector/pgvector:pg16` service) and `docker` job (buildx + GHA layer cache, then runs the image against a Postgres service and asserts `/health` = 200 and non-root uid). Jobs run in parallel.
  - `permissions: contents: read`, `persist-credentials: false`, concurrency cancels superseded runs on the same ref. Actions pinned to major tags (checkout v7, setup-buildx v4, build-push v7), except `astral-sh/setup-uv`, which since v8 publishes only immutable exact releases (no `@vN` tags) and is pinned to the v10.2.0 commit SHA. The first push failed on `setup-uv@v10` for this reason; actionlint does not check that tags exist, so verify new action refs with `git ls-remote --tags`.
  - Validated with actionlint 1.7.12 (includes shellcheck); both jobs' steps replayed locally and pass. Passing on GitHub is for the user to confirm after push.
  - Dev test client switched `httpx` → `httpx2` (Starlette 1.7 deprecation); tests pass with `-W error::DeprecationWarning`.
  - Dev machine: installed `uv` 0.12.18 + Python 3.12.14 (in `~/.local`) and nvm 0.40.8 + Node 24.21.0 LTS (in `~/.nvm`); created a local `.env` from `.env.example` with a generated `JWT_SECRET` (`GROQ_API_KEY` still empty).
  - Dev machine: `~/.bashrc` used to source ROS Humble, whose Python 3.10 `PYTHONPATH` broke pytest plugin loading in the 3.12 venv. With the user's approval the ROS/Gazebo/TurtleBot3 lines were removed (backup: `~/.bashrc.bak-ros-2026-09-24`); a fresh login shell has no `PYTHONPATH`, and plain `uv run pytest` passes.
  - Follow-up (optional): Dependabot for `github-actions` + `uv` to keep action tags and the lockfile current.
- [x] Phase 3 — Database models and migrations
  - Models in `app/models/` (`base.py` naming convention + `str→text`, `datetime→timestamptz` type map; `user.py`, `patient.py` (+ `UserPatientAccess`), `report.py` (+ `ReportFile`), `metric.py` (`CanonicalMetric` = `metric_dictionary`, `Metric`), `report_chunk.py`). Allowed values are `Literal` aliases (`Sex`, `AccessRole`, `ReportStatus`, `MetricFlag`) reused for the `CHECK` constraints and for Pydantic schemas later.
  - Beyond Section 4.2: `metrics` and `report_chunks` have a composite FK `(report_id, patient_id) → reports(id, patient_id)`, so the DB rejects rows linking one patient's data to another patient's report. Also: per-patient `UNIQUE(patient_id, file_sha256)`, `CHECK`s for lowercase email, sha256 hex, value present, `reference_low <= reference_high`, `chunk_index >= 0`; `ON DELETE RESTRICT` for dictionary entries in use.
  - Alembic: `alembic.ini` (date-prefixed file names, ruff format+fix post-write hooks, no URL — `env.py` reads `DATABASE_URL` from settings), `env.py` accepts a caller-supplied connection (tests) and sets `compare_server_default=True`. Initial migration `2026_09_24_5eefbab520ce_create_core_schema.py` (autogenerated, hand-edited to `CREATE EXTENSION IF NOT EXISTS vector` first / `DROP EXTENSION` last). HNSW index uses `vector_cosine_ops`.
  - Seed: `app/cli/metric_dictionary.toml` (80 metrics, 10 categories, 175 aliases; ASCII units with `u` for micro; LOINC codes omitted, unverified) validated by Pydantic (`extra="forbid"`, non-blank strings, every name/alias unique case- and whitespace-insensitively) and upserted by `python -m app.cli.seed` (`ON CONFLICT (canonical_name) DO UPDATE`, ids stable). Removing an entry from the TOML does not delete it.
  - Tests (38 total): fresh `<db>_test` database per run (refused on non-local hosts), per-test rolled-back session, API client shares it. Migrations (upgrade, downgrade→upgrade round trip, models-vs-migrations drift), CRUD across all tables, lossless `Decimal`/`timestamptz`/vector round trips, 384-dim enforcement, every `CHECK`/`UNIQUE` asserted by constraint name, cross-patient composite FK, cascades, `RESTRICT`, seed validation and idempotency.
  - CI docker job now also runs `alembic upgrade head`, `alembic check` and the seed (twice) inside the built image against an empty DB.
  - Deps: `alembic` 1.20, `pgvector` 0.5 (no NumPy; returns `list[float]`). Ruff isort treats `alembic` as third-party (local `alembic/` dir).
  - Context7 MCP was installed at local scope for `~` only; re-added at user scope. It is available from the next session (MCP tools load at startup), so Phase 3 docs were checked against upstream sources directly (pgvector-python README/CHANGELOG, Alembic cookbook, SQLAlchemy 2.0 docs).
  - Code review (engineering:code-review) findings, all fixed: drift test was blind to server-default changes (enabled `compare_server_default`); test fixture could create/drop a DB on a remote server (local-host guard, exits with code 2); seed-removal semantics undocumented.
  - Known limitation: Alembic autogenerate never detects `CHECK` constraint changes — write those migrations by hand (noted in README).
  - Follow-ups: **Phase 4** normalize emails (strip + lower) before insert; keep at least one `owner` per patient in app logic. **Phase 5** parse printed times as Asia/Kolkata before storing `timestamptz`; Section 4.1 step 3 fields not in 4.2 (sample type, printed age/sex) need columns via migration or go in `raw_extraction`. **Phase 6** match aliases on normalized exact names (short aliases like `K`, `Na`, `ABG`, `PCT` must never substring-match); `raw_extraction` must contain only scrubbed data. **Phase 7** `metrics.collected_at` is NOT NULL, so confirm must supply a date. **Phase 12** filtered HNSW search can return < k rows; consider pgvector 0.8 `hnsw.iterative_scan` or rely on the `patient_id` index at family scale.
- [x] Phase 4 — Authentication and patients
  - `app/security.py`: Argon2id via `pwdlib` (`PasswordHash.recommended()`: m=64 MiB, t=3, p=4, ~55 ms), `verify_and_update` upgrades outdated hashes on login; HS256 JWTs via a strict `jwt.PyJWT(options={"enforce_minimum_key_length": True})`, claims `sub`/`iat`/`exp` all required, `algorithms=["HS256"]` only.
  - `app/services/users.py`: email normalization (strip + lower), password 12–1024 chars, `create_user`, `authenticate` (unknown email burns one Argon2 verify so timing and response match a wrong password; an unreadable stored hash also counts as a mismatch).
  - `app/api/deps.py`: `DbSession`, `CurrentUser` (`HTTPBearer(auto_error=False)`, 401 + `WWW-Authenticate: Bearer`, deleted users rejected), `get_patient_access` (**404** when the user has no access, identical to a nonexistent id), `require_owner` (403 for viewers).
  - Routes: `POST /auth/login` (JSON body, not OAuth2 form, so no `python-multipart` yet), `GET /auth/me`, `GET/POST /patients`, `GET/PATCH/DELETE /patients/{patient_id}` (creator becomes owner; PATCH/DELETE owner-only; DELETE cascades all data).
  - `app/api/errors.py`: 422 responses drop the submitted `input` (FastAPI's default echoes it — would reflect passwords and patient names).
  - CLI `python -m app.cli.create_user --email … --name …` (prompts twice or `--password-stdin`; never an argument).
  - Settings: `JWT_SECRET` required, `SecretStr`, ≥ 32 chars; `JWT_EXPIRE_MINUTES` default 1440.
  - FastAPI 0.141 keeps included routers nested (`app.routes` holds `_IncludedRouter`s); walk routes with `fastapi.routing.iter_route_contexts(app.routes)`. A test uses it to assert every `{patient_id}` route depends on `get_patient_access` (verified to catch a deliberately unprotected route).
  - pytest config now sets `filterwarnings = ["error::DeprecationWarning"]` (it caught SQLAlchemy's deprecated `Row.tuple()`).
  - Tests: 104 total — token edge cases (expired, wrong secret, `alg=none`, other algorithm, tampered payload, missing claims, non-UUID subject), login/enumeration parity, 401/404/403 access matrix, viewer read-only, validation, no-echo of inputs, CLI via stdin/prompt/errors.
  - CI: each job generates a masked throwaway `JWT_SECRET`; the docker job also creates a user with the CLI inside the image, logs in over HTTP, calls `/auth/me`, and checks unauthenticated `/patients` is 401 (replayed locally end-to-end).
  - Code review (engineering:code-review) findings, both fixed: 422 bodies echoed submitted values (password reflected); a malformed stored hash raised `UnknownHashError` → 500, distinguishable from 401.
  - Context7 still not loaded in this session (needs a Claude Code restart); docs were checked against upstream sources (pwdlib README, PyJWT usage + changelog, FastAPI release notes).
  - Follow-ups: **Sharing** — no way yet to grant another user `viewer`/`owner` access (decide: CLI or UI). **Phase 17** — login rate limiting; token revocation (tokens stay valid until expiry, and there is no password-change endpoint yet). Minor: `create_user` CLI shows a traceback if two runs race on the same email (unique constraint still holds). Optional: a compose healthcheck for `api` so `docker compose up --wait` means "serving", not just "started".
- [ ] Phase 5 — PDF text extraction, header parsing, PII scrubbing
- [ ] Phase 6 — LLM structuring and normalization
- [ ] Phase 7 — Upload, review and confirm API
- [ ] Phase 8 — History and metrics API
- [ ] Phase 9 — Frontend scaffold and auth
- [ ] Phase 10 — Frontend upload and review
- [ ] Phase 11 — Frontend history and charts
- [ ] Phase 12 — Embeddings and vector search
- [ ] Phase 13 — Query agent
- [ ] Phase 14 — Frontend chat
- [ ] Phase 15 — Flags and trend insights
- [ ] Phase 16 — Deployment (CD)
- [ ] Phase 17 — Hardening and polish

**Next step:** Phase 5 — PDF text extraction, header parsing, PII scrubbing (after the user commits Phase 4 and CI is green). Phase 5 needs a real Thyrocare PDF in `samples/` (gitignored) to model the synthetic fixture on.

---

## 9. Skills, plugins and MCP servers

Use whatever is installed in this environment when it helps. Check what is available at the start of a session (e.g. `/plugin`, `/mcp`) and mention which ones you are using.

- **Context7 MCP**: look up current docs before writing code against FastAPI, SQLAlchemy 2.x, Alembic, pgvector, Groq SDK, fastembed, pdfplumber, Vite, Tailwind, TanStack Query, Recharts, GitHub Actions. Do not rely on memory for APIs or model IDs.
- **frontend-design skill/plugin** (if installed): use for all UI work in Phases 9–11 and 14. Aim for a calm, clean, readable health dashboard, accessible colors (never color-only flags), responsive layout.
- **MarkItDown MCP** (if installed): useful for inspecting a local sample PDF's text during development. Never copy real patient data into code, fixtures, or this file.
- **GitHub MCP** (if installed): read-only use only (e.g. checking workflow runs). Never commit, push, open PRs, or create tags through it.
- **Engineering skills** (if installed): testing strategy when planning tests for a phase, code review before ending a phase, debugging for failures, deploy checklist for Phase 16, documentation for the README.
- If a phase would clearly benefit from a skill or plugin that is not installed, suggest it to the user instead of installing it yourself.

---

## 10. Decision log

| Decision | Reason |
|---|---|
| Long-format `metrics` table, no dynamic columns | New biomarkers are rows; no migrations per new test; easy time series |
| Postgres + pgvector in one DB (Neon) | Relational integrity for health data plus vector search without a second store |
| Text-layer PDF extraction only, no OCR | Family reports are digital PDFs from labs; exact numbers, free, local |
| Groq for all LLM calls; gpt-oss-20b structures, gpt-oss-120b answers | Text-only tasks; Groq does not train on inputs; separate per-model rate limits |
| Gemini, Celery/Redis, Nginx/Caddy removed | Vision not needed; processing is fast enough in-process; Render/Vercel terminate TLS |
| Render (backend) + Vercel (frontend) + Neon (DB) | Free tiers; Vercel's function time limits cannot host the backend |
| Local embeddings (bge-small, fastembed preferred) | Free, private, fits Render's memory limit |
| Flag + explain, never diagnose | Lab values alone lack clinical context; honest and safer framing |
| Manual commits per phase | User reviews and commits every feature themselves |
| Develop on Ubuntu | Native Docker, parity with CI runners and Linux containers |
| Sync SQLAlchemy 2.x + psycopg 3 (not async) | Simpler code, Alembic and tests; `BackgroundTasks` runs sync work in a threadpool; pdfplumber/fastembed are blocking anyway; traffic is family-scale |
| `/health` includes a DB round trip (503 on failure) | Phase 1 "done" criterion; makes a broken DB connection visible to Render's health check |
| `httpx2` instead of `httpx` as the test client (dev only) | Starlette 1.7 deprecates `httpx` in `TestClient` and prefers `httpx2`; approved by the user in Phase 2 |
| CI runs the built image against Postgres, not just `docker build` | Catches runtime-only image faults (venv interpreter path, missing deps, root user) that a build alone misses |
| *Phase 3 schema decisions (agreed before Phase 3):* | |
| UUID primary keys (uuid4, generated in Python) | IDs in URLs (`/patients/{id}`) are not guessable or enumerable |
| Original PDFs stored in Postgres (`bytea`) in a separate 1:1 `report_files` table, kept after confirm | Render free tier has no persistent disk; separate table keeps report listings light; source stays viewable for review. PDFs contain PII but never leave our DB or reach an LLM. Neon free 0.5 GB ≈ 500+ reports |
| Tests use a dedicated `bloodline_test` database: migrations once per session, each test in a rolled-back transaction | Tests never touch dev data; same setup locally and in CI |
| `metric_dictionary` seeded from a versioned data file via an idempotent seed command (upsert on `canonical_name`), not a data migration | Aliases grow as new reports appear, without new migrations. LOINC codes left null unless verified — never guessed |
| Constrained values (`status`, `flag`, `role`, `sex`) as `text` + `CHECK`, not native Postgres enums | Adding values later is a simple migration |
| `NUMERIC` for lab values and reference bounds; `timestamptz` for all timestamps | Preserves printed precision exactly (e.g. "5.60"); unambiguous times |
| `ON DELETE CASCADE` from patient → reports → metrics / chunks / files | A family member's data can be erased completely |
| `patients.sex` required: `male` \| `female` | Selects sex-specific reference ranges |
| *Made during Phase 3:* | |
| Composite FK `(report_id, patient_id) → reports(id, patient_id)` on `metrics` and `report_chunks` | Privacy by design at the lowest layer: the DB itself refuses cross-patient links |
| Metric dictionary seed lives in `app/cli/metric_dictionary.toml` (stdlib `tomllib`, Pydantic-validated) | Comments allowed, no new dependency, ships inside the Docker image |
| Test suite refuses to run against non-local DB hosts | Tests create/drop a `_test` database; they must never do that on Neon |
| *Made during Phase 4:* | |
| JSON login + `Authorization: Bearer` (not OAuth2 password form) | Natural for the React SPA; no `python-multipart` until uploads need it (Phase 7) |
| No access to a patient → 404, same as a nonexistent id; viewer editing → 403 | Never reveal that another family member's record exists |
| 422 validation errors never echo submitted values | Default FastAPI errors reflect inputs (passwords, patient names) back to the client and into any logs |
| Structural test: every `{patient_id}` route must depend on `get_patient_access` | Makes Principle 2's access check impossible to forget in later phases |

### Deferred (revisit only if needed)
- OCR fallback for scanned/photographed reports: Tesseract first, vision model only for low-confidence pages.
- Separate worker + queue if processing ever becomes slow.
- Doctor-facing vs patient-facing views.
