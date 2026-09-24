# Bloodline

[![CI](https://github.com/AbhiNow0909/Bloodline/actions/workflows/ci.yml/badge.svg)](https://github.com/AbhiNow0909/Bloodline/actions/workflows/ci.yml)

Bloodline is a small web app for tracking a family's lab results over time.

It works like a file system: your account is the root, each **family** you create is a
folder, and each **family member** in it holds their own reports and analysis.

Upload a lab report PDF (blood or urine panel) for a family member and Bloodline extracts the
values. You check and confirm them, and they are added to that member's history. From there
you can view trend charts with the reference range shaded, see which values are out of range
(for one member or the whole family), and ask questions in plain English, such as *"How has
Mum's HbA1c changed over the last two years?"* or *"Who in the family has high LDL?"*

> **Not medical advice.** Bloodline flags values outside their reference range and explains
> what a marker generally relates to. It never diagnoses and never recommends medication.
> Discuss your results with a doctor.

**Status:** early development. The app is built in phases; see [Roadmap](#roadmap).

---

## Features (planned)

- **Families**: group family members into families you create. Only you can see your
  families, their members and everything under them.
- **PDF ingestion**: reads the text layer of digitally generated lab PDFs (no OCR).
- **Privacy-first structuring**: names, addresses, phone numbers, barcodes and doctor
  names are removed locally before any text goes to an LLM.
- **Human review**: extracted values are held as *pending review* until you confirm or
  correct them.
- **History and trend charts**: charts for each metric, with the reference range drawn as a
  band and out-of-range points flagged, plus a family overview of every member's latest
  out-of-range values.
- **Ask questions**: an AI agent answers from your data, about one member or across a family.
  It uses SQL tools for numbers and semantic search (RAG) for report notes, always limited to
  that member or family. The LLM sees members only as labels ("Member A"), never names.
- **Flags and trend alerts**: computed in code, not by the LLM. The LLM only writes the
  plain-language explanation.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `uv` |
| Database | Postgres 16 + `pgvector` (Neon in production) |
| PDF extraction | `pdfplumber` (with `PyMuPDF` as a fallback) |
| LLMs | Groq: `openai/gpt-oss-20b` for structuring, `openai/gpt-oss-120b` for the query agent |
| Embeddings | `BAAI/bge-small-en-v1.5` via `fastembed`, run locally |
| Auth | JWT + Argon2 |
| Hosting | Vercel (frontend), Render in Docker (backend), Neon (database), all on free tiers |
| CI/CD | GitHub Actions → GHCR → Render deploy hook; Vercel Git integration |

## Architecture

```
React SPA (Vercel) ──HTTPS + JWT──▶ FastAPI (Docker on Render)
                                      │
                                      ├─ Ingestion: PDF → text → local header parse
                                      │    → PII scrub → LLM structuring → validate
                                      │    → pending_review → confirm → metrics + embeddings
                                      │
                                      ├─ Query agent: LLM + typed tools (SQL, vector search)
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
               Neon Postgres + pgvector        Groq API
```

## Repository layout

```
.
├── backend/                # FastAPI service
│   ├── alembic/            # database migrations
│   ├── app/
│   │   ├── api/            # routers
│   │   ├── cli/            # create-user, seed
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   └── services/
│   │       ├── extraction/     # PDF text, header parse, PII scrub
│   │       ├── structuring/    # LLM → structured metrics
│   │       ├── normalization/  # metric dictionary, units, ranges
│   │       ├── embeddings/     # local embeddings
│   │       ├── agent/          # query agent tools + orchestrator
│   │       └── llm/            # Groq client, retry
│   └── tests/
│       └── fixtures/       # SYNTHETIC reports only
├── frontend/               # React SPA
└── .github/workflows/      # CI and deployment
```

`docker-compose.yml` (repo root) runs `api` + `db` for local development. `frontend/package.json`
and the workflow files are added in later phases.

## Local development

### Prerequisites

- Ubuntu (or another Linux) with **Docker Engine** and the **Docker Compose** plugin
- **uv** (it can also install Python 3.12):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv python install 3.12
  ```
- **Node.js 22 LTS or newer** (for the frontend), e.g. via [nvm](https://github.com/nvm-sh/nvm):
  `nvm install --lts`
- A free **Groq API key** (for the structuring and query features)

### Configuration

```bash
cp .env.example .env
# then set GROQ_API_KEY and JWT_SECRET (openssl rand -hex 32)
```

See `.env.example` for all variables.

### Backend and database

```bash
docker compose up --build        # starts `api` (FastAPI) and `db` (Postgres 16 + pgvector)
curl http://localhost:8000/health
# {"status":"ok","database":"ok"}  (HTTP 503 with "unreachable" if the DB is down)
```

- API: <http://localhost:8000>, interactive docs at <http://localhost:8000/docs>
- Postgres: `localhost:5432`, user/password/database `bloodline` (local only), data kept in
  the `pgdata` volume. `docker compose down -v` wipes it.
- Both ports are bound to `127.0.0.1`, so nothing is exposed to your network.
- The container is built from the same `backend/Dockerfile` that runs on Render. After code
  changes, run `docker compose up --build` again.

### Migrations and seed data

After the first `docker compose up`, create the schema and load the metric dictionary:

```bash
docker compose exec api alembic upgrade head      # creates tables and the pgvector extension
docker compose exec api python -m app.cli.seed    # loads/updates ~80 biomarker definitions
```

Both commands are safe to re-run. The seed reads
[`backend/app/cli/metric_dictionary.toml`](backend/app/cli/metric_dictionary.toml), where
each metric has a canonical name, category, unit, description and the aliases labs print
for it. To add a biomarker or alias, edit that file and run the seed again.

To change the schema, edit the models in `backend/app/models/`, then generate a migration
against the local database (at head) and review it before committing:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

Autogenerate does not detect changes to CHECK constraints (e.g. adding a new report
status). Write those migration steps by hand.

### Creating a user and logging in

There is no public sign-up. Create accounts with the CLI inside the API container. It prompts
for the password twice (at least 12 characters); the password is never a command-line
argument, so it stays out of shell history:

```bash
docker compose exec api python -m app.cli.create_user --email you@example.com --name "Your Name"
```

For scripts, pipe the password in with `--password-stdin` instead of being prompted.

Log in to get a bearer token (valid for `JWT_EXPIRE_MINUTES`, default 24 h), then send it
in the `Authorization` header. The interactive docs at <http://localhost:8000/docs> have an
**Authorize** button for the same thing.

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "..."}'
# {"access_token": "eyJ...", "token_type": "bearer", "expires_in": 86400}

TOKEN=eyJ...
curl -s -X POST http://localhost:8000/families -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name": "Sharma Family"}'
# {"id": "<family id>", "name": "Sharma Family", "patient_count": 0, ...}

curl -s -X POST http://localhost:8000/families/<family id>/patients \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"display_name": "Mum", "sex": "female", "date_of_birth": "1962-04-10"}'
```

| Endpoint | What it does |
|---|---|
| `GET /families`, `POST /families` | list your families (with member counts), create one |
| `GET/PATCH/DELETE /families/{id}` | view, rename, delete a family (deletes its members and all their data) |
| `GET/POST /families/{id}/patients` | list a family's members, add a member |
| `GET/PATCH/DELETE /patients/{id}` | view, edit, delete one family member |

Only a family's creator can see it. Anything you cannot see answers `404 Not Found`, exactly
as if it did not exist, so other users' families are never revealed. In the API a family
member is called a *patient*.

### Frontend *(available from Phase 9)*

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

### Tests and checks

Tests run against a real Postgres, so start the database first. They read `DATABASE_URL`
from the environment or from the repo-root `.env`, but never use that database directly:
each run recreates a separate `<name>_test` database (e.g. `bloodline_test`), migrates it,
and rolls back every test's changes, so your development data is never touched.

```bash
docker compose up -d db
cd backend
uv sync                          # creates backend/.venv with dev dependencies
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to `main`, every
pull request, and on demand:

- **Backend**: `uv sync --locked`, then ruff lint, ruff format check, mypy (strict) and pytest
  against a `pgvector/pgvector:pg16` service container.
- **Docker image**: builds `backend/Dockerfile` with layer caching, starts the image
  against Postgres, checks that `/health` returns 200 and that the container is not running
  as root, then migrates and seeds the empty database from inside the image (twice for the
  seed, to prove it is idempotent), creates a user with the CLI, logs in, and creates a
  family and a member through the API.

## Privacy

- Real reports go in `samples/`, which is gitignored along with every `*.pdf` outside
  `backend/tests/fixtures/`. Test fixtures are synthetic.
- Identity fields are parsed and removed locally. The LLM sees scrubbed text, and the query
  agent refers to "the patient" (or "Member A", "Member B" in family chat), never a name.
- Every data access is scoped to one family member, or to one family's members, and checked
  against ownership of that family. Vector search always applies a hard `patient_id` filter.
- Secrets live only in environment variables. `.env` is never committed.

## Roadmap

| Phase | Scope |
|---|---|
| 0 | Repository scaffolding |
| 1 | Backend skeleton + Docker |
| 2 | Continuous integration |
| 3 | Database models and migrations |
| 4 | Authentication and patients |
| 4b | Families (user-owned groups of family members) |
| 5 | PDF text extraction, header parsing, PII scrubbing |
| 6 | LLM structuring and normalization |
| 7 | Upload, review and confirm API |
| 8 | History and metrics API |
| 9 | Frontend scaffold and auth |
| 10 | Frontend upload and review |
| 11 | Frontend history and charts |
| 12 | Embeddings and vector search |
| 13 | Query agent |
| 14 | Frontend chat |
| 15 | Flags and trend insights |
| 16 | Deployment (CD) |
| 17 | Hardening and polish |

Current progress and design decisions are tracked in [`CLAUDE.md`](CLAUDE.md).
