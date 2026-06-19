#!/usr/bin/env bash
# Container entrypoint. Runs as the non-root `app` user (see Dockerfile).
#
# Responsibilities:
#   1. Ensure runtime directories exist (SQLite parent dir, /app/local_data).
#   2. Sanity-check that the baked-in index is actually present — if not,
#      fail loudly. A missing index means the developer ran `docker build`
#      without first running `make ingest`, which would otherwise produce
#      a backend that 500s on every query.
#   3. Print a one-line startup banner so logs are debuggable.
#   4. Exec uvicorn (replacing the shell so signals propagate cleanly to
#      Python — Ctrl-C and Docker stop both deliver SIGTERM to PID 1).
#
# Environment vars that affect behavior:
#   PORT            (default 8000) — uvicorn bind port
#   UVICORN_WORKERS (default 1)    — process workers. >1 multiplies memory
#                                    by N (ChromaDB is mmap-shared but the
#                                    in-memory ExactCache is per-process,
#                                    causing cache misses across workers).
#                                    Stick with 1 unless you understand
#                                    the trade-off.
#   LOG_LEVEL       (default info) — uvicorn log level

set -euo pipefail

PORT="${PORT:-8000}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Local SQLite dir must exist before SettingsSqliteDocumentStore opens
# the connection. Default path inside the container is
# /app/local_data/app.db (set in config.py). The mkdir is idempotent.
mkdir -p /app/local_data

# Sanity-check the baked-in indices. If any is missing, the backend
# would import fine but every retrieval would fail. Fail fast at boot.
CHROMA_DIR="/app/ingestion/data/chroma_db"
BM25_DIR="/app/ingestion/data/bm25_index"
CHUNKS_FILE="/app/ingestion/data/chunks.jsonl"

if [ ! -d "${CHROMA_DIR}" ] || [ -z "$(ls -A "${CHROMA_DIR}" 2>/dev/null)" ]; then
    echo "FATAL: ChromaDB index missing or empty at ${CHROMA_DIR}" >&2
    echo "Did you run 'make ingest' before 'docker build'?" >&2
    exit 1
fi

if [ ! -d "${BM25_DIR}" ] || [ -z "$(ls -A "${BM25_DIR}" 2>/dev/null)" ]; then
    echo "FATAL: BM25 index missing or empty at ${BM25_DIR}" >&2
    echo "Did you run 'make ingest' before 'docker build'?" >&2
    exit 1
fi

if [ ! -s "${CHUNKS_FILE}" ]; then
    echo "FATAL: chunks.jsonl missing or empty at ${CHUNKS_FILE}" >&2
    echo "This file is needed to hydrate retrieved chunk_ids to text." >&2
    echo "Did you run 'make ingest' before 'docker build'?" >&2
    exit 1
fi

echo "[entrypoint] starting uvicorn: host=0.0.0.0 port=${PORT} workers=${UVICORN_WORKERS}"

# exec replaces the shell process with uvicorn so PID 1 IS uvicorn.
# Without exec, the shell would catch SIGTERM and uvicorn would never
# see it -> Docker waits 10s for graceful shutdown, then SIGKILLs.
exec uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${UVICORN_WORKERS}" \
    --log-level "${LOG_LEVEL}" \
    --no-access-log