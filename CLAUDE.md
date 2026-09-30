# CLAUDE.md — Bloodline

This file is the source of truth for how Bloodline is built. Read it fully at the start of every session, follow the workflow rules exactly, and keep the **Progress** section up to date.

---

## 1. What Bloodline is

Bloodline is a personal, family-scale web app that:

1. Accepts lab reports (blood/urine panels) as **digitally generated PDFs** (e.g. Thyrocare reports issued via Healthcare OnTime).
2. Extracts the text layer, structures it into metrics with an LLM, and asks the uploader to **review and confirm** the values before saving.
3. Organizes people into **families**, like a file system: a user (the root) creates families (folders), adds family members to them, and each member's reports and analysis are the files (Section 4.5).
4. Stores each family member's results as a longitudinal history in Postgres.
5. Shows history, **per-metric trend charts** with the reference range drawn as a shaded band, and a **family overview** of every member's latest out-of-range values.
6. Answers **natural-language questions** about one family member or across a whole family through a tool-calling AI agent, with semantic search over report text (RAG).
7. **Flags and explains** out-of-range values and notable trends. It does **not** diagnose.

Users: a handful of accounts created manually; each account sees only the families it created. It is also a portfolio project, so code quality, tests, Docker, and CI/CD matter as much as features.

---

## 2. Guiding principles (non-negotiable)

1. **Flag and explain, never diagnose.** The app may say a value is outside its reference range, describe what the marker generally relates to, show the trend, and suggest discussing it with a doctor. It must never state or imply a diagnosis ("you have X"), and never recommend medication or dosing. Every AI-generated health explanation shows a short "not medical advice — discuss with your doctor" note.
2. **Privacy by design.**
   - Never send patient names, addresses, phone numbers, barcodes, or referring-doctor names to any LLM. Parse identity/header fields locally, scrub them from the text before any LLM call, and reattach identity only on our own backend. Family members' display names are never sent either: prompts use pseudonymous labels ("the patient", or "Member A", "Member B" in family chat) that only our backend maps back to names.
   - Never commit real reports or real patient data. `samples/` and any `*.pdf` outside `backend/tests/fixtures/` are gitignored. Test fixtures must be **synthetic** (fake names, fake addresses, made-up values in the same layout).
   - Every data access is scoped by `patient_id` (or, for family-level views, by the exact set of patient ids in one family) and checked against the logged-in user's ownership of that family. Vector searches **always** apply a hard `patient_id` filter in SQL (one id, or the family's ids); never rely on semantic similarity alone.
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
│  /auth  /families  /patients  /reports  /metrics  /chat  │
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
- `families` — id, owner_id (→ users, cascade), name, created_at. Unique `(owner_id, name)`. Only the owner can see a family (Section 4.5).
- `patients` — id, family_id (→ families, cascade, required), display_name, sex, date_of_birth (nullable), created_at. A "patient" is a **family member**; the UI says "family member", the schema and API say `patients`.
- ~~`user_patient_access`~~ — created in Phase 3, **dropped in Phase 4b**: access now follows family ownership.
- `reports` — id, patient_id, lab_name, collected_at, file_sha256, file_path/blob, status (`processing` | `pending_review` | `confirmed` | `failed`), failure_reason, raw_extraction (JSONB), created_at
- `metric_dictionary` — id, canonical_name, category, canonical_unit, aliases (text[]), description, loinc_code (nullable)
- `metrics` — id, patient_id, report_id, canonical_metric_id (nullable), raw_name, value_numeric, value_text, unit, value_canonical, unit_canonical, reference_low, reference_high, reference_text, flag (`low` | `normal` | `high` | `unknown`), sample_type, method, collected_at
  - indexes on `(patient_id, canonical_metric_id, collected_at)`
- `report_chunks` — id, patient_id, report_id, chunk_index, content, embedding `vector(384)`
  - HNSW index on `embedding`; every query filters `WHERE patient_id = :pid`

Seed `metric_dictionary` with common panels (CBC, lipid profile, liver, kidney, thyroid, HbA1c/glucose, iron studies incl. ferritin, vitamins, urine albumin/creatinine/UACR) via a migration or seed script.

### 4.3 Query agent

- Two scopes, both access-checked through family ownership:
  - **Member chat** `POST /patients/{id}/chat`: the model sees one pseudonymous label ("the patient"), never a name.
  - **Family chat** `POST /families/{id}/chat` (e.g. "who in my family has high LDL?"): the model sees members only as labels ("Member A", with sex and age), built server-side from that family's members. Every tool takes an optional `member` label, which the backend validates against the family and resolves to a `patient_id`; omitting it runs the tool across all of the family's members. Before the reply reaches the user, the backend maps labels back to display names.
