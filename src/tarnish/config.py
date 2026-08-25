"""Typed config (pydantic-settings) and target-profile loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schemas import TargetProfile


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Langfuse (Tarnish's own project, separate from anything the target uses).
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Accept either LANGFUSE_HOST or LANGFUSE_BASE_URL (region matters: EU vs US cloud).
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )
    langfuse_tracing_environment: str = "redteam"

    # LLMs (attacker / judge / remediation). Backend is auto-detected: agent CLI first,
    # API key as the fallback. See backends.resolve_backend.
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # "" = auto-detect (see backends.resolve_backend). Set to force one:
    # claude_cli | codex_cli | openai | anthropic
    llm_backend: str = Field(
        default="", validation_alias=AliasChoices("llm_backend", "tarnish_llm_backend")
    )
    llm_model: str = "gpt-4o-mini"          # used by the openai backend
    anthropic_model: str = "claude-sonnet-5"  # used by the anthropic backend
    # fastembed model id (local, keyless). 384 dims — changing it invalidates .tarnish/chroma.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    targets_dir: str = "targets"
    checkpoint_db: str = ".tarnish/checkpoints.sqlite"
    chroma_dir: str = ".tarnish/chroma"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_target(target_id: str, targets_dir: str | None = None) -> TargetProfile:
    """Load a target profile from targets/<id>.yaml. Adding a target is config, not code."""
    base = Path(targets_dir or get_settings().targets_dir)
    path = base / f"{target_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Target profile not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TargetProfile(**data)
