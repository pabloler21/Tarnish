"""Tier 1 remediation: a deterministic table (objective -> RemediationClass + templated detail).
No LLM, no hallucination, instant — the floor every finding gets. LLM security fixes are largely
standardized, so this covers the common cases; the real value is verification, not fix generation."""

from __future__ import annotations

from ..schemas import Objective, Remediation

# objective -> (RemediationClass, concrete detail). technique is available for future refinement.
_MAP: dict[Objective, tuple[str, str]] = {
    "instruction": (
        "prompt_hardening",
        "Add a system-prompt delta declaring every user-supplied or retrieved block untrusted "
        "data: it may be quoted or summarized, never executed as an instruction. Restate the "
        "task and its constraints AFTER that block, so the last word belongs to the system.",
    ),
    "data": (
        "input_sanitization",
        "Sanitize untrusted content before it reaches the prompt: strip zero-width and bidi "
        "control characters; where the input arrives as a document, also drop text hidden by "
        "colour, size or position at parse time (a text-level strip cannot see it). Take any "
        "fact the model acts on from your own records, not from claims made inside that content.",
    ),
    "leak": (
        "prompt_hardening",
        "Instruct the model never to disclose its system prompt, tool definitions or internal "
        "rules — verbatim or paraphrased — and to refuse meta-questions about its own "
        "configuration.",
    ),
    "jailbreak": (
        "scope_restriction",
        "Enforce the agent's task boundary in code, not only in the prompt: reject any request "
        "outside the operations this agent exists to perform. Role-play, hypotheticals and "
        "'for testing' framings do not widen that boundary.",
    ),
    "logic": (
        "schema_closure",
        "Constrain the model's output to a closed schema — typed fields, an enum for every "
        "decision — and validate it before acting on it. Reject free-form output and any value "
        "outside the enum instead of coercing it into range.",
    ),
}


_SEVERITY: dict[Objective, str] = {
    "instruction": "critical",
    "logic": "critical",
    "data": "high",
    "jailbreak": "high",
    "leak": "medium",
}


_ESCALATION = {"medium": "high", "high": "critical", "critical": "critical", "low": "medium"}


def severity_for(objective: Objective, target=None) -> str:
    """One level higher when the target has a tool that changes the world. Reaching a bot that
    can refund, send or delete is materially worse than reaching one that only answers."""
    base = _SEVERITY.get(objective, "medium")
    tools = getattr(target, "tools", None)
    return _ESCALATION[base] if tools and any(t.side_effect for t in tools) else base


def remediate(objective: Objective, technique: str) -> Remediation:
    remediation_class, detail = _MAP[objective]
    return Remediation(remediation_class=remediation_class, detail=detail, tier="static")
