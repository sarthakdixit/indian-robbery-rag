# syntax=docker/dockerfile:1.7
#
# Backend container for the Indian Robbery Law RAG Assistant.
#
# Multi-stage build:
#   - `builder`: installs Python deps into a venv. Has build tools
#     available in case any package needs to compile from source.
#   - `runtime`: minimal final image with the venv copied in, the
#     app code, and the pre-built indices baked in.
#
# Build invocation (from REPO ROOT, not from backend/):
#     docker build -f backend/Dockerfile -t robbery-rag-backend .
#
# Why repo-root build context: the Dockerfile COPYs from `backend/app/`,
# `ingestion/data/chroma_db/`, and `data/` — three paths that only share
# a common ancestor at the repo root. Per design.md CORP-13, both the
# raw corpus and the built index are baked into the image.
#
# Prerequisites:
#   1. `make ingest` has been run, producing ingestion/data/chroma_db/
#      and ingestion/data/bm25_index/. The entrypoint sanity-checks
#      this and fails fast otherwise.
#   2. The repo root contains the data/ directory with the bare-act PDFs
#      and judgment subfolders (committed per design.md §10.4).

# ---------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Build tools, in case any wheel needs to compile. Most of our deps
# (ChromaDB, bm25s, etc.) ship prebuilt linux/amd64 wheels, so this is
# defensive. Removed in the runtime stage to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create a venv at /opt/venv. Using a venv (rather than installing
# into the system site-packages) makes it trivial to COPY just the
# installed deps into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

# Copy and install deps first, separately from the app code, so the
# layer cache stays warm when only app code changes.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Non-root user for security. Container scanners flag root processes;
# Container Apps best-practices recommend non-root.
RUN groupadd -r app \
    && useradd -r -g app -d /app -s /usr/sbin/nologin app

# Runtime-only system deps. ca-certificates is needed for outbound
# HTTPS (Gemini API, Cloudflare Turnstile verification, Application
# Insights). curl is here purely for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the venv from the builder. Owned by root; the app user can read
# but not modify, which is the correct security stance.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
# PYTHONDONTWRITEBYTECODE: don't write .pyc files at runtime
# (they'd accumulate in /app and bloat any image diff).
# PYTHONUNBUFFERED: print() and logs flush immediately, not when the
# stdio buffer fills — important for visible logs under Docker.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Application code. Ownership goes to `app` so the runtime user can
# read everything, but the source is immutable from inside the
# container (only /app/local_data is writable, set up by entrypoint).
#
# `backend/__init__.py` is copied separately because the next COPY only
# brings in `backend/app/`. The `__init__.py` makes `backend` a real
# package (rather than relying on Python's namespace-package fallback).
# Either would work, but the explicit form is unambiguous.
COPY --chown=app:app backend/__init__.py /app/backend/__init__.py
COPY --chown=app:app backend/app /app/backend/app

# Pre-built indices. These are the LARGE files in the image (~20-50 MB
# combined per design.md CORP-12). Bake them in so the runtime never
# needs to rebuild — `docker run` is enough to serve queries.
#
# `chunks.jsonl` is needed alongside the indices: ChromaDB returns
# top-k chunk_ids, and the pipeline hydrates each id to chunk text
# via the in-memory lookup built from this file. Without it,
# `/api/query` fails at container init with FileNotFoundError.
COPY --chown=app:app ingestion/data/chroma_db /app/ingestion/data/chroma_db
COPY --chown=app:app ingestion/data/bm25_index /app/ingestion/data/bm25_index
COPY --chown=app:app ingestion/data/bm25_chunk_ids.jsonl /app/ingestion/data/bm25_chunk_ids.jsonl
COPY --chown=app:app ingestion/data/chunks.jsonl /app/ingestion/data/chunks.jsonl

# Raw corpus per design.md CORP-13. Read-only at runtime; only used if
# someone triggers an in-container re-ingestion (rare/never). Could be
# excluded for a tighter image, but the spec is explicit.
COPY --chown=app:app data /app/data

# Entrypoint script. Owned by root, executable by all (the standard
# pattern: app user can run it but can't modify it).
COPY backend/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create local_data so SQLite has a place to write at runtime. Owned
# by app so the SQLite connection (running as the app user) can write.
RUN mkdir -p /app/local_data && chown -R app:app /app/local_data

USER app

EXPOSE 8000

# HEALTHCHECK lets Docker (and orchestrators like Container Apps) know
# whether the container is alive. Hits /api/health, which Batch 4
# wired as a no-deps endpoint that returns 200 if the app is up.
# Interval/timeout tuned for the 1-2 second response budget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]