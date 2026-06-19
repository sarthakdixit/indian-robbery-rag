# Makefile for the Indian Robbery Law RAG Assistant — backend.
#
# Most targets work regardless of where `make` is invoked from (e.g.,
# `make -C backend dev` from the repo root, or `cd backend && make dev`).
# Internally we resolve paths against `$(REPO_ROOT)` which is computed
# relative to this Makefile's location.
#
# Headline targets (the ones a contributor cares about):
#   make dev            — start uvicorn locally with auto-reload
#   make docker-build   — build the production container image
#   make docker-run     — run the container locally with sane defaults
#   make ingest         — re-run the offline ingestion pipeline
#   make test           — pytest the backend
#   make check          — full pre-commit gate (ruff + mypy + pytest)
#
# Required local setup before any of these:
#   1. Python 3.11+ in a venv (the repo's .venv is gitignored)
#   2. .env at repo root (copy from .env.example, fill in GEMINI_API_KEY)
#   3. `make ingest` run once to produce the local indices

# --- Path resolution --------------------------------------------------
# GNU Make's $(realpath) and $(dir) split on whitespace, which breaks
# any path containing a space (e.g., "RAG Crime/"). We use shell-side
# resolution instead — `$(shell ...)` invokes the shell once at parse
# time and the result is a single string that Make treats opaquely.
#
# The dollar-shell idiom: `$(shell cd $(dir1) && pwd)` returns the
# absolute path of dir1, quoted-safe because pwd never emits spaces
# as separators. We still must quote $(REPO_ROOT) at use sites because
# Make passes it to /bin/sh unquoted by default.
BACKEND_DIR := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" 2>/dev/null && pwd)
REPO_ROOT := $(shell cd "$(BACKEND_DIR)/.." 2>/dev/null && pwd)

# Image tag for the container builds. The `:dev` suffix distinguishes
# local builds from any CI-tagged images.
IMAGE_TAG ?= robbery-rag-backend:dev

# Host port to expose. 8001 because 8000 may be in use during local dev
# (your uvicorn from `make dev` likely runs on 8000).
HOST_PORT ?= 8001

# Default uvicorn port inside the container.
CONTAINER_PORT ?= 8000

# Python interpreter. Override with PYTHON=/path/to/python if needed.
PYTHON ?= python3

.PHONY: help dev docker-build docker-run docker-stop ingest ingest-full \
        ingest-embed test test-smoke install-dev _check-pytest \
        lint format check clean clean-sqlite docker-clean

help:
	@echo "Targets:"
	@echo "  dev            — uvicorn on :8000 with auto-reload"
	@echo "  docker-build   — build $(IMAGE_TAG) from repo root"
	@echo "  docker-run     — run $(IMAGE_TAG), expose on :$(HOST_PORT)"
	@echo "  docker-stop    — stop the running container (if any)"
	@echo "  ingest         — run the offline ingestion pipeline"
	@echo "  install-dev    — install dev deps (pytest, ruff, mypy)"
	@echo "  test           — run all pytest tests"
	@echo "  test-smoke     — run just the smoke tests"
	@echo "  lint           — ruff check + mypy (no fixes)"
	@echo "  format         — ruff format"
	@echo "  check          — full pre-commit gate (lint + format check + tests)"
	@echo "  clean          — wipe local SQLite + __pycache__"
	@echo "  clean-sqlite   — wipe just the local SQLite database"
	@echo "  docker-clean   — remove $(IMAGE_TAG)"

# ---------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------

# `make dev` runs uvicorn directly on the host. Reads .env automatically
# via pydantic-settings. `--reload` is convenient but adds a watcher
# process; turn it off (set RELOAD= empty) for benchmarking.
RELOAD ?= --reload
PORT ?= 8000

dev:
	cd "$(REPO_ROOT)" && $(PYTHON) -m uvicorn backend.app.main:app \
		--host 127.0.0.1 \
		--port $(PORT) \
		$(RELOAD)

