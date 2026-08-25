"""Pydantic data models. Phase 0 only needs TargetProfile; the rest of PLAN.md section 5
(Payload, AttackAttempt, Verdict, Remediation, Finding, ...) lands when each phase needs it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)

# Attack taxonomy (closed enums — structural guarantees, not free strings).
Objective = Literal["instruction", "data", "leak", "jailbreak", "logic"]
# PDF-channel-only hiding techniques. malicious_font (cmap remap) is Phase 2+.
HidingTechnique = Literal["white_on_white", "tiny_font", "off_page", "metadata"]
# Every member has an executable implementation in remediation/mitigations/.
RemediationClass = Literal[
    "input_sanitization", "schema_closure", "prompt_hardening",
    "output_validation", "scope_restriction",
]
VerificationMode = Literal["rescan", "prompt_level", "harness"]


class TargetProfile(BaseModel):
    id: str
    name: str
    url: str  # the target's web page; the browser transport drives its real input surface
    owner_verified: bool  # authorization gate (real ownership proof enforced in Phase 3)
    # OPTIONAL, best-effort auto-detected — never required. Operators paste a URL and don't
    # know their model; falsifiability comes from the mandatory control, not the judge family.
    target_model_family: str | None = None
    system_prompt: str | None = None  # if exposed, enables prompt_level verification (Phase 2)
    # "auto" = detect the surface from the DOM; override only when detection fails.
    surface: Literal["auto", "pdf_upload", "text_chat"] = "auto"


class Payload(BaseModel):
    objective: Objective
    technique: str  # the specialist/technique that produced it
    content: str
    hiding: HidingTechnique | None = None  # PDF surface only


class AttackAttempt(BaseModel):
    id: str
    payload: Payload
    surface: str  # the surface kind the payload was delivered through
    raw_response: str
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=_now)


class Verdict(BaseModel):
    attempt_id: str
    succeeded: bool  # ground-truth binary, vs the planted payload + clean control
    parser_passed: bool | None = None  # PDF two-stage: did the parser surface the hidden text?
    model_acted: bool  # did the model act on the payload?
    evidence: str  # the span/quote proving success
    confidence: float
    judge_model: str


class VerificationResult(BaseModel):
    mode: VerificationMode
    status: Literal["verified", "failed", "partial"]
    attempts_rerun: int
    attempts_blocked: int
    evidence: str  # the post-fix response that no longer reflects the payload
    verified_at: datetime = Field(default_factory=_now)


class Remediation(BaseModel):
    remediation_class: RemediationClass
    detail: str  # the concrete fix for THIS finding
    tier: Literal["static", "rag"]
    grounding: list[str] = Field(default_factory=list)  # corpus chunk ids; empty for static tier
    verification: VerificationResult | None = None  # None = proposed, NOT verified — say so


class Finding(BaseModel):
    fingerprint: str  # stable identity across runs (see fingerprint.py); NOT the payload hash
    severity: Literal["critical", "high", "medium", "low"]
    objective: Objective
    business_impact: str  # the consequence in the target's domain language
    reproduction: AttackAttempt
    control_diff: str  # the delta between the injected evaluation and the clean control
    remediation: Remediation
    status: Literal["new", "persisting", "fixed", "regression"] = "new"
    first_seen: datetime = Field(default_factory=_now)


class Baseline(BaseModel):
    target_id: str
    accepted_fingerprints: list[str] = Field(default_factory=list)  # must NOT break the build
    created_at: datetime = Field(default_factory=_now)


class CampaignResult(BaseModel):
    target: TargetProfile
    findings: list[Finding] = Field(default_factory=list)
    control_baseline: str = ""  # the evaluation of the clean, un-injected CV
    coverage: dict = Field(default_factory=dict)  # attempts / successes per objective
    new_findings: list[str] = Field(default_factory=list)  # fingerprints new this run
    fixed_findings: list[str] = Field(default_factory=list)  # fingerprints closed this run
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
