"""Which LLM backend to use, resolved once per process.

Order is deliberate: the agent CLIs come first because they draw on a subscription the
developer already pays for, so a keyless first run works. API keys are the CI path."""

from __future__ import annotations

import shutil
from typing import Literal

from .config import get_settings

Backend = Literal["claude_cli", "codex_cli", "openai", "anthropic"]

# How to invoke each CLI backend. The prompt is appended by agent_cli.py.
ARGV: dict[str, list[str]] = {
    "claude_cli": ["claude", "-p"],
    "codex_cli": ["codex", "exec"],
}

_CLI_EXECUTABLE: dict[str, str] = {"claude_cli": "claude", "codex_cli": "codex"}


class NoBackendAvailable(RuntimeError):
    """No agent CLI on PATH and no API key. The message must be actionable."""


def _api_keys() -> dict[str, str]:
    s = get_settings()
    return {"openai": s.openai_api_key, "anthropic": s.anthropic_api_key}


def _forced_backend() -> str:
    return get_settings().llm_backend


def resolve_backend() -> Backend:
    forced = _forced_backend()
    if forced:
        return forced  # type: ignore[return-value]

    for backend, executable in _CLI_EXECUTABLE.items():
        if shutil.which(executable):
            return backend  # type: ignore[return-value]

    keys = _api_keys()
    for backend in ("openai", "anthropic"):
        if keys.get(backend):
            return backend  # type: ignore[return-value]

    # ASCII only: this is printed to a terminal, and a Windows cp1252 console mangles the rest.
    raise NoBackendAvailable(
        "Tarnish needs a model. Pick one:\n"
        "  1. Claude Code   install it, then `claude login` (uses your Claude plan)\n"
        "  2. Codex         install it, then `codex login` (uses your ChatGPT plan)\n"
        "  3. An API key    set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env\n"
        "Then run this command again."
    )
