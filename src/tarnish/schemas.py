"""Pydantic data models. Phase 0 only needs TargetProfile; the rest of PLAN.md section 5
(Payload, AttackAttempt, Verdict, Remediation, Finding, ...) lands when each phase needs it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


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


class Surface(BaseModel):
    """Where untrusted input enters the target. `symbol` (the enclosing function/route) is what
    the fingerprint hashes — `line` is for display only, because lines move on every refactor."""

    file: str
    line: int
    symbol: str
    kind: Literal["chat_input", "document_ingest", "tool_result", "retrieved_doc"]


class ToolSpec(BaseModel):
    name: str
    file: str
    line: int
    parameters: dict = Field(default_factory=dict)  # NOT `schema`: it shadows BaseModel.schema
    side_effect: bool = False  # writes, charges, sends? drives severity and impact wording


class PromptRef(BaseModel):
    file: str
    line: int
    text: str  # the literal system prompt, so HarnessTransport can reconstruct the target


class RepoProfile(BaseModel):
    """Output of `init`, committed to the user's repo. The repo-mode counterpart of
    TargetProfile: same role, no URL, no browser."""

    id: str
    name: str
    root: str
    language: Literal["typescript", "python", "other"]
    surfaces: list[Surface] = Field(default_factory=list)
    system_prompt: PromptRef
    tools: list[ToolSpec] = Field(default_factory=list)
    domain_vocabulary: list[str] = Field(default_factory=list)  # feeds canary carriers


class Payload(BaseModel):
    objective: Objective
    technique: str  # the specialist/technique that produced it
    content: str
    hiding: HidingTechnique | None = None  # PDF surface only
    # Canary tokens planted in `content`. If any surfaces in the target's response but NOT in the
    # control's, the payload provably landed — a deterministic, reproducible oracle for
    # INGESTION. It is not judge-free: a surfaced token still goes to the judge to decide
    # whether the target obeyed or merely quoted it while refusing (D2).
    oracle: list[str] = Field(default_factory=list)


class AttackAttempt(BaseModel):
    id: str
    payload: Payload
    surface: str  # the surface kind the payload was delivered through
    raw_response: str
    # best-of-N delivery bookkeeping: which delivery (1-based) this attempt was, and the
    # ceiling in force. On a finding's recorded (succeeding) attempt this reads "reproduced on
    # delivery K of N" — the observed reliability. 1/1 = a single-shot delivery (pre-best-of-N
    # and every prior persisted report).
    delivery_index: int = 1
    delivery_ceiling: int = 1
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
    location: str = ""  # repo mode: `file#symbol` (+ line in the report). Empty in live mode.
    remediation: Remediation
    # `not_reproducing`, NOT `fixed`: all that was observed is that the payload did not
    # reproduce on one delivery. Nothing is applied through Tarnish in this MVP, so nobody
    # fixed anything. `remediation.verification` is where a proven fix is asserted.
    status: Literal["new", "persisting", "not_reproducing", "regression"] = "new"
    first_seen: datetime = Field(default_factory=_now)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_status(cls, data):
        """Pre-release compatibility shim: reports written before `fixed` was renamed to
        `not_reproducing` carry the old value, which no longer validates. Every reader routes
        through here (baseline re-hydration, `tarnish report`'s whole-CampaignResult load), so
        this is the one place it belongs. Removable once no report on disk predates the rename."""
        if isinstance(data, dict) and data.get("status") == "fixed":
            data = data | {"status": "not_reproducing"}
        return data


class Baseline(BaseModel):
    """`.tarnish/baseline.json` — committed, and the thing the CI gate reads.

    `fingerprints` holds SUPPRESSIONS only: `accepted` (you decided to live with it) or
    `not_reproducing` (it stopped reproducing on the run that wrote this file — an observation,
    not a proof that anyone fixed it; its return is reported as a `regression`). A finding that
    is neither fails the gate.
    `proofs` is what `check` replays: no graph, no RAG, no specialists."""

    target_id: str
    fingerprints: dict[str, Literal["accepted", "not_reproducing"]] = Field(default_factory=dict)
    proofs: dict[str, AttackAttempt] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data):
        """Pre-M2 baselines stored a plain list. Read them as accepted. Removable once none exist."""
        if isinstance(data, dict) and isinstance(data.get("accepted_fingerprints"), list):
            data = dict(data)
            legacy = data.pop("accepted_fingerprints")
            data.setdefault("fingerprints", {fp: "accepted" for fp in legacy})
        return data


class CampaignResult(BaseModel):
    target: TargetProfile | RepoProfile
    findings: list[Finding] = Field(default_factory=list)
    control_baseline: str = ""  # the target's response to the clean, un-injected input
    coverage: dict = Field(default_factory=dict)  # attempts / successes per objective
    new_findings: list[str] = Field(default_factory=list)  # fingerprints new this run
    # fingerprints that stopped reproducing this run. NOT "fixed" — see Finding.status.
    # The `fixed_findings` alias is the same pre-release compatibility shim as
    # Finding._upgrade_legacy_status: without it a report written before the rename loads with
    # this list SILENTLY emptied. Removable once no report on disk predates the rename.
    not_reproducing_findings: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("not_reproducing_findings", "fixed_findings"),
    )
    cost_usd: float = 0.0
    # The best-of-N ceiling actually in force for THIS campaign (1 in live mode; attack_attempts
    # in harness mode) — persisted so a report states what was observed, not the CURRENT global
    # setting. Default 1 is deliberate: every report persisted before this field existed really
    # was single-shot, so an old file re-rendered says "delivered up to 1 time", which is true.
    delivery_ceiling: int = 1
    created_at: datetime = Field(default_factory=_now)
