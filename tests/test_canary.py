# tests/test_canary.py
"""The canary is two halves doing two jobs: a domain word that makes the target surface the
text, and an opaque token that no target can volunteer. Only the token is the oracle."""

from __future__ import annotations

from tarnish.canary import canary, impact, new_token
from tarnish.schemas import PromptRef, RepoProfile, Surface, ToolSpec


def _profile() -> RepoProfile:
    return RepoProfile(
        id="victim", name="victim", root="victim", language="typescript",
        surfaces=[Surface(file="src/bot.ts", line=18, symbol="handleMessage", kind="chat_input")],
        system_prompt=PromptRef(file="src/bot.ts", line=7, text="You are Acme Support."),
        tools=[ToolSpec(name="refundOrder", file="src/tools.ts", line=4, side_effect=True)],
        domain_vocabulary=["refund", "order", "escalation"],
    )


def test_token_is_opaque_and_unique():
    a, b = new_token(), new_token()
    assert a.startswith("TRN-") and len(a) == 10 and a != b


def test_carrier_uses_the_domain_vocabulary_but_the_oracle_is_the_token_alone():
    vocabulary = ["refund", "order", "escalation"]
    line, oracle = canary("chat_input", vocabulary)

    assert len(oracle) == 1
    token = oracle[0]
    assert token in line
    assert any(word in line for word in vocabulary), "a bare token can be ingested and never appear"
    # The false-positive killer: a target may volunteer "refund"; it can never invent the token.
    assert not any(word in oracle for word in vocabulary)


def test_each_surface_kind_gets_its_own_carrier():
    lines = {kind: canary(kind, ["refund"])[0]
             for kind in ("chat_input", "document_ingest", "retrieved_doc", "pdf_upload")}
    assert len(set(lines.values())) == 4


def test_unknown_kind_falls_back_rather_than_raising():
    line, oracle = canary("something_new", ["refund"])
    assert oracle[0] in line


def test_impact_names_the_real_tool_and_location():
    text = impact("logic", _profile(), where="src/bot.ts#handleMessage")
    assert "refundOrder" in text and "src/bot.ts#handleMessage" in text


def test_impact_without_a_repo_profile_keeps_the_live_mode_prose():
    text = impact("data")
    assert text and "{" not in text  # no unformatted placeholder leaked


def test_a_side_effect_tool_raises_severity_one_level():
    from tarnish.remediation.static_map import severity_for

    assert severity_for("data") == "high"                    # live mode, no tool inventory
    assert severity_for("data", _profile()) == "critical"    # this bot can refund money
    assert severity_for("leak", _profile()) == "high"        # medium -> high, not straight to top


def test_a_repo_with_no_side_effect_tool_keeps_the_base_severity():
    harmless = _profile().model_copy(update={"tools": []})
    from tarnish.remediation.static_map import severity_for

    assert severity_for("data", harmless) == "high"
