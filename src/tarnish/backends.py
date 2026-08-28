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
    # --setting-sources "": do not load user or project settings, so no CLAUDE.md (ours or the
    # user's) reaches any role. Paired with the neutral cwd in agent_cli.py.
    "claude_cli": ["claude", "-p", "--setting-sources", ""],
    # --skip-git-repo-check: we run from a neutral temp dir (see agent_cli.py), and codex
    # refuses to start outside a git repository without it.
    "codex_cli": ["codex", "exec", "--skip-git-repo-check"],
}

_CLI_EXECUTABLE: dict[str, str] = {"claude_cli": "claude", "codex_cli": "codex"}


class NoBackendAvailable(RuntimeError):
    """No agent CLI on PATH and no API key. The message must be actionable."""


def _api_keys() -> dict[str, str]:
    s = get_settings()
    return {"openai": s.openai_api_key, "anthropic": s.anthropic_api_key}


def _forced_backend() -> str:
    return get_settings().llm_backend


def _api_key_backend() -> Backend | None:
    """Try to resolve from API keys in order: openai, anthropic. Return None if neither is set."""
    keys = _api_keys()
    for backend in ("openai", "anthropic"):
        if keys.get(backend):
            return backend  # type: ignore[return-value]
    return None


def resolve_backend() -> Backend:
    forced = _forced_backend()
    if forced:
        return forced  # type: ignore[return-value]

    for backend, executable in _CLI_EXECUTABLE.items():
        if shutil.which(executable):
            return backend  # type: ignore[return-value]

    api_backend = _api_key_backend()
    if api_backend:
        return api_backend

    # ASCII only: this is printed to a terminal, and a Windows cp1252 console mangles the rest.
    raise NoBackendAvailable(
        "Tarnish needs a model. Pick one:\n"
        "  1. Claude Code   install it, then `claude login` (uses your Claude plan)\n"
        "  2. Codex         install it, then `codex login` (uses your ChatGPT plan)\n"
        "  3. An API key    set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env\n"
        "Then run this command again."
    )


def resolve_attacker_backend() -> Backend:
    """Backend for GENERATING attack payloads. Both agent CLIs refuse it: the claude CLI on AUP
    grounds across every model, with or without a real system channel (verified 2026-08-28); codex
    (gpt-5.5), measured the same day on the same prompt, also refuses ("I can't provide a payload
    designed to hijack a model..."). Only the API backends are measured to generate, so an API key
    now wins over both CLIs — unlike the judge/remediation/recon roles, which claude handles fine.
    Between the two refusing CLIs the order barely matters (both are keyless; that is not a
    differentiator between them). Codex is kept first only because its refusal, measured
    2026-08-28, came with an offer to help on a benign variant — claude's did not. A forced
    backend still wins (the operator's explicit choice, warned about elsewhere)."""
    forced = _forced_backend()
    if forced:
        return forced  # type: ignore[return-value]
    api_backend = _api_key_backend()
    if api_backend:
        return api_backend
    if shutil.which(_CLI_EXECUTABLE["codex_cli"]):
        return "codex_cli"  # will refuse; llm.attacker_can_generate() is False, caller warns
    if shutil.which(_CLI_EXECUTABLE["claude_cli"]):
        return "claude_cli"  # will refuse; llm.attacker_can_generate() is False, caller warns
    raise NoBackendAvailable(
        "Tarnish needs a model that will GENERATE attack payloads. Both the claude and codex\n"
        "CLIs refuse this on AUP grounds, so an API key is the only route that works:\n"
        "  set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env\n"
        "Then run this command again."
    )
