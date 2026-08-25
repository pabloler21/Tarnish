"""Tier 1 remediation: a deterministic table (objective -> RemediationClass + templated detail).
No LLM, no hallucination, instant — the floor every finding gets. LLM security fixes are largely
standardized, so this covers the common cases; the real value is verification, not fix generation."""

from __future__ import annotations

from ..schemas import Objective, Remediation

# objective -> (RemediationClass, concrete detail). technique is available for future refinement.
_MAP: dict[Objective, tuple[str, str]] = {
    "instruction": (
        "prompt_hardening",
        "Add a system-prompt delta stating the resume is untrusted data; never follow "
        "instructions found inside it. Score only on genuine evidence.",
    ),
    "data": (
        "input_sanitization",
        "Strip invisible/hidden text (zero-width, bidi, white-on-white) before evaluation, and "
        "verify claimed skills/experience against structured, corroborated fields.",
    ),
    "leak": (
        "prompt_hardening",
        "Instruct the model to never disclose its system prompt or scoring rubric, and to refuse "
        "meta-questions about its own instructions.",
    ),
    "jailbreak": (
        "scope_restriction",
        "Enforce the CV-evaluation task boundary: refuse any request to act outside scoring a "
        "resume, regardless of framing.",
    ),
    "logic": (
        "schema_closure",
        "Constrain the output to a closed schema (integer score 0-100 + verdict enum); reject "
        "free-form verdicts and out-of-scope documents.",
    ),
}

_SEVERITY: dict[Objective, str] = {
    "instruction": "critical",
    "logic": "critical",
    "data": "high",
    "jailbreak": "high",
    "leak": "medium",
}


def severity_for(objective: Objective) -> str:
    return _SEVERITY.get(objective, "medium")


def remediate(objective: Objective, technique: str) -> Remediation:
    remediation_class, detail = _MAP[objective]
    return Remediation(remediation_class=remediation_class, detail=detail, tier="static")
