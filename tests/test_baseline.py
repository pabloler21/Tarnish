"""Fingerprint diff: new / persisting / fixed across runs (drives status + the CI gate)."""

from __future__ import annotations

from tarnish.baseline import apply_status, diff
from tarnish.schemas import (
    AttackAttempt,
    CampaignResult,
    Finding,
    Payload,
    Remediation,
    TargetProfile,
)


def test_diff_classifies_fingerprints():
    previous = {"a", "b", "c"}
    current = {"b", "c", "d"}  # d is new, b/c persist, a is fixed
    new, persisting, fixed = diff(current, previous)
    assert new == {"d"}
    assert persisting == {"b", "c"}
    assert fixed == {"a"}


def test_first_run_is_all_new():
    new, persisting, fixed = diff({"a", "b"}, set())
    assert new == {"a", "b"}
    assert not persisting and not fixed


def _finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp, severity="high", objective="data", business_impact="x",
        reproduction=AttackAttempt(
            id="a", surface="pdf_upload", raw_response="Score 90 — Kafka",
            payload=Payload(objective="data", technique="injection", content="hidden"),
        ),
        control_diff="before/after", remediation=Remediation(
            remediation_class="input_sanitization", detail="strip hidden", tier="static"),
    )


def test_fixed_finding_is_rehydrated_and_rescan_verified(tmp_path):
    target = TargetProfile(id="t", name="t", url="https://x", owner_verified=True)
    # A prior report on disk holds one finding.
    prior = CampaignResult(target=target, findings=[_finding("fp1")], created_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC))
    (tmp_path / "t-20260101T000000.json").write_text(prior.model_dump_json(), encoding="utf-8")

    # This run reproduces nothing -> fp1 should flip to fixed.
    result = CampaignResult(target=target, findings=[])
    apply_status(result, "t", reports_dir=str(tmp_path))

    assert result.fixed_findings == ["fp1"]
    fixed = [f for f in result.findings if f.status == "fixed"]
    assert len(fixed) == 1
    v = fixed[0].remediation.verification
    assert v is not None and v.mode == "rescan" and v.status == "verified"
