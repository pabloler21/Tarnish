"""Langfuse is opt-in: a trace holds the system prompt, working payloads and unfixed
vulnerabilities, so it must never leave the machine unless the operator asks."""

from __future__ import annotations

import tarnish.langfuse_setup as ls


def _clear_caches():
    ls.get_langfuse.cache_clear()
    from tarnish.config import get_settings
    get_settings.cache_clear()


def test_tracing_disabled_without_keys(monkeypatch):
    for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ls, "_settings_keys", lambda: ("", ""))
    _clear_caches()

    assert ls.tracing_enabled() is False
    client = ls.get_langfuse()
    # A no-op must absorb every call the codebase makes, without raising.
    client.update_current_span(input={"a": 1}, output={"b": 2}, metadata={})
    client.flush()
    assert ls.get_callback_handler() is None


def test_tracing_enabled_with_keys(monkeypatch):
    monkeypatch.setattr(ls, "_settings_keys", lambda: ("pk-lf-test", "sk-lf-test"))
    _clear_caches()

    assert ls.tracing_enabled() is True
