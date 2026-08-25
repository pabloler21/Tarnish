"""Langfuse v4 wiring: client, LangChain callback handler, tracing environment.

Optional and off by default: a trace holds the system prompt, the payloads that worked and
the unfixed vulnerabilities — a dossier on how to attack you. Nothing leaves the machine
unless both keys are set.

Verified against langfuse.com docs (Aug 2026): v4 uses `from langfuse import get_client, observe`
and `from langfuse.langchain import CallbackHandler`. The tracing environment is set via the
LANGFUSE_TRACING_ENVIRONMENT env var (pattern ^(?!langfuse)[a-z0-9-_]+$, <=40 chars)."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from langfuse import get_client
from langfuse.langchain import CallbackHandler

from .config import get_settings


def _settings_keys() -> tuple[str, str]:
    """Seam so tests can force the keyless path without touching real env."""
    s = get_settings()
    return s.langfuse_public_key, s.langfuse_secret_key


def tracing_enabled() -> bool:
    public, secret = _settings_keys()
    return bool(public and secret)


# @observe still spins up the SDK's global client, which logs a WARNING that it is "disabled"
# when no keys are set. Off-by-default must be silent (a warning nags; the CLI says it once at
# the end instead), so quiet the SDK's logger the moment we know tracing is off. Import-time,
# because @observe fires before any get_langfuse() call in the decorated function's body.
if not tracing_enabled():
    logging.getLogger("langfuse").setLevel(logging.ERROR)


class _NoopClient:
    """Absorbs every Langfuse call. Tracing off is the default, so this is the common path."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _configure_env() -> None:
    """Push settings into os.environ (the SDK reads env, not our Settings object).
    setdefault so real shell env vars always win over .env-derived values."""
    s = get_settings()
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", s.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", s.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", s.langfuse_host)
    os.environ.setdefault("LANGFUSE_BASE_URL", s.langfuse_host)  # both names seen across SDK versions
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", s.langfuse_tracing_environment)


@lru_cache(maxsize=1)
def get_langfuse():
    if not tracing_enabled():
        return _NoopClient()
    _configure_env()
    return get_client()


def get_callback_handler() -> CallbackHandler | None:
    """The LangChain/LangGraph callback handler. None when tracing is off."""
    if not tracing_enabled():
        return None
    get_langfuse()  # ensure env is configured before the handler is built
    return CallbackHandler()
