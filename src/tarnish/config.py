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

    targets_dir: str = "targets"
    checkpoint_db: str = ".tarnish/checkpoints.sqlite"


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
