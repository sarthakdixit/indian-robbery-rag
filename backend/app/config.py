"""Application configuration via pydantic-settings.

All runtime configuration — env vars, file paths, model names, thresholds —
flows through this `Settings` class. Per AGENT.md §8, no other module reads
`os.environ` directly. Tests override settings by constructing `Settings`
with explicit kwargs.

Local vs cloud is a single env var (`environment`). The DI container reads
it to pick local-vs-cloud adapters; the rest of the code is environment-
agnostic.

Secret values use Pydantic's `SecretStr` so they don't accidentally print
in logs or error tracebacks. Callers retrieve plaintext with
`settings.gemini_api_key.get_secret_value()`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# The corpus version is a single source of truth for cache invalidation,
# replicated from sources.yaml at ingestion time onto every chunk and cache
# entry. Bumping it in sources.yaml + re-running ingestion invalidates all
# caches implicitly because cached corpus_version no longer matches.
#
# This module-level constant tracks the current value the backend was built
# against. The backend will refuse to serve answers whose retrieved chunks
# carry a different corpus_version than this constant — protects against
# index/code skew during deploys.
CORPUS_VERSION: str = "2026.05.14"


# Project root resolved relative to this file: backend/app/config.py
# -> backend/app -> backend -> <repo root>
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Backend runtime configuration.

    Reads from environment variables; in local development from a `.env`
    file at the repo root. Cloud deployments inject env vars from
    Key Vault references.
    """

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
    )

    # --- Environment switch -----------------------------------------------
    environment: Literal["local", "cloud"] = "local"

    # --- Secrets ----------------------------------------------------------
    gemini_api_key: SecretStr

    # --- Gemini models ----------------------------------------------------
    # Models are pinned here, not in random per-module constants, because
    # any of them could change (deprecation has bitten us twice already).
    # Bumping a model triggers a single-line change here plus re-evaluation
    # against the eval set, rather than a hunt across modules.
    gemini_generation_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 768

    # --- Index paths ------------------------------------------------------
    # Default points at the ingestion pipeline's output directory. Tests
    # override with a temp dir; production with the path baked into the
    # Docker image.
    chroma_db_dir: Path = Field(default=_REPO_ROOT / "ingestion" / "data" / "chroma_db")
    bm25_index_dir: Path = Field(default=_REPO_ROOT / "ingestion" / "data" / "bm25_index")
    bm25_chunk_ids_path: Path = Field(
        default=_REPO_ROOT / "ingestion" / "data" / "bm25_chunk_ids.jsonl"
    )
    chunks_jsonl_path: Path = Field(
        default=_REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
    )

    # --- ChromaDB collection ----------------------------------------------
    chroma_collection_name: str = "robbery_corpus"

    # --- Retrieval tuning -------------------------------------------------
    # These are the user-tunable retrieval knobs. Domain thresholds (scope
    # rejection similarity, semantic cache threshold) live in per-package
    # `constants.py` per AGENT.md §15, not here.
    retrieval_top_k: int = 20
    retrieval_final_k: int = 5

    # --- HTTP / lifecycle (Batch 4 will use these) ------------------------
    request_timeout_seconds: float = 30.0


def get_settings() -> Settings:
    """Return a Settings instance.

    Stateless — callers should hold a single instance for the process
    lifetime. The DI container constructs one and passes it everywhere.
    Reading this each call is wasteful but cheap; if it becomes a hotspot,
    cache with `functools.lru_cache`.
    """
    return Settings()  # type: ignore[call-arg]