- Model: `gpt-oss-120b` with tool calling. Max tool-call iterations per question (e.g. 5).
- Tools (scoped to the current patient_id, or to the current family's patient ids in family chat; the model can never widen the scope):
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

### 4.5 Families and access (file-system model)

| File system | Bloodline |
|---|---|
| root directory | a user **account** |
| folder | a **family** the user created (e.g. "Sharma family") |
| items in the folder | **family members** (`patients`) |
| files | each member's **reports, metrics, charts and chat** |

Rules (agreed with the user before Phase 4b):
- A user can create any number of families. Each family member belongs to exactly one family.
- **Only a family's creator can see it**: its members, their reports and all analysis. No sharing with other accounts (can be added later with a `family_access` table without redesign).
- Anything the user may not see answers **404**, exactly like something that does not exist.
- Deleting a family deletes its members and everything under them; deleting a user deletes their families.
- Access checks: `get_owned_family` for `{family_id}` routes, `get_owned_patient` for `{patient_id}` routes (the patient's family must be owned by the current user). A test fails if any route with those path parameters skips its check.
- Family-level analysis: a **family overview** (every member's latest out-of-range values side by side) and **family chat** (Section 4.3). Both only ever read the patient ids of that one family.

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

### Phase 4b — Families
- Added after Phase 4 at the user's request (Section 4.5). `families` table (owner, name), required `patients.family_id`; migration moves existing patients into a "My family" per owner and drops `user_patient_access`.
- Access by family ownership: `get_owned_family` / `get_owned_patient`; only a family's creator can see it (404 otherwise).
- API: `GET/POST /families`, `GET/PATCH/DELETE /families/{family_id}`, `GET/POST /families/{family_id}/patients`; `GET/PATCH/DELETE /patients/{patient_id}` keep working; `GET/POST /patients` are replaced by the family routes.
- Tests: family CRUD, isolation between users, cascade deletes, the data migration, and the structural access test extended to `{family_id}` routes.
- Commit: `feat(families): group family members into user-owned families`

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
- Family overview endpoint `GET /families/{family_id}/overview`: each member's latest out-of-range values, side by side.
- Commit: `feat(metrics): add history and time-series endpoints`

### Phase 9 — Frontend scaffold and auth
- Vite + React + TS + Tailwind, routing, API client, TanStack Query, login page, protected routes, family navigation (families list → family → member pages, like folders and files), create/rename/delete families and members. Apply the frontend-design skill.
- Commit: `feat(frontend): scaffold app with auth and family navigation`

### Phase 10 — Frontend upload and review
- Upload with progress/status polling, review table beside a PDF preview, inline edits, confirm.
- Commit: `feat(frontend): add report upload and review screen`

### Phase 11 — Frontend history and charts
- Report timeline, per-metric Recharts line charts with shaded reference band and flagged points, latest-values dashboard.
- Family overview page: every member's latest out-of-range values side by side (never color-only).
- Commit: `feat(frontend): add history dashboard and trend charts`

### Phase 12 — Embeddings and vector search
- Local `bge-small-en-v1.5` via fastembed, chunking of scrubbed report text on confirm, HNSW index, `search_report_text` service with a hard `patient_id` filter (one member, or the exact patient ids of one family for family chat).
- Tests: a search for patient A never returns patient B's chunks; a family-scoped search never returns another family's chunks.
- Commit: `feat(rag): add local embeddings and patient-scoped vector search`

### Phase 13 — Query agent
- Tool definitions (Section 4.3), `gpt-oss-120b` orchestrator loop with iteration cap, deterministic trend helpers, no-diagnosis system prompt, member chat `POST /patients/{id}/chat` and family chat `POST /families/{id}/chat` (pseudonymous member labels, mapped back to names only on the backend).
- Tests: tool functions; orchestrator with a mocked LLM; guardrail prompt present; family chat never sends display names to the LLM and cannot reach members of another family.
- Commit: `feat(agent): add tool-calling query agent`

### Phase 14 — Frontend chat
- Chat panel per member and per family, streaming or loading state, citations of report dates (and which member), disclaimer.
- Commit: `feat(frontend): add patient chat interface`

### Phase 15 — Flags and trend insights
- Deterministic trend alerts (Section 4.4), insights panel on each member's dashboard and in the family overview, LLM-phrased plain-language explanations with the disclaimer.
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
  - Follow-ups: **Sharing** — resolved by the user's families decision (Phase 4b, Section 4.5): families are visible only to their creator. **Phase 17** — login rate limiting; token revocation (tokens stay valid until expiry, and there is no password-change endpoint yet). Minor: `create_user` CLI shows a traceback if two runs race on the same email (unique constraint still holds). Optional: a compose healthcheck for `api` so `docker compose up --wait` means "serving", not just "started".
- [x] Phase 4b — Families (inserted after Phase 4 at the user's request; see Section 4.5)
  - Design agreed with the user first (Section 4.5): file-system model; only a family's creator can see it; any number of families per user; each member in exactly one family; family overview + family chat planned for later phases (Phases 8, 11–15 updated).
  - `app/models/family.py` (`families`: `owner_id` → users cascade, `name`, `UNIQUE(owner_id, name)`); `patients.family_id` required (→ families cascade, indexed); `UserPatientAccess`/`AccessRole` removed.
  - Migration `2026_09_24_fd63c4d93886_add_families.py` (autogenerated, rewritten by hand — the draft dropped the access table before reading it): creates `families`, adds nullable `family_id`, moves each owner's patients into one "My family" (earliest owner wins; viewer rows ignored), **refuses** (raises) if any patient has no owner instead of deleting it, then makes `family_id` NOT NULL and drops `user_patient_access`. Downgrade rebuilds owner access rows from families. Plain-SQL `op.execute` avoids `:` (bind-parameter syntax, per Alembic docs via Context7).
  - Access: `get_owned_family` / `get_owned_patient` in `app/api/deps.py` (join through `families.owner_id`); 404 "Family not found" / "Patient not found" for anything not owned, identical to nonexistent ids. `require_owner` and roles removed.
  - API (`app/api/families.py`, `app/api/patients.py`): `GET/POST /families` (list with `patient_count`, create; 409 on a duplicate name), `GET/PATCH/DELETE /families/{family_id}`, `GET/POST /families/{family_id}/patients`, `GET/PATCH/DELETE /patients/{patient_id}`. `GET/POST /patients` removed. Moving a member between families is not supported (`family_id` in a body is a 422).
  - Tests (125 total): family CRUD and name uniqueness per owner, list counts, cascade deletes (member / family / user), cross-user isolation matrix (404 identical to nonexistent, nothing changed), 401s, validation, no-echo of member names, and three data-migration tests (upgrade from the Phase 3 schema with real rows, downgrade rebuilding access, orphan refusal). The structural test (`tests/test_access_control.py`) now covers `{family_id}` → `get_owned_family` and `{patient_id}` → `get_owned_patient`; verified to flag deliberately unprotected routes of both kinds.
  - CI docker smoke now also creates a family and a member through the API inside the image, and checks unauthenticated `/families` is 401 (replayed locally end-to-end on an empty DB).
  - Context7 used (Alembic operations docs). Code review: no defects found; added an assertion for `patient_count` in the family list (a separate query path from the detail view).
  - Follow-ups: family names are unique per owner case-sensitively ("Sharma" and "sharma" can coexist) — fine for now. Concurrent creation of the same family name could hit the unique constraint as a 500 (pre-check covers normal use). Family overview endpoint → Phase 8; family navigation UI → Phase 9; family chat → Phases 13–14.
- [x] Phase 5 — PDF text extraction, header parsing, PII scrubbing
  - `app/services/extraction/`: `pdf_text.read_page_texts` (pdfplumber; `UnreadablePdfError` for non-PDFs and > 50 pages; **any** page without a text layer → `NoTextLayerError("scanned/image PDF not supported yet")`, never skipped, since it could hide results), `layout` (page kinds: results = has a `TEST NAME … VALUE … UNITS` line; conditions; other = cover/summary; `split_results_page` keeps only the table region and drops the identity header and the footer from `Report Remarks`), `header.parse_header` (regexes that stop at whole right-column labels because pdfplumber merges the two header columns into one line), `pii.scrub_text` / `find_leaks`, `pipeline.extract_report` → `ExtractedReport`.
  - Layout learned from the user's real Thyrocare PDF in `samples/`, inspected only through masked views (identity letters → x/X, digits → 9); nothing from it is in code, fixtures or this file. Real report: 6 pages (cover, status summary, 3 results pages, Conditions of Reporting); header bracket codes `(SCT)/(SRT)/(RRT)` are field abbreviations, not time zones; times are Indian local time → parsed with a fixed +05:30 `IST` offset (no tzdata needed); the micro sign is U+00B5.
  - `ExtractedReport`: lab name, earliest collection time, printed age/sex, per-page sample type + collected/received/released times, scrubbed text per page, dropped page numbers, warnings (e.g. pages for different patients). `llm_text()` = each page's scrubbed results prefixed with `Sample type: …`. The printed identity (names, referrers, barcodes) is kept on the backend only for scrubbing and the Phase 7 name-mismatch warning, and is `Field(exclude=True, repr=False)` so it never reaches `model_dump`/JSON/logs.
  - Scrubbing = structural (header/footer dropped) + regex (emails, Indian mobiles incl. `+91` and `98765 43210`, barcodes, full printed names as phrases, name parts ≥ 3 chars, referring doctor, `Dr …` signatures). `extract_report` **fails closed** with `PiiLeakError` (kinds only, no values) if `find_leaks` still finds identity.
  - Synthetic fixture `backend/tests/fixtures/synthetic_thyrocare_report.pdf`, generated deterministically by `tests/synthetic_pdf.py` (a ~40-line text-only PDF writer, Helvetica/cp1252 so µ renders — no PDF-authoring dependency); a test fails if the committed PDF drifts from the generator.
  - Validated against the real report (masked output only): 3 results pages kept, header fields and IST times parsed, 0 of 22 header-only words present in the LLM text. Two bugs found and fixed this way / by tests: the fixture's guessed `(IST)` labels (real: SCT/SRT/RRT), and label matching that truncated names like "RAVI TEST" (a truncated name would escape scrubbing).
  - Tests: 211 total (86 new): reader errors, page classification, header variants, label-like surnames, IST conversion, scrubber table (and results left untouched), end-to-end rows/ranges/units kept, every fake identity value absent, identity never serialized, different-patient warning, unsupported layout, fail-closed leak check.
  - Dependencies: `pdfplumber` 0.11 (pulls `pdfminer.six`, `pypdfium2`, Pillow, and `cryptography`, which made PyJWT's key types strict — one Phase 4 test updated to use `""` as the `alg=none` key). Image 304 → 387 MB. PyMuPDF fallback **not** added: pdfplumber reads the real report fully and PyMuPDF is AGPL; add only if a real report needs it.
  - CI docker job also extracts the synthetic report inside the built image (native deps check).
  - Context7 used (pdfplumber API). Testing-strategy and code-review skills used; review added whole-phrase name scrubbing so short name parts (e.g. "LI") go when the full name appears.
  - Follow-ups: **Phase 6** send `llm_text()` only; parse ranges like `Male:/Female:`, `Men:/Women:`, `Adults: Less than N`, units `µg/mL`, `µg/mg of Creatinine`. **Phase 7** store header fields (sample types, times, printed age/sex) on the report (migration or `raw_extraction`, never the identity) and compare `identity.names` with the member's display name for a mismatch warning. Known limits: only Thyrocare-style layouts (others → `UnsupportedLayoutError`); the `Report Remarks` footer is dropped entirely (lab remarks are not available to RAG yet); name parts shorter than 3 characters are scrubbed only as part of the full name.
- [x] Phase 6 — LLM structuring and normalization
  - Model IDs confirmed live against the Groq `/models` endpoint with the user's key (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, 131k context); Groq structured outputs (`json_schema`, `strict: true`) and SDK errors/retries confirmed via Context7. `groq` SDK 1.7.
  - `app/services/llm/`: `ChatClient` protocol (the mocking boundary), `GroqChatClient` (strict JSON schema, `temperature=0`, `seed=0`, `reasoning_effort="low"`, `reasoning_format="hidden"`, `max_completion_tokens=16384`; SDK retries off), `retry.call_with_retries` (exponential backoff with full jitter, honours `Retry-After`, 4 attempts; retries 429/5xx/connection/timeouts only), errors `LLMUnavailableError` ("busy, try again"), `LLMRequestError` (status only, never the key), `LLMNotConfiguredError`. `get_structuring_client()` is cached (one HTTP pool). Settings: `GROQ_API_KEY` (optional `SecretStr`; blank = unset), `STRUCTURING_MODEL`, `AGENT_MODEL`.
  - **Division of labour (differs from Section 4.1 step 5, see Decision log):** the LLM only segments and copies strings (`raw_name`, `panel`, `technology`, `value`, `unit`, `method`, `sample_type`, and each printed range line as `{label, text}`); Python derives everything numeric. `app/services/structuring/`: hand-written strict schema (`LLM_REPORT_SCHEMA`, kept in sync with `LlmReport` by a test), `SYSTEM_PROMPT`, `structure_report()` (sends only `ExtractedReport.llm_text()`, re-runs the leak check at the LLM boundary, validates the reply with Pydantic) and `normalize_test()`.
  - `app/services/normalization/`: `parse_number` (exact `Decimal`; "<0.5"/"Negative" stay text), `parse_bounds` ("39 - 259", "Less than 30", "> 5", en dash, "Upto"), `select_range` (patient's sex line, else a single general line such as "Adults"/unlabelled; ambiguous or subgroup-only → none), `compute_flag` (inclusive bounds), `convert`/`unit_key` (µ/μ→u, `10³`, lakhs/thousand/million per cumm; SI-prefix arithmetic within mass/mol/IU/count per volume and mass/mass; analyte-specific conversions such as mg/dL→mmol/L are never guessed), `MetricIndex`/`name_key`/`load_metric_index` (exact normalized names and aliases, trailing "(…)" handled, urine sample prefers the urine test; never substring).
  - Every row keeps what was printed (`value_text`, `unit`, full `reference_text`, chosen `reference_label`) and carries review warnings: value or name not found in the report text (catches hallucinations and prompt-injected values), unknown test, no range matched (numeric values only), unit not converted.
  - A real `gpt-oss-20b` reply for the synthetic report (1.6 s) is recorded in `tests/structuring_data.py`; it revealed the model sometimes appends the TECHNOLOGY value to the test name, now stripped deterministically. Synthetic report → Urine Creatinine / Urine Microalbumin / UACR / Ferritin, female ranges chosen, µg/mL→mg/L and µg/mg→mg/g, all "normal", no warnings.
  - Tests: 328 total (117 new): numbers, bounds, range selection (sexes, Men/Women, Adult Male, general, ambiguous), flags, unit keys and conversions, name mapping incl. no-substring cases and the DB-loaded index, retry/backoff/Retry-After/give-up/non-retryable/non-JSON with real `groq` exception objects, schema strictness, only scrubbed text sent, leak guard stops before any call, invalid reply shapes, hallucinated value warning, qualitative and unconvertible values, and one `live` test (synthetic report through real Groq; skipped without `GROQ_API_KEY`, as in CI).
  - Your real report was **not** sent to Groq during development (synthetic only).
  - CI docker step also imports the structuring stack inside the image. Image 387 → 392 MB. Code review: cached the Groq client (per-call clients leaked connection pools) and capped completion tokens.
  - Follow-ups: **Phase 7** load the index with `load_metric_index`, call `structure_report(extracted, patient_sex=patient.sex, …)` in the background task, store `StructuredReport.model_dump(mode="json")` (Decimals serialize as exact strings) in `raw_extraction`, surface row warnings in the review payload, map `LLMError`/`StructuringError`/`ExtractionError` messages to `failure_reason`. Known limits: range bounds are inclusive (a "Less than 30" value of exactly 30 is "normal"); ranges with category labels (e.g. vitamin D "Deficiency/Sufficiency") are left for the user to choose in review.
- [x] Phase 7 — Upload, review and confirm API
  - `POST /patients/{patient_id}/reports`: the PDF is the **raw request body** (`Content-Type: application/pdf`), not multipart — ownership (`get_owned_patient`) is checked before a byte is read, the `MAX_UPLOAD_MB` limit (setting, default 10, max 50) is enforced from `Content-Length` and again while streaming (413), then `%PDF-` magic (422), empty (422), wrong media type (415). Per-member SHA-256 dedupe → 409 with `{"detail": {"message", "report_id"}}` (also on a concurrent-insert race). Creates `reports` (`processing`) + `report_files`, returns 202, schedules the background task. No `python-multipart` needed.
  - `app/services/ingestion.py`: `process_report(report_id, session_factory, client_factory, model)` opens its **own** session (FastAPI ≥ 0.106 closes request-scoped dependencies before background tasks; confirmed via Context7): extract → structure (Phase 6) → `StoredProcessing{version, extraction, structured, warnings}` in `reports.raw_extraction` (scrubbed text + header fields + rows; identity excluded) → `pending_review`, sets `lab_name`/`collected_at`. Any `ExtractionError`/`LLMError`/`StructuringError` → `failed` with its user-safe message; anything else → logged (report id only) and `failed` with a generic message; deleted reports are ignored. The session factory returns a context manager (production: a fresh `Session`; tests: `nullcontext(db_session)`); the LLM client is resolved inside the task, so a missing `GROQ_API_KEY` fails the report rather than the upload.
  - Mismatch warnings (`member_mismatch_warnings`): printed sex vs member's sex, printed age vs age from date of birth at collection (±1 year), printed name vs display name (no shared word → gentle warning; the printed name is never stored or shown).
  - `GET /reports/{report_id}` (status), `GET …/review` (409 unless `pending_review`), `POST …/confirm` (`ConfirmReport`: reviewed rows as text + bounds, optional aware `collected_at`; server recomputes `value_numeric`, canonical conversion and flag; unknown dictionary ids / low > high / future date / missing date → 422; not pending → 409), `POST …/retry` (failed only), `GET …/file` (PDF, `no-store`, `nosniff`), `DELETE /reports/{report_id}` (cascades), `GET /metric-dictionary`. New `get_owned_report` (report → member → family owner; 404 "Report not found"); the structural test covers `{report_id}`.
  - `ExtractedReport.identity` got an empty default so stored extractions round-trip (they never contained identity).
  - Tests: 382 total (54 new): upload happy path through review, only scrubbed text in the LLM call and in `raw_extraction`, media type/empty/not-PDF/size limit (declared and streamed), dedupe per member, access (401/404 before reading), review states, confirm (history rows with server-computed values, corrections re-flagged, un-mapping, removal, 9 validation cases incl. client-sent flag and `1e400`), once-only confirm, retry, file, delete cascade, cross-user 404 matrix for all report routes, dictionary list, and direct pipeline tests (six failure kinds, deleted report, non-processing report, mismatch warnings).
  - Verified end to end in the production image against the **real** Groq API (synthetic PDF, throwaway DB): upload → processed → review (4 rows, female ranges, no warnings) → confirm → duplicate 409 → file download identical. CI docker job now uploads the synthetic report and asserts it fails cleanly with "GROQ_API_KEY is not set" and that a re-upload is 409 (replayed locally from the YAML).
  - Code review: capped decimals at 18 significant digits (confirm bounds → 422; longer printed "numbers" stay text) — `NaN`/`Infinity` were already rejected by Pydantic.
  - Follow-ups: a report stuck in `processing` (server restart mid-task) can only be deleted and re-uploaded; add a stale-processing retry if it ever happens. **Phase 8** lists reports per member and reads confirmed `metrics`. **Phase 10** the frontend uploads with `XMLHttpRequest` (raw body, progress events), fetches `/reports/{id}/file` as a blob with the bearer token for the PDF preview, and uses `/metric-dictionary` for mapping. **Phase 12** chunk `StoredProcessing.extraction.pages[].text` on confirm (hook marked in `confirm_report`).
- [x] Phase 8 — History and metrics API
  - `app/services/history.py`: read-side queries that take the **exact patient ids** to read (callers resolve them via ownership checks; the Phase 13 agent tools will reuse them with one member's id or one family's ids): `list_reports` (newest first by collection time, else upload time; value and flagged counts via `count() FILTER`), `report_readings`, `metric_catalog` (latest reading per test via Postgres `DISTINCT ON (patient_id, series)` where series = dictionary id, else `raw:<printed name>`; count and first date; unmapped tests last), `metric_history` (oldest first; `start`/`end` inclusive Indian calendar days; each point carries `reference_low/high_canonical` converted with the Phase 6 unit rules so chart bands line up across labs), `out_of_range` (default: tests whose *latest* value is low/high; `latest_only=False` for every flagged value; `since`), `family_overview` (per member: latest out-of-range values, tracked-test count, last confirmed collection time; 4 queries for the whole family).
  - `app/api/history.py`: `GET /patients/{id}/reports`, `GET /reports/{id}/metrics`, `GET /patients/{id}/metrics`, `GET /patients/{id}/metrics/{metric_id}` (404 unknown metric, 422 `start > end`, empty series if never tested), `GET /patients/{id}/out-of-range`, `GET /families/{id}/overview`. All behind the existing ownership checks (structural test covers them). `app/schemas/history.py`: `MetricInfo` (incl. description for explanations), `Reading`, `HistoryPoint`, `MetricHistory`, `CatalogEntry`, `FlaggedReading`, `ReportSummary`, `MemberOverview`, `FamilyOverview`; decimals serialize as exact strings.
  - Context7: SQLAlchemy 2.0 `select().distinct(*cols)` renders `DISTINCT ON` on PostgreSQL without deprecation.
  - Tests: 393 total (11 new): ordering and counts, one report's values, catalog latest/first/count/unmapped, time series with g/L→g/dL range conversion, midnight-edge IST date filters, 404/422/empty, out-of-range now vs ever vs since, **service scoping by exact patient ids** (one, two, none; never a stranger), family overview (flagged, clean, no-data members; other family excluded), 404/401 on every history route.
  - Verified end to end in the production image with real Groq (synthetic PDF, throwaway DB): upload → confirm → reports, catalog, series, out-of-range and family overview all return the confirmed values.
  - Bug found by tests: `dict(result)` on a SQLAlchemy `Result` treats it as a mapping (it has `.keys()`); use `.all()` first.
  - Follow-ups: unmapped tests appear in the catalog but have no time-series endpoint (map them in review). **Phase 9**: install the `frontend-design` plugin (`/plugin install frontend-design@claude-plugins-official`); it is not installed yet and Section 9 asks to use it for all UI work.
- [x] Phase 9 — Frontend scaffold and auth
  - Stack (versions checked against npm and Context7): Vite 8.3, React 19.3, React Router 8.4 (data mode: `createBrowserRouter` from `react-router`, `RouterProvider` from `react-router/dom`), TanStack Query 5.104, Tailwind 4.3 via `@tailwindcss/vite` (`@theme` tokens in `src/index.css`, no config file), TypeScript **6.0** (typescript-eslint 8.71 supports < 6.1, so not TS 7), ESLint 10 flat config (`strictTypeChecked`, react-hooks, react-refresh) + Prettier 3.9, Vitest 5 + jsdom 30 + Testing Library. Node 24 LTS (`frontend/.nvmrc`, `engines >= 22`). `create-vite` 9 now defaults to oxlint; ESLint kept as CLAUDE.md specifies.
  - `src/lib/`: `api.ts` (fetch wrapper: bearer token, `ApiError` with user-facing messages, 422 → per-field messages, network/5xx messages, 204), `session.ts` (token + expiry in `localStorage`, expiry timer, sign-out follows across tabs via the `storage` event, stable `get()` for `useSyncExternalStore`), `queries.ts` (query keys, hooks, mutations and cache updates), `format.ts` (Indian date format, age from date of birth, stable tube-cap colour per member), `forms.ts` (focus the first invalid field).
  - Routes (`src/routes.tsx`): `/login`; everything else behind `RequireAuth` (redirects to `/login`, then back to the page asked for; only same-app paths) → `AppLayout` → `/families`, `/families/:familyId`, `/families/:familyId/members/:memberId`, `*` not found. A member opened under another family's URL is "not found", like a 404.
  - Privacy: logging out, an expired token (timer, or found expired on the next request) or a 401 ends the session and **clears the whole query cache** (also when another tab switches account), so nothing of one account is shown to the next. Not-found pages look the same whether something was deleted or belongs to someone else. The member-name hint says names are never sent to the AI (Principle 2).
  - Screens (frontend-design skill): calm lab-vernacular look: "requisition paper" background, slate ink, EDTA-tube violet accent; red only for destructive actions (later: "high" flags). Families are folder cards with a tab, members are file cards with a folded corner and an initial on a blood-tube cap colour (decorative; the name is always shown). Breadcrumbs read like a path. 18px base type (Atkinson Hyperlegible Next, bundled, no third-party requests), ≥ 44px targets, visible focus rings, icons always with words, skip link, headings take focus on page change, native `<dialog>` modals (focus starts on Cancel in delete confirmations, which spell out what is deleted). Contrast checked: text ≥ 5.6:1, field borders 3.5–3.8:1 (WCAG 1.4.11).
  - Member page shows details and an honest placeholder for reports (Phase 10–11).
  - Tests (62, Vitest): session (expiry, restore, other tabs), API error mapping and token handling, formatting; flows through the real router and query client against an in-memory fake API (`src/test/fakeApi.ts`): sign-in and return, wrong password, validation and focus, sign-out clears the cache, 401 signs out, families list/create/duplicate 409/rename/delete with confirm, members add/validate/422/edit/delete, stale data never shown after a delete, not found. Passes in time zones from UTC−11 to UTC+14 (a clock-order bug made one file depend on the time of day; fixed).
  - Verified in a real browser (Playwright) against the backend on a throwaway database: sign in, create families and members, edit, confirm dialog, log out; desktop and 375px wide, no horizontal scroll, no console warnings, CORS preflights OK.
  - CI: new `frontend` job (`actions/setup-node@v7` with npm cache from `frontend/package-lock.json`; `npm ci`, lint, format check, typecheck, tests, build), validated with actionlint 1.7.12 and replayed in a clean `node:24-slim` container.
  - `vite.config.ts` reads `.env` from the repo root (`envDir: '..'`); only `VITE_*` variables reach the browser.
  - Code review (code-review skill's checks, run locally since there is no PR): fixed field-border contrast (1.4:1 → 3.8:1), an expired session is now ended on the next request instead of sending it without a token, and tests no longer wait for real retry delays.
  - Tooling note: the GitHub MCP server failed to connect ("Authorization header is badly formatted") and the engineering plugin's MCP servers need authorization via `/mcp`; neither was needed for this phase.
  - Follow-ups: **Phase 10** upload with `XMLHttpRequest` (raw PDF body, progress), fetch `/reports/{id}/file` as a blob with the bearer token for the preview; the member page's Reports placeholder is where the list goes. **Phase 16** Vercel needs an SPA rewrite (every path → `index.html`) so deep links and reloads work; add the Vercel origin to `CORS_ORIGINS`; consider a Content-Security-Policy header (the token is in `localStorage`; the app never renders HTML from data). Known limits: after logging out and signing in as another account, the "return to" page may be the previous account's page, which then shows "not found"; the date-of-birth check uses the browser's date while the server uses its own (a birth date of "today" near midnight may be refused by one and not the other).
- [ ] Phase 10 — Frontend upload and review
- [ ] Phase 11 — Frontend history and charts
- [ ] Phase 12 — Embeddings and vector search
- [ ] Phase 13 — Query agent
- [ ] Phase 14 — Frontend chat
- [ ] Phase 15 — Flags and trend insights
- [ ] Phase 16 — Deployment (CD)
- [ ] Phase 17 — Hardening and polish

**Next step:** Phase 10 — Frontend upload and review (after the user commits Phase 9 and CI is green).

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
| Structural test: every `{patient_id}` route must depend on its access check (since Phase 4b: `get_owned_patient`, and `{family_id}` on `get_owned_family`) | Makes Principle 2's access check impossible to forget in later phases |
| *Families (user's decision before Phase 5, built as Phase 4b):* | |
| File-system model: user → families → family members → reports/analysis | The user's requested mental model; groups each person's data under a family they manage |
| Only a family's creator can see it; any number of families per user; each member in exactly one family | User's choices; simplest model for 2–3 people; sharing can be added later via a `family_access` table |
| `user_patient_access` dropped; access = `patients.family_id → families.owner_id` | One source of truth for access; the viewer role had no use without sharing |
| Keep the name `patients` in schema and API; UI says "family member" | Avoids renaming across models, migrations and every later phase's `/patients/{id}/...` routes |
| Family overview + family chat, with members shown to the LLM only as labels ("Member A") | User's choice; keeps Principle 2 (no names to LLMs) while allowing cross-member questions |
| *Made during Phase 5:* | |
| Keep only each results page's table region; drop header and footer structurally, then regex-scrub, then fail closed on any leftover identity | Structure removes most identity reliably; regexes are the second line; failing is safer than sending |
| Any page without a text layer fails the report (spec, Section 4.1) | A skipped scanned page could silently lose results |
| Synthetic PDF fixture from a tiny deterministic writer in `tests/`, not a PDF library | No new dependency; exact control of layout; reproducible bytes checked by a test |
| No PyMuPDF fallback yet | pdfplumber reads the real report fully; PyMuPDF is AGPL — add only when a real report needs it |
| Report times parsed as fixed +05:30 IST | Thyrocare prints Indian local time; India has no DST; avoids a tzdata dependency |
| *Made during Phase 6:* | |
| The structuring LLM only segments and copies strings; values, range bounds, sex-specific range choice, unit conversion, dictionary mapping and flags are computed in Python (refines Section 4.1 step 5) | No number ever comes from the model; logic is deterministic and unit-tested; each copied value is checked against the source text, so hallucinated or injected values surface in review |
| Hand-written strict JSON schema for Groq structured outputs (+ sync test with the Pydantic models) | Strict mode requires every field required and `additionalProperties: false`; explicit beats generated for a provider contract |
| Own retry policy (SDK retries off): backoff with full jitter, honour `Retry-After`, 4 attempts, only 429/5xx/network | One tested policy; friendly "busy, try again" after exhaustion |
| Only analyte-independent unit conversions | mg/dL ↔ mmol/L depends on the analyte; guessing would corrupt history, so such rows are flagged for review |
| Live LLM test uses the synthetic report only and is skipped without `GROQ_API_KEY` | CI needs no secret; the user's real data is not sent to Groq during development |
| *Made during Phase 7:* | |
| Upload the PDF as the raw request body (`application/pdf`), not multipart | Ownership is checked before reading; size limit enforced while streaming; no `python-multipart`; XHR still gives upload progress |
| Flat `/reports/{report_id}` routes with `get_owned_report` | One ownership join; the structural test covers `{report_id}` |
| Processing results live in `reports.raw_extraction` (`StoredProcessing`, versioned); no migration | Header fields, scrubbed text and rows are review-time data; `lab_name`/`collected_at` already have columns |
| Confirm recomputes every number server-side from reviewed text and bounds | The client and the LLM are never trusted for values or flags |
| Failed reports can be retried; any report can be deleted | Dedupe would otherwise block re-uploading after a transient failure |
| *Made during Phase 8:* | |
| History services take explicit patient ids; routes resolve them through ownership checks | One scoping contract for the API and the agent tools (member or family) |
| "Out of range" defaults to tests whose latest value is flagged | Answers "what needs attention now"; history of flagged values is available with `latest_only=false` |
| Chart ranges converted to the canonical unit per point | Different labs print different units; the shaded band must match the plotted values |
| *Made during Phase 9:* | |
| ESLint + Prettier kept (not the oxlint default of `create-vite` 9) | CLAUDE.md specifies them; `strictTypeChecked` rules catch real bugs (floating promises, unsafe `any`) |
| TypeScript pinned to 6.0 | typescript-eslint 8.71 supports TypeScript < 6.1 |
| JWT in `localStorage` with its expiry; cleared on logout, expiry, 401, or another tab signing out | Survives reloads and new tabs for 24 h; the app never renders HTML from data (main XSS defence); an httpOnly cookie would need CSRF handling and cross-site cookies between Vercel and Render |
| Whole query cache cleared whenever the session ends or changes account | Privacy between the family's accounts on a shared device |
| No icon library; a few hand-drawn inline SVG icons, always next to words | No dependency for eight icons; never icon-only or colour-only meaning |
| Self-hosted font (Atkinson Hyperlegible Next via `@fontsource`) | Legible for older readers; no requests to font CDNs (privacy) |
| Frontend tests use an in-memory fake of the API behind `fetch` | Whole flows through the real router, query client and session without a backend; the real API contract is covered by the backend tests and the CI smoke test |

### Deferred (revisit only if needed)
- OCR fallback for scanned/photographed reports: Tesseract first, vision model only for low-confidence pages.
- Separate worker + queue if processing ever becomes slow.
- Doctor-facing vs patient-facing views.
