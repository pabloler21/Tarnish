"""Test the explore CLI command, especially warning messages."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tarnish import cli
from tarnish.schemas import CampaignResult, PromptRef, RepoProfile, TargetProfile


def test_explore_warns_when_attacker_cannot_generate_in_harness_mode(tmp_path, monkeypatch):
    """When the attacker backend is the refusing claude CLI, explore must warn the user that
    the campaign will find nothing — even in harness mode. The warning must appear for both
    harness and --live modes since payload generation happens in both."""
    # Setup: stub all the external dependencies that explore calls
    (tmp_path / ".tarnish").mkdir()
    profile = RepoProfile(
        id="test",
        name="test",
        root=str(tmp_path),
        language="python",
        system_prompt=PromptRef(file="test.py", line=1, text="You are helpful"),
    )
    (tmp_path / ".tarnish" / "profile.json").write_text(profile.model_dump_json(), encoding="utf-8")

    # Stub recon.load_profile to return our profile
    def _load_profile(root):
        return profile

    monkeypatch.setattr("tarnish.cli.recon.load_profile", _load_profile)

    # Stub attacker_can_generate to return False (the condition being tested)
    monkeypatch.setattr("tarnish.cli.attacker_can_generate", lambda: False)

    # Stub run_campaign to return a minimal result without running the graph
    def _run_campaign(*a, **k):
        result = CampaignResult(target=profile, findings=[])
        return result, tmp_path / "campaign.json"

    monkeypatch.setattr("tarnish.cli.run_campaign", _run_campaign)

    # Invoke explore in harness mode (default)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["explore", "--root", str(tmp_path)])

    # Verify the warning appears
    assert result.exit_code == 0, f"Exit code: {result.exit_code}, output: {result.output}"
    assert "no backend here will generate attack payloads" in result.output
    assert "both the claude and codex CLIs refuse" in result.output


def test_explore_warns_when_attacker_cannot_generate_in_live_mode(tmp_path, monkeypatch):
    """Same warning in --live mode, since payload generation is not conditional on mode."""
    # Stub the dependencies for live mode
    target = TargetProfile(id="test", name="test", url="http://localhost:3000", owner_verified=True)

    def _load_target(profile_id):
        return target

    monkeypatch.setattr("tarnish.cli.load_target", _load_target)

    # Stub attacker_can_generate to return False
    monkeypatch.setattr("tarnish.cli.attacker_can_generate", lambda: False)

    # Stub run_campaign
    def _run_campaign(*a, **k):
        result = CampaignResult(target=target, findings=[])
        return result, tmp_path / "campaign.json"

    monkeypatch.setattr("tarnish.cli.run_campaign", _run_campaign)

    # Invoke explore in live mode
    runner = CliRunner()
    result = runner.invoke(cli.app, ["explore", "--live", "test"])

    # Verify the warning appears
    assert result.exit_code == 0, f"Exit code: {result.exit_code}, output: {result.output}"
    assert "no backend here will generate attack payloads" in result.output
    assert "both the claude and codex CLIs refuse" in result.output
