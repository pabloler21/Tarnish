"""`init` = a bounded repo scan + one structured LLM call. The scan is pure and tested against
victim/; the LLM call is faked, because profile *quality* is not a unit-test target."""

from __future__ import annotations

import json

import pytest

from tarnish import recon
from tarnish.authz import AuthorizationError, assert_authorized
from tarnish.schemas import PromptRef, RepoProfile, Surface, ToolSpec


def test_candidate_files_finds_the_victim_sources():
    files = [p.as_posix() for p in recon.candidate_files("victim")]
    assert any(f.endswith("src/bot.ts") for f in files)
    assert any(f.endswith("src/tools.ts") for f in files)
    assert not any(f.endswith(".json") for f in files)


def test_candidate_files_skips_vendored_directories(tmp_path):
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.ts").write_text("const systemPrompt = 1")
    (tmp_path / "app.ts").write_text("const SYSTEM_PROMPT = 'you are a bot'")
    assert [p.name for p in recon.candidate_files(tmp_path)] == ["app.ts"]


class _FakeModel:
    """Scripted responder: no network, no subprocess."""

    def __init__(self, profile):
        self.profile, self.prompt = profile, ""

    def with_structured_output(self, schema, **kwargs):
        outer = self

        class _Runnable:
            def invoke(self, messages):
                outer.prompt = "\n".join(str(m) for m in messages)
                return outer.profile

        return _Runnable()


def _fake_profile() -> RepoProfile:
    return RepoProfile(
        id="wrong", name="wrong", root="/somewhere/hallucinated", language="typescript",
        surfaces=[Surface(file="src/bot.ts", line=18, symbol="handleMessage", kind="chat_input")],
        system_prompt=PromptRef(file="src/bot.ts", line=7, text="You are Acme Support."),
        tools=[ToolSpec(name="refundOrder", file="src/tools.ts", line=4, side_effect=True)],
        domain_vocabulary=["refund", "order"],
    )


def test_profile_repo_overrides_the_models_guess_at_identity(monkeypatch):
    fake = _FakeModel(_fake_profile())
    monkeypatch.setattr(recon, "get_chat_model", lambda **kw: fake)

    profile = recon.profile_repo("victim")

    # The model may hallucinate root/id/name; those are facts we know, so we overwrite them.
    assert profile.root.endswith("victim") and profile.id == "victim" and profile.name == "victim"
    assert profile.surfaces[0].symbol == "handleMessage"
    assert "SYSTEM_PROMPT" in fake.prompt, "the scanned source must reach the model"


def test_write_and_load_profile_round_trip(tmp_path):
    profile = _fake_profile().model_copy(
        update={"id": "victim", "name": "victim", "root": str(tmp_path)})
    path = recon.write_profile(profile)

    assert path == tmp_path / ".tarnish" / "profile.json"
    assert json.loads(path.read_text())["id"] == "victim"
    # init writes its own .gitignore, or the first user commits 40MB of Chroma.
    ignored = (tmp_path / ".tarnish" / ".gitignore").read_text()
    assert "chroma/" in ignored and "checkpoints.sqlite" in ignored
    assert recon.load_profile(tmp_path).surfaces[0].kind == "chat_input"


def test_authorization_rejects_a_repo_outside_the_working_directory(tmp_path):
    outside = _fake_profile().model_copy(update={"root": str(tmp_path.parent / "not-mine")})
    with pytest.raises(AuthorizationError):
        assert_authorized(outside)


def test_authorization_accepts_the_checkout_you_are_standing_in():
    assert_authorized(_fake_profile().model_copy(update={"root": "victim"}))  # no raise
