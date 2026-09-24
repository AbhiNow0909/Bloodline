# Bloodline

Bloodline is a small web app for tracking a family's lab results over time.

Upload a lab report PDF (blood or urine panel) and Bloodline extracts the values. You check
and confirm them, and they are added to that family member's history. From there you can
view trend charts with the reference range shaded, see which values are out of range, and
ask questions in plain English, such as *"How has my HbA1c changed over the last two years?"*

> **Not medical advice.** Bloodline flags values outside their reference range and explains
> what a marker generally relates to. It never diagnoses and never recommends medication.
> Discuss your results with a doctor.

**Status:** early development. The app is built in phases; see [Roadmap](#roadmap).

---

## Features (planned)

- **PDF ingestion**: reads the text layer of digitally generated lab PDFs (no OCR).
- **Privacy-first structuring**: names, addresses, phone numbers, barcodes and doctor
  names are removed locally before any text goes to an LLM.
- **Human review**: extracted values are held as *pending review* until you confirm or
  correct them.
- **History and trend charts**: charts for each metric, with the reference range drawn as a
  band and out-of-range points flagged.
- **Ask questions**: an AI agent answers from your data. It uses SQL tools for numbers and
  semantic search (RAG) for report notes, always limited to the selected family member.
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

`docker-compose.yml`, `backend/Dockerfile`, `backend/pyproject.toml`, `frontend/package.json`
and the workflow files are added in later phases.

## Local development

### Prerequisites

- Ubuntu (or another Linux) with **Docker Engine** and the **Docker Compose** plugin
- **uv** (it can also install Python 3.12):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv python install 3.12
  ```
- **Node.js 22 LTS or newer** (for the frontend)
- A free **Groq API key** (for the structuring and query features)

### Configuration

```bash
cp .env.example .env
# then set GROQ_API_KEY and JWT_SECRET (openssl rand -hex 32)
```

See `.env.example` for all variables.

### Backend and database *(available from Phase 1)*

```bash
docker compose up --build        # starts `api` (FastAPI) and `db` (Postgres + pgvector)
curl http://localhost:8000/health
```

### Migrations and seed data *(available from Phase 3)*

```bash
docker compose exec api alembic upgrade head
```

### Creating a user *(available from Phase 4)*

There is no public sign-up. Accounts are created with a CLI script inside the API container.
The exact command will be documented in Phase 4.

### Frontend *(available from Phase 9)*

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

### Tests and checks *(available from Phase 1/2)*

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest                    # integration tests need the Postgres container running
```

## Privacy

- Real reports go in `samples/`, which is gitignored along with every `*.pdf` outside
  `backend/tests/fixtures/`. Test fixtures are synthetic.
- Identity fields are parsed and removed locally. The LLM sees scrubbed text, and the query
  agent refers to "the patient", never a name.
- Every data access is scoped to a patient and checked against the logged-in user's access.
  Vector search always applies a hard `patient_id` filter.
- Secrets live only in environment variables. `.env` is never committed.

## Roadmap

| Phase | Scope |
|---|---|
| 0 | Repository scaffolding |
| 1 | Backend skeleton + Docker |
| 2 | Continuous integration |
| 3 | Database models and migrations |
| 4 | Authentication and patients |
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
