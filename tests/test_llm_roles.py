"""The target role is not the attacker role. The attacker needs a model that will generate a
red-team payload; the target needs one that resembles what runs in production. Serving both
from one factory pinned the target to the most injection-resistant model we have."""

from __future__ import annotations

import pytest

from tarnish import llm
from tarnish.agent_cli import AgentCliChatModel


@pytest.fixture(autouse=True)
def _claude_backend(monkeypatch):
    monkeypatch.setattr(llm, "resolve_backend", lambda: "claude_cli")


def test_target_model_differs_from_the_attacker_model():
    attacker = llm.get_chat_model()
    target = llm.get_target_model()

    assert isinstance(attacker, AgentCliChatModel) and isinstance(target, AgentCliChatModel)
    assert attacker.argv[attacker.argv.index("--model") + 1] == "claude-opus-4-8"
    assert target.argv[target.argv.index("--model") + 1] == "haiku"


def test_target_model_carries_a_real_system_prompt_channel():
    target = llm.get_target_model()

    assert target.system_flag == "--system-prompt"
    assert "--exclude-dynamic-system-prompt-sections" in target.argv
    assert target.temperature == 0


def test_attacker_keeps_no_system_flag():
    """Only the target needs a privilege boundary; the attacker is just generating text."""
    assert llm.get_chat_model().system_flag is None


def test_claude_argv_never_loads_project_settings():
    """--setting-sources "" stops CLAUDE.md (project AND user) reaching any role."""
    from tarnish.backends import ARGV

    assert ARGV["claude_cli"][-2:] == ["--setting-sources", ""]


def test_privilege_gap_is_false_only_on_codex(monkeypatch):
    monkeypatch.setattr(llm, "resolve_backend", lambda: "claude_cli")
    assert llm.harness_has_privilege_gap() is True

    monkeypatch.setattr(llm, "resolve_backend", lambda: "openai")
    assert llm.harness_has_privilege_gap() is True

    monkeypatch.setattr(llm, "resolve_backend", lambda: "codex_cli")
    assert llm.harness_has_privilege_gap() is False
