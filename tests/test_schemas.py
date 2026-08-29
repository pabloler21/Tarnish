"""The attack data model composes end to end, and a fresh Remediation is unverified."""

from __future__ import annotations

from tarnish.fingerprint import fingerprint
from tarnish.schemas import (
    AttackAttempt,
    Finding,
    Payload,
    Remediation,
)


def _finding() -> Finding:
    attempt = AttackAttempt(
        id="a1",
        payload=Payload(objective="data", technique="data_injection",
                        content="fake skill: Rust", hiding="white_on_white"),
        surface="pdf_upload",
        raw_response="Score 90/100 — strong Rust experience",
    )
    return Finding(
        fingerprint=fingerprint("data", "data_injection", "cv_pdf"),
        severity="high",
        objective="data",
        business_impact="An attacker can inflate their score with skills they don't have.",
        reproduction=attempt,
        control_diff="control scored 58; injected scored 90 citing a planted skill",
        remediation=Remediation(
            remediation_class="input_sanitization", detail="strip invisible text", tier="static"
        ),
    )


def test_finding_composes_and_defaults():
    f = _finding()
    assert f.reproduction.payload.hiding == "white_on_white"
    assert f.status == "new"
    # verification: None means proposed, not verified.
    assert f.remediation.verification is None


def test_finding_round_trips_through_json():
    f = _finding()
    assert Finding.model_validate_json(f.model_dump_json()) == f


def test_a_pre_rename_campaign_result_still_loads():
    """The shape `tarnish report` reads: a whole CampaignResult JSON written before `fixed` was
    renamed to `not_reproducing`. Four such reports are on disk, one of them the Gate 1 evidence.
    Validating the CampaignResult must normalize the nested finding, not raise."""
    import json

    from tarnish.schemas import CampaignResult, TargetProfile

    target = TargetProfile(id="aurea", name="Aurea", url="https://x", owner_verified=True)
    data = json.loads(CampaignResult(target=target, findings=[_finding()]).model_dump_json())
    data["findings"][0]["status"] = "fixed"  # as written before the rename

    loaded = CampaignResult.model_validate_json(json.dumps(data))

    assert loaded.findings[0].status == "not_reproducing"


def test_a_pre_rename_campaign_result_keeps_its_fixed_findings_list():
    """The sibling of the status shim: `fixed_findings` became `not_reproducing_findings`, and
    pydantic silently DROPS an unknown key — so without the alias a pre-rename report renders
    "Stopped reproducing 0" directly above a finding badged not_reproducing. All four reports on
    disk carry a non-empty list."""
    import json

    from tarnish.schemas import CampaignResult, TargetProfile

    target = TargetProfile(id="aurea", name="Aurea", url="https://x", owner_verified=True)
    data = json.loads(CampaignResult(
        target=target, findings=[_finding()], not_reproducing_findings=["7daf6f56e83c58c0"],
    ).model_dump_json())
    data["fixed_findings"] = data.pop("not_reproducing_findings")  # as written before the rename

    loaded = CampaignResult.model_validate_json(json.dumps(data))

    assert loaded.not_reproducing_findings == ["7daf6f56e83c58c0"]
    assert "fixed_findings" not in loaded.model_dump_json()  # and the old key is not written back


def test_attack_attempt_defaults_to_a_single_delivery():
    """delivery_index/ceiling default to 1/1 so every existing construction and every prior
    persisted report reads as a single-shot delivery (pre-best-of-N)."""
    from tarnish.schemas import AttackAttempt, Payload

    a = AttackAttempt(
        id="x", surface="chat_input", raw_response="r",
        payload=Payload(objective="data", technique="injection", content="p"),
    )
    assert a.delivery_index == 1
    assert a.delivery_ceiling == 1


def test_attack_attempt_records_which_delivery_landed():
    from tarnish.schemas import AttackAttempt, Payload

    a = AttackAttempt(
        id="x", surface="chat_input", raw_response="r", delivery_index=3, delivery_ceiling=5,
        payload=Payload(objective="data", technique="injection", content="p"),
    )
    assert (a.delivery_index, a.delivery_ceiling) == (3, 5)


def test_attack_attempts_setting_defaults_to_five(monkeypatch):
    """best-of-N ceiling. Default 5 -> ~0.1% miss at the measured 75% landing rate."""
    from tarnish.config import get_settings

    monkeypatch.delenv("ATTACK_ATTEMPTS", raising=False)
    monkeypatch.delenv("TARNISH_ATTACK_ATTEMPTS", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().attack_attempts == 5
    finally:
        get_settings.cache_clear()


def test_attack_attempts_setting_reads_the_env(monkeypatch):
    from tarnish.config import get_settings

    monkeypatch.setenv("ATTACK_ATTEMPTS", "3")
    get_settings.cache_clear()
    try:
        assert get_settings().attack_attempts == 3
    finally:
        get_settings.cache_clear()


def test_attack_attempts_rejects_a_ceiling_below_one(monkeypatch):
    """A 0/negative ceiling would make _attack's delivery loop record no attempt at all,
    crashing _assess with an AttributeError on a None. Reject it at the settings boundary
    instead, as a clean validation error."""
    import pytest
    from pydantic import ValidationError

    from tarnish.config import get_settings

    monkeypatch.setenv("ATTACK_ATTEMPTS", "0")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()
