# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: install locked dependencies into /app/.venv with uv.
# Both stages must use the same Python image so the venv's interpreter path matches.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, in their own layer, so code changes don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# The embedding model for report-text search, downloaded once at build time into its own
# layer. At runtime the app never downloads it (Render has no persistent disk, and cold starts
# should not depend on Hugging Face). Keep the model name in step with EMBEDDING_MODEL.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN /app/.venv/bin/python -c \
      "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1], cache_dir='/opt/models')" \
      "$EMBEDDING_MODEL" \
 && chmod -R a+rX /opt/models

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# ---------------------------------------------------------------------------
# Runtime stage: slim image, no uv, non-root user.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie

RUN groupadd --system --gid 999 app \
 && useradd --system --gid 999 --uid 999 --create-home app

# Owned by root, so the app user can read and run the code and the model but not modify them.
COPY --from=builder /app /app
COPY --from=builder /opt/models /opt/models

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EMBEDDING_CACHE_DIR=/opt/models \
    EMBEDDING_OFFLINE=true \
    HF_HUB_OFFLINE=1

USER app
WORKDIR /app

EXPOSE 8000

# Render injects PORT; locally it defaults to 8000. `exec` lets uvicorn receive signals.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
