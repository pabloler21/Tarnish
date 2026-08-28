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


def test_a_finding_that_stops_reproducing_is_not_claimed_verified(tmp_path):
    """The 2026-08-28 fossil: with no fix applied, a finding that fails to reproduce was stamped
    rescan/verified 'after the operator applied the fix'. In the MVP nothing is applied through
    Tarnish, so that claim is always a lie."""
    target = TargetProfile(id="t", name="t", url="https://x", owner_verified=True)
    # A prior report on disk holds one finding.
    prior = CampaignResult(target=target, findings=[_finding("fp1")], created_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC))
    (tmp_path / "t-20260101T000000.json").write_text(prior.model_dump_json(), encoding="utf-8")

    # This run reproduces nothing -> fp1 should flip to fixed.
    result = CampaignResult(target=target, findings=[])
    apply_status(result, "t", reports_dir=str(tmp_path))  # fix_applied defaults to False

    assert result.fixed_findings == ["fp1"]              # the diff bookkeeping still happens
    rehydrated = [f for f in result.findings if f.fingerprint == "fp1"]
    if rehydrated:                                        # if carried into the report at all,
        assert rehydrated[0].remediation.verification is None  # it must NOT claim verified


def test_a_real_applied_fix_still_records_the_rescan_proof(tmp_path):
    """When a fix WAS applied (M3 / manual rescan), the verified before/after is legitimate and
    must survive."""
    target = TargetProfile(id="t", name="t", url="https://x", owner_verified=True)
    prior = CampaignResult(target=target, findings=[_finding("fp1")], created_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC))
    (tmp_path / "t-20260101T000000.json").write_text(prior.model_dump_json(), encoding="utf-8")

    result = CampaignResult(target=target, findings=[])
    apply_status(result, "t", reports_dir=str(tmp_path), fix_applied=True)

    rehydrated = [f for f in result.findings if f.fingerprint == "fp1"][0]
    assert rehydrated.status == "fixed"
    assert rehydrated.remediation.verification is not None
    assert rehydrated.remediation.verification.status == "verified"


"""`.tarnish/baseline.json`: the proofs `check` replays, plus suppressions only ever set
deliberately. A fresh finding must NOT be auto-accepted or the gate is decorative."""


def test_write_baseline_records_proofs_but_accepts_nothing(tmp_path):
    from tarnish.baseline import load_baseline, write_baseline
    from tarnish.schemas import CampaignResult, TargetProfile

    result = CampaignResult(
        target=TargetProfile(id="victim", name="victim", url="https://x", owner_verified=True),
        findings=[_finding("aa11")],
    )
    path = write_baseline(result, tmp_path)

    assert path == tmp_path / ".tarnish" / "baseline.json"
    baseline = load_baseline(tmp_path, "victim")
    assert "aa11" in baseline.proofs
    assert baseline.fingerprints == {}, "a new finding is open, not accepted"


def test_write_baseline_marks_fixed_and_keeps_existing_suppressions(tmp_path):
    from tarnish.baseline import load_baseline, write_baseline
    from tarnish.schemas import Baseline, CampaignResult, TargetProfile

    existing = Baseline(target_id="victim", fingerprints={"bb22": "accepted"})
    (tmp_path / ".tarnish").mkdir()
    (tmp_path / ".tarnish" / "baseline.json").write_text(existing.model_dump_json())

    result = CampaignResult(
        target=TargetProfile(id="victim", name="victim", url="https://x", owner_verified=True),
        findings=[_finding("aa11")], fixed_findings=["cc33"],
    )
    write_baseline(result, tmp_path)

    baseline = load_baseline(tmp_path, "victim")
    assert baseline.fingerprints == {"bb22": "accepted", "cc33": "fixed"}


def test_load_baseline_on_a_fresh_repo_is_empty(tmp_path):
    from tarnish.baseline import load_baseline

    baseline = load_baseline(tmp_path, "victim")
    assert baseline.target_id == "victim" and baseline.proofs == {}


def test_load_baseline_raises_actionable_error_on_corrupt_file(tmp_path):
    """baseline.json is committed by design, so an unresolved git merge conflict is the expected
    corruption mode, not an exotic one. The bare parse error must not leak past this loader."""
    from tarnish.baseline import load_baseline

    (tmp_path / ".tarnish").mkdir()
    conflicted = tmp_path / ".tarnish" / "baseline.json"
    conflicted.write_text(
        "<<<<<<< HEAD\n{\"target_id\": \"victim\"}\n=======\n{\"target_id\": \"other\"}\n"
        ">>>>>>> branch\n",
        encoding="utf-8",
    )

    try:
        load_baseline(tmp_path, "victim")
        assert False, "expected a RuntimeError"
    except RuntimeError as e:
        assert str(conflicted) in str(e)


def test_write_baseline_keeps_prior_accepted_when_the_finding_reproduces_again(tmp_path):
    """The single most important property of this task: a fingerprint already marked `accepted`
    must survive a run that reproves it, and its proof must still refresh."""
    from tarnish.baseline import load_baseline, write_baseline
    from tarnish.schemas import Baseline, CampaignResult, TargetProfile

    existing = Baseline(target_id="victim", fingerprints={"aa11": "accepted"})
    (tmp_path / ".tarnish").mkdir()
    (tmp_path / ".tarnish" / "baseline.json").write_text(existing.model_dump_json())

    finding = _finding("aa11")
    result = CampaignResult(
        target=TargetProfile(id="victim", name="victim", url="https://x", owner_verified=True),
        findings=[finding],
    )
    write_baseline(result, tmp_path)

    baseline = load_baseline(tmp_path, "victim")
    assert baseline.fingerprints["aa11"] == "accepted"
    assert baseline.proofs["aa11"] == finding.reproduction
