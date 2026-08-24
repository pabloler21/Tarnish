"""The five executable mitigation classes. RemediationClass is a closed enum and each member
maps here to real, runnable code — the structural guarantee that a fix is testable (a free-text
fix is not). Used by verification (harness mode, Phase 3) to prove a fix closes a finding."""

from __future__ import annotations

from . import (
    input_sanitization,
    output_validation,
    prompt_hardening,
    schema_closure,
    scope_restriction,
)

# RemediationClass -> the module implementing it (so the closed enum is provably backed by code).
MITIGATIONS = {
    "input_sanitization": input_sanitization,
    "schema_closure": schema_closure,
    "prompt_hardening": prompt_hardening,
    "output_validation": output_validation,
    "scope_restriction": scope_restriction,
}
