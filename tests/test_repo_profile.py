"""The repo-mode contracts: a profile that survives a round trip, and a Baseline that reads
both the new dict form and the pre-M2 list form (an existing baseline.json must not crash)."""

from __future__ import annotations

from tarnish.schemas import (
    AttackAttempt, Baseline, CampaignResult, Finding, Payload, PromptRef, RepoProfile,
    Remediation, Surface, ToolSpec,
)


def _profile() -> RepoProfile:
    return RepoProfile(
        id="victim", name="victim", root="victim", language="typescript",
        surfaces=[Surface(file="src/bot.ts", line=31, symbol="handleMessage", kind="chat_input")],
        system_prompt=PromptRef(file="src/bot.ts", line=7, text="You are a support bot."),
        tools=[ToolSpec(name="refundOrder", file="src/tools.ts", line=4,
                        parameters={"orderId": "string"}, side_effect=True)],
        domain_vocabulary=["refund", "order", "escalation"],
    )


def test_repo_profile_round_trips_inside_a_campaign_result():
    result = CampaignResult(target=_profile())
    parsed = CampaignResult.model_validate_json(result.model_dump_json())
    assert isinstance(parsed.target, RepoProfile)
    assert parsed.target.surfaces[0].symbol == "handleMessage"
    assert parsed.target.tools[0].side_effect is True


def test_baseline_reads_the_legacy_list_form():
    legacy = '{"target_id": "aurea", "accepted_fingerprints": ["7daf6f56", "aa11bb22"]}'
    baseline = Baseline.model_validate_json(legacy)
    assert baseline.fingerprints == {"7daf6f56": "accepted", "aa11bb22": "accepted"}
    assert baseline.proofs == {}


def test_baseline_carries_the_proof_check_replays():
    attempt = AttackAttempt(
        id="a1", surface="chat_input", raw_response="ref TRN-9f3a2c approved",
        payload=Payload(objective="data", technique="injection", content="x", oracle=["TRN-9f3a2c"]),
    )
    baseline = Baseline(target_id="victim", fingerprints={"7daf6f56": "not_reproducing"},
                        proofs={"7daf6f56": attempt})
    parsed = Baseline.model_validate_json(baseline.model_dump_json())
    assert parsed.proofs["7daf6f56"].payload.oracle == ["TRN-9f3a2c"]
    assert parsed.fingerprints["7daf6f56"] == "not_reproducing"


def test_finding_location_defaults_to_empty():
    # live (browser) findings have no file#symbol; the field must not become required.
    finding = Finding(
        fingerprint="f", severity="high", objective="data", business_impact="x",
        reproduction=AttackAttempt(
            id="a", surface="pdf_upload", raw_response="r",
            payload=Payload(objective="data", technique="injection", content="c")),
        control_diff="d",
        remediation=Remediation(remediation_class="input_sanitization", detail="s", tier="static"),
    )
    assert finding.location == ""
