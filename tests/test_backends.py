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


from tarnish.agent_cli import AgentCliChatModel  # noqa: E402
from tarnish.llm import get_chat_model  # noqa: E402


def test_get_chat_model_returns_the_cli_model_when_a_cli_is_present(monkeypatch):
    _only(monkeypatch, "claude")
    monkeypatch.setattr(backends, "_forced_backend", lambda: "")
    model = get_chat_model(temperature=0)
    assert isinstance(model, AgentCliChatModel)
    # The model is pinned (Opus 5 refuses attack-gen via AUP); id is volatile, so don't couple.
    assert model.argv[:2] == ["claude", "-p"]
    assert "--model" in model.argv


def test_get_chat_model_falls_back_to_openai(monkeypatch):
    _only(monkeypatch)
    monkeypatch.setattr(backends, "_forced_backend", lambda: "")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert type(get_chat_model()).__name__ == "ChatOpenAI"


def test_get_chat_model_uses_anthropic_when_only_that_key_is_set(monkeypatch):
    """The no-backend error promises ANTHROPIC_API_KEY as a route, so it must work."""
    _only(monkeypatch)
    monkeypatch.setattr(backends, "_forced_backend", lambda: "")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "", "anthropic": "sk-ant-x"})
    assert type(get_chat_model()).__name__ == "ChatAnthropic"


def test_codex_argv_allows_running_outside_a_git_repo():
    """We run the CLI from a neutral temp dir, and codex refuses to start outside a git repo
    without this flag."""
    from tarnish.backends import ARGV

    assert "--skip-git-repo-check" in ARGV["codex_cli"]


def test_attacker_backend_prefers_api_key_over_codex(monkeypatch):
    """Regression coverage for the 2026-08-28 measurement: codex (gpt-5.5) refuses attack-gen
    too, on the same prompt claude also refuses. An API key must win over codex even when codex
    is on PATH — this is the test that would have caught the old codex-first ordering."""
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "")
    monkeypatch.setattr(b.shutil, "which", lambda name: f"/usr/bin/{name}")  # both CLIs on PATH
    monkeypatch.setattr(b, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})

    assert b.resolve_attacker_backend() == "openai"


def test_attacker_backend_prefers_openai_over_anthropic(monkeypatch):
    """Same tie-break as the general _api_key_backend() helper: openai first."""
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "")
    monkeypatch.setattr(b.shutil, "which", lambda name: None)
    monkeypatch.setattr(b, "_api_keys", lambda: {"openai": "sk-x", "anthropic": "sk-ant-x"})

    assert b.resolve_attacker_backend() == "openai"


def test_attacker_backend_uses_codex_when_no_key_is_set(monkeypatch):
    """No API key, but codex is on PATH: codex still refuses the payload-gen prompt (measured
    2026-08-28), but it is keyless and offers a benign alternative, so it stays ahead of claude
    among the two agent CLIs."""
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "")
    monkeypatch.setattr(b.shutil, "which", lambda name: f"/usr/bin/{name}")  # both CLIs on PATH
    monkeypatch.setattr(b, "_api_keys", lambda: {"openai": "", "anthropic": ""})

    assert b.resolve_attacker_backend() == "codex_cli"


def test_attacker_backend_falls_to_claude_only_when_alone(monkeypatch):
    """claude is the last resort — it will refuse, and the caller warns, but it is better than
    NoBackendAvailable."""
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "")
    monkeypatch.setattr(b.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(b, "_api_keys", lambda: {"openai": "", "anthropic": ""})

    assert b.resolve_attacker_backend() == "claude_cli"


def test_attacker_backend_respects_a_forced_choice(monkeypatch):
    """An explicit TARNISH_LLM_BACKEND wins for every role, attacker included."""
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "anthropic")
    assert b.resolve_attacker_backend() == "anthropic"


def test_attacker_backend_raises_when_nothing_is_available(monkeypatch):
    import tarnish.backends as b

    monkeypatch.setattr(b, "_forced_backend", lambda: "")
    monkeypatch.setattr(b.shutil, "which", lambda name: None)
    monkeypatch.setattr(b, "_api_keys", lambda: {"openai": "", "anthropic": ""})

    import pytest
    with pytest.raises(b.NoBackendAvailable):
        b.resolve_attacker_backend()
