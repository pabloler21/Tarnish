"""Langfuse v4 wiring: client, LangChain callback handler, tracing environment.

Verified against langfuse.com docs (Aug 2026): v4 uses `from langfuse import get_client, observe`
and `from langfuse.langchain import CallbackHandler`. The tracing environment is set via the
LANGFUSE_TRACING_ENVIRONMENT env var (pattern ^(?!langfuse)[a-z0-9-_]+$, <=40 chars)."""

from __future__ import annotations

import os
from functools import lru_cache

from langfuse import get_client
from langfuse.langchain import CallbackHandler

from .config import get_settings


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
    _configure_env()
    return get_client()


def get_callback_handler() -> CallbackHandler:
    """The LangChain/LangGraph callback handler (used from Phase 1 when the graph exists)."""
    get_langfuse()  # ensure env is configured before the handler is built
    return CallbackHandler()
