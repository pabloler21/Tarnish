"""Three roles, three factories. `get_chat_model()` is the GENERAL model (judge, remediation,
recon); `get_target_model()` plays the target and needs to resemble what runs in production;
`get_attacker_model()` generates payloads and needs a backend that will not refuse. Serving all
three from one factory pinned the target to the most injection-resistant model we have.

Tests named for the general model must not be read as attacker coverage — that mislabelling is
why the attacker path has its own assertions at the bottom of this file."""

from __future__ import annotations

import pytest

from tarnish import llm
from tarnish.agent_cli import AgentCliChatModel


@pytest.fixture(autouse=True)
def _claude_backend(monkeypatch):
    monkeypatch.setattr(llm, "resolve_backend", lambda: "claude_cli")


def test_target_model_differs_from_the_general_model():
    general = llm.get_chat_model()
    target = llm.get_target_model()

    assert isinstance(general, AgentCliChatModel) and isinstance(target, AgentCliChatModel)
    assert general.argv[general.argv.index("--model") + 1] == "claude-opus-4-8"
    assert target.argv[target.argv.index("--model") + 1] == "haiku"


def test_target_model_carries_a_real_system_prompt_channel():
    target = llm.get_target_model()

    assert target.system_flag == "--system-prompt"
    assert "--exclude-dynamic-system-prompt-sections" in target.argv
    assert target.temperature == 0


def test_general_model_keeps_no_system_flag():
    """Only the target needs a privilege boundary; judging and remediation just generate text."""
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


def test_attacker_model_uses_the_generating_backend(monkeypatch):
    """The attacker resolves via resolve_attacker_backend, not resolve_backend, so a claude
    machine with codex present generates on codex instead of refusing on claude."""
    from tarnish import llm
    from tarnish.agent_cli import AgentCliChatModel

    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "codex_cli")
    m = llm.get_attacker_model()

    assert isinstance(m, AgentCliChatModel)
    assert m.argv[:2] == ["codex", "exec"]
    assert m.system_flag is None  # codex has no system channel; not needed for generation


def test_attacker_can_generate_is_false_for_both_agent_clis(monkeypatch):
    """Both agent CLIs refuse attack generation: claude on AUP grounds, codex (gpt-5.5) on the
    same prompt, measured 2026-08-28. Only the API backends are measured to generate."""
    from tarnish import llm

    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "openai")
    assert llm.attacker_can_generate() is True

    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "anthropic")
    assert llm.attacker_can_generate() is True

    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "codex_cli")
    assert llm.attacker_can_generate() is False

    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "claude_cli")
    assert llm.attacker_can_generate() is False


def test_attacker_model_pins_the_model_on_the_claude_branch(monkeypatch):
    """The claude-branch model pinning above covers get_chat_model, not the attacker. When the
    attacker falls back to claude (last resort, no API key), it must still pin the model id
    rather than inherit Claude Code's default, which refuses hardest of all."""
    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "claude_cli")
    attacker = llm.get_attacker_model()

    assert isinstance(attacker, AgentCliChatModel)
    assert attacker.argv[attacker.argv.index("--model") + 1] == "claude-opus-4-8"


def test_attacker_keeps_no_system_flag_on_the_claude_branch(monkeypatch):
    """Generation needs no privilege boundary, so the attacker carries no system flag even on
    the one backend that has one. Pinned on the real get_attacker_model, not on get_chat_model."""
    monkeypatch.setattr(llm, "resolve_attacker_backend", lambda: "claude_cli")

    assert llm.get_attacker_model().system_flag is None
