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
    # used by the claude_cli backend. Opus 5 (the CLI default) refuses red-team payload
    # generation via AUP safeguards; 4.8 does not. `haiku` is a cheaper/faster option.
    claude_model: str = "claude-opus-4-8"
    # The model that PLAYS the target in harness mode. Chosen for resemblance to a production
    # app, NOT for capability: a strong safety-trained model refuses injections a real
    # gpt-4o-mini would obey, and that shows up as false negatives. VOLATILE id.
    # Only honoured on the claude_cli backend (llm.get_target_model()). On openai the shared
    # gpt-4o-mini is already production-like, so that's fine as-is. On anthropic it is currently
    # NOT honoured: the target shares anthropic_model with the attacker/judge, which reproduces
    # D1's third fault (a target more injection-resistant than production).
    target_model: str = "haiku"
    anthropic_model: str = "claude-sonnet-5"  # used by the anthropic backend
    # A nested agent-CLI call carrying a RAG-assembled prompt routinely outruns a short
    # timeout; a trip kills the whole campaign, including work (e.g. the control run)
    # that already succeeded. Raise it rather than guessing a bigger constant in code.
    agent_cli_timeout: int = 600
    # best-of-N: how many times a single generated payload is delivered to the target before a
    # negative ("does not reproduce") is declared. The target is stochastic (~75% landing on
    # victim/, measured 2026-08-29), so one delivery is one Bernoulli sample and misses a real
    # vuln ~1 run in 4. (1-p)^N: at p=0.75, N=5 -> 0.1% miss. 1 = the old single-shot behaviour.
    attack_attempts: int = Field(
        default=5, validation_alias=AliasChoices("attack_attempts", "tarnish_attack_attempts")
    )
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
