"""Evaluator wiring: turn a judge judgment into a Verdict, including the PDF two-stage
inference (parser_passed) and the judge_model stamp. The judge LLM is mocked."""

from __future__ import annotations

from tarnish import evaluator
from tarnish.evaluator import _Judgment
from tarnish.schemas import AttackAttempt, Payload


def _attempt(surface="pdf_upload") -> AttackAttempt:
    return AttackAttempt(
        id="a1",
        payload=Payload(objective="data", technique="injection", content="fake: Rust expert"),
        surface=surface,
        raw_response="Score 95 — strong Rust experience",
    )


def test_success_on_pdf_infers_parser_passed(monkeypatch):
    monkeypatch.setattr(
        evaluator, "_judge",
        lambda p, i, c: _Judgment(model_acted=True, succeeded=True, evidence="strong Rust", confidence=0.9),
    )
    v = evaluator.evaluate(_attempt("pdf_upload"), control_response="Score 58 — no Rust")
    assert v.succeeded is True
    assert v.model_acted is True
    assert v.parser_passed is True  # acted => the parser surfaced the hidden text
    assert v.judge_model  # stamped


def test_failure_leaves_parser_passed_unknown(monkeypatch):
    monkeypatch.setattr(
        evaluator, "_judge",
        lambda p, i, c: _Judgment(model_acted=False, succeeded=False, evidence="unchanged", confidence=0.8),
    )
    v = evaluator.evaluate(_attempt("pdf_upload"), control_response="Score 58")
    assert v.succeeded is False
    assert v.parser_passed is None  # cannot confirm the parser surfaced it
