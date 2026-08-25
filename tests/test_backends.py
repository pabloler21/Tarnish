"""Backend resolution order and, above all, the error when nothing is available:
a first-run user with no agent CLI and no key must be told exactly what to do."""

from __future__ import annotations

import pytest

from tarnish import backends


def _only(monkeypatch, *available: str):
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}" if name in available else None)


def _no_keys(monkeypatch):
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "", "anthropic": ""})


def test_claude_cli_wins_when_present(monkeypatch):
    _only(monkeypatch, "claude", "codex")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "claude_cli"


def test_codex_cli_is_second(monkeypatch):
    _only(monkeypatch, "codex")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "codex_cli"


def test_api_key_is_the_fallback(monkeypatch):
    _only(monkeypatch)
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "openai"


def test_explicit_override_wins(monkeypatch):
    _only(monkeypatch, "claude")
    monkeypatch.setattr(backends, "_forced_backend", lambda: "openai")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "openai"


def test_error_names_all_three_routes(monkeypatch):
    _only(monkeypatch)
    _no_keys(monkeypatch)
    with pytest.raises(backends.NoBackendAvailable) as excinfo:
        backends.resolve_backend()
    message = str(excinfo.value)
    for route in ("claude", "codex", "OPENAI_API_KEY"):
        assert route in message
