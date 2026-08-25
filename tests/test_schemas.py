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
