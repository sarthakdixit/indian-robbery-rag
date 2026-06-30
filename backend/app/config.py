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
from typing import Annotated, Literal
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
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
    # --- Salt for IP hashing ----------------------------------------------
    # Used by RequestContextMiddleware to compute hashed_ip = SHA-256(salt:ip).
    # The default value here is committed to the repo, which is fine because
    # the salt's purpose is only to prevent trivial rainbow-table lookups of
    # IP -> hash by external parties, not to be cryptographically secret.
    # For cloud deployments, override via the IP_HASH_SALT env var (read from
    # Key Vault). For local dev, the default suffices.
    ip_hash_salt: SecretStr = SecretStr("local-dev-salt-replace-in-cloud")
    # --- Turnstile -------------------------------------------------------
    # Server-side secret paired with the frontend's site key. For
    # production, set via env var (TURNSTILE_SECRET_KEY) populated from
    # Key Vault. For local dev, Cloudflare's documented "always passes"
    # test key is the default — this lets the CloudflareTurnstileVerifier
    # be exercised locally if needed, without any account setup.
    # See https://developers.cloudflare.com/turnstile/troubleshooting/testing/
    turnstile_secret_key: SecretStr = SecretStr(
        "1x0000000000000000000000000000000AA",
    )
    # --- Telemetry -------------------------------------------------------
    # Application Insights connection string is only used in cloud mode.
    # The local default is a placeholder; cloud deploy must set it via
    # env var APP_INSIGHTS_CONNECTION_STRING (or AZ_KEY_VAULT in Batch 7).
    app_insights_connection_string: str = "InstrumentationKey=local-stub-not-used"
    # --- Cosmos DB (cloud mode only) -------------------------------------
    # Connection string format: AccountEndpoint=...;AccountKey=...
    # In Container Apps, this gets injected from a Key Vault reference.
    # The local default is a placeholder that the cloud adapters refuse
    # to connect with (fail loudly rather than try the placeholder).
    cosmos_connection_string: SecretStr = SecretStr(
        "AccountEndpoint=https://local-stub.documents.azure.com:443/;AccountKey=local-stub",
    )
    cosmos_database_name: str = "robbery-rag"
    cosmos_container_name: str = "documents"
    # --- Admin dashboard ------------------------------------------------
    # Single shared password gating `/api/admin/*`. Not real auth — see
    # AdminAuth class docstring for the threat model. For local dev the
    # default is readable; cloud deploy MUST override via env var
    # ADMIN_PASSWORD (sourced from Key Vault in Batch 7).
    admin_password: SecretStr = SecretStr("local-dev-admin-changeme")
    # --- Local persistence -------------------------------------------------
    # SQLite file backing the local DocumentStore (rate limits, global
    # counters, query log when wired up in Batch 4.4). Production swaps to
    # Cosmos via the DI container's Selector.
    sqlite_path: Path = Field(default=_REPO_ROOT / "local_data" / "app.db")
    # --- Rate limiting & cap -----------------------------------------------
    # design.md FR-5 / §4 AP-2,AP-3. Numbers chosen to keep the demo from
    # burning the Gemini free tier in a single afternoon while still being
    # usable by a few interested visitors.
    per_ip_daily_query_limit: int = 5
    global_daily_query_cap: int = 200
    # Circuit breaker (local LLM call counter). Set below the Gemini free
    # tier ceiling so we self-throttle BEFORE hitting Gemini's 429s.
    local_llm_daily_limit: int = 180

    # --- CORS ----------------------------------------------------------
    # Allowed origins for the browser frontend. Read from env var
    # CORS_ALLOWED_ORIGINS as a comma-separated string; the validator
    # below splits it into a list. Local dev defaults to the Vite
    # ports; cloud deploys set this via Container Apps env to include
    # the SWA URL (see infra/main.bicep). FastAPI's CORSMiddleware
    # requires exact origins — wildcards in allow_origins are NOT
    # supported (only "*" for everything, which we don't want).
    #
    # The Annotated[..., NoDecode] is REQUIRED. Without it,
    # pydantic-settings tries to json.loads() the env var string
    # BEFORE our field_validator runs, and throws JSONDecodeError on
    # the comma-separated input. NoDecode tells pydantic-settings to
    # hand the raw string straight to the validator.
    # Docs: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/#disabling-json-parsing
    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """Accept either a comma-separated string (from env vars) or a list.

        With NoDecode on the field, pydantic-settings hands us the raw
        env var string. We split on commas, strip whitespace, drop empty
        pieces. List inputs (default value, programmatic construction
        in tests) pass through unchanged.
        """
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v
def get_settings() -> Settings:
    """Return a Settings instance.
    Stateless — callers should hold a single instance for the process
    lifetime. The DI container constructs one and passes it everywhere.
    Reading this each call is wasteful but cheap; if it becomes a hotspot,
    cache with `functools.lru_cache`.
    """
    return Settings()  # type: ignore[call-arg]