# ---------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------

# Build context is the repo root (the Dockerfile references both
# `backend/` and `ingestion/data/`). The `-f` flag points at the
# Dockerfile in this directory.
docker-build:
	cd "$(REPO_ROOT)" && docker build -f backend/Dockerfile -t $(IMAGE_TAG) .

# Run with the env vars the container needs. GEMINI_API_KEY MUST be set
# in your shell (or .env, but docker env-passing requires `--env-file`).
docker-run:
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "ERROR: GEMINI_API_KEY not set in shell environment."; \
		echo "Either export it, or use: docker compose -f $(BACKEND_DIR)docker-compose.yml up"; \
		exit 1; \
	fi
	docker run --rm \
		--name robbery-rag-backend \
		-p $(HOST_PORT):$(CONTAINER_PORT) \
		-e GEMINI_API_KEY="$$GEMINI_API_KEY" \
		-e ADMIN_PASSWORD="$${ADMIN_PASSWORD:-local-dev-admin-changeme}" \
		-v "$(REPO_ROOT)/local_data":/app/local_data \
		$(IMAGE_TAG)

docker-stop:
	@docker stop robbery-rag-backend 2>/dev/null || echo "no running container"

docker-clean:
	@docker rmi $(IMAGE_TAG) 2>/dev/null || echo "$(IMAGE_TAG) not present"

# ---------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------

# Run the full ingestion pipeline. Skips classify (interactive) and
# embed (rate-limited daily quota) by default — pass these targets
# only when needed.
ingest:
	cd "$(REPO_ROOT)" && $(PYTHON) -m ingestion.run_ingestion --skip classify --skip embed

ingest-full:
	cd "$(REPO_ROOT)" && $(PYTHON) -m ingestion.run_ingestion

ingest-embed:
	cd "$(REPO_ROOT)" && $(PYTHON) -m ingestion.embed.embed_chunks

# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

test: _check-pytest
	cd "$(REPO_ROOT)" && $(PYTHON) -m pytest backend/tests/ -v

test-smoke: _check-pytest
	cd "$(REPO_ROOT)" && $(PYTHON) -m pytest backend/tests/test_smoke.py -v

# Install dev dependencies (pytest, ruff, mypy). Run once after cloning.
install-dev:
	cd "$(REPO_ROOT)" && $(PYTHON) -m pip install -r backend/requirements-dev.txt

# Internal: bail with a useful message if pytest is missing.
_check-pytest:
	@$(PYTHON) -c "import pytest" 2>/dev/null || ( \
		echo "ERROR: pytest not installed in $(PYTHON)."; \
		echo "Run: make install-dev"; \
		exit 1 )

# ---------------------------------------------------------------------
# Lint / format / check
# ---------------------------------------------------------------------

lint:
	cd "$(REPO_ROOT)" && ruff check backend/
	cd "$(REPO_ROOT)" && mypy backend/

format:
	cd "$(REPO_ROOT)" && ruff format backend/

# The pre-commit gate per AGENT.md §14.3. Run this before any commit
# touching backend/.
check:
	cd "$(REPO_ROOT)" && ruff check backend/
	cd "$(REPO_ROOT)" && ruff format --check backend/
	cd "$(REPO_ROOT)" && mypy backend/
	cd "$(REPO_ROOT)" && $(PYTHON) -m pytest backend/tests/ -x

# ---------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------

# Wipe local SQLite — useful when rate limit state or stale logs are
# getting in the way of testing. Does NOT touch the corpus/indices.
clean-sqlite:
	rm -f "$(REPO_ROOT)/local_data/app.db"
	@echo "removed $(REPO_ROOT)/local_data/app.db"

# Full cleanup of dev artifacts. Indices are preserved (slow to rebuild).
clean: clean-sqlite
	find "$(REPO_ROOT)/backend" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find "$(REPO_ROOT)/backend" -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned pycache + pytest_cache under backend/"