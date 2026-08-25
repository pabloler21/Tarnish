"""The subprocess contract. The model is a seam: every caller keeps talking LangChain."""

from __future__ import annotations

import subprocess

import pytest
from pydantic import BaseModel

from tarnish.agent_cli import AgentCliChatModel


class _Reply(BaseModel):
    verdict: bool
    reason: str


def _fake_run(stdout: str, returncode: int = 0, calls: list | None = None):
    def run(*args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")
    return run


def test_generate_returns_stdout_as_message(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("  PONG  \n"))
    model = AgentCliChatModel(argv=["fake-cli"])

    assert model.invoke([("human", "ping")]).content == "PONG"


def test_prompt_goes_over_stdin_not_argv(monkeypatch):
    """A RAG-assembled prompt can exceed the OS argv limit (~32k on Windows)."""
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _fake_run("ok", calls=calls))
    AgentCliChatModel(argv=["fake-cli", "-p"]).invoke([("human", "ping")])

    (argv,), kwargs = calls[0]
    assert argv[1:] == ["-p"]
    assert "ping" in kwargs["input"]


def test_executable_is_resolved_to_an_absolute_path(monkeypatch):
    """Windows CreateProcess ignores PATHEXT, so a bare `codex` (a .CMD shim) raises
    FileNotFoundError. Resolving via shutil.which is what makes the codex backend work."""
    import tarnish.agent_cli as ac

    calls: list = []
    monkeypatch.setattr(subprocess, "run", _fake_run("ok", calls=calls))
    monkeypatch.setattr(ac.shutil, "which", lambda name: rf"C:\bin\{name}.CMD")
    AgentCliChatModel(argv=["codex", "exec"]).invoke([("human", "ping")])

    assert calls[0][0][0][0] == r"C:\bin\codex.CMD"


def test_nonzero_exit_raises_with_the_command_named(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("", returncode=2))
    model = AgentCliChatModel(argv=["fake-cli"])

    with pytest.raises(RuntimeError, match="fake-cli"):
        model.invoke([("human", "ping")])


def test_structured_output_parses_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run('{"verdict": true, "reason": "canary echoed"}'))
    model = AgentCliChatModel(argv=["fake-cli"])

    result = model.with_structured_output(_Reply).invoke([("human", "judge this")])

    assert result.verdict is True
    assert result.reason == "canary echoed"


def test_structured_output_tolerates_a_fenced_block(monkeypatch):
    fenced = '```json\n{"verdict": false, "reason": "control matched"}\n```'
    monkeypatch.setattr(subprocess, "run", _fake_run(fenced))
    model = AgentCliChatModel(argv=["fake-cli"])

    assert model.with_structured_output(_Reply).invoke([("human", "judge this")]).verdict is False
