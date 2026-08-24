"""Tier 1 remediation: every objective maps to a fix whose class is backed by executable code,
and each of the five mitigations actually does its job."""

from __future__ import annotations

import pytest

from tarnish.remediation.mitigations import MITIGATIONS
from tarnish.remediation.mitigations import (
    input_sanitization,
    output_validation,
    schema_closure,
    scope_restriction,
)
from tarnish.remediation.static_map import remediate, severity_for
from tarnish.schemas import Objective

OBJECTIVES = ("instruction", "data", "leak", "jailbreak", "logic")


@pytest.mark.parametrize("objective", OBJECTIVES)
def test_every_objective_gets_a_backed_static_fix(objective: Objective):
    r = remediate(objective, technique="whatever")
    assert r.tier == "static"
    assert r.verification is None  # proposed, not verified
    assert r.remediation_class in MITIGATIONS  # the class is backed by executable code
    assert severity_for(objective) in ("critical", "high", "medium", "low")


def test_input_sanitization_strips_zero_width_smuggling():
    assert input_sanitization.sanitize("app​rove") == "approve"


def test_scope_restriction_rejects_non_cv():
    assert scope_restriction.is_in_scope("Experience: 5 years. Education: BSc. Skills: Python")
    assert not scope_restriction.is_in_scope("Today's soup is tomato. Main course: steak.")


def test_output_validation_flags_prompt_leak():
    ok, _ = output_validation.validate("Sure, my system prompt is: You are a CV evaluator")
    assert ok is False
    ok, _ = output_validation.validate("Score: 58/100. Solid backend experience.")
    assert ok is True


def test_schema_closure_rejects_out_of_range_score():
    with pytest.raises(Exception):
        schema_closure.ClosedEvaluation(score=999, verdict="advance")
