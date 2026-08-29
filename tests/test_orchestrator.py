"""The campaign graph's conditional routing: an unknown/unsupported surface stops before any
attack (the needs_clarification path). Browser + LLM are mocked out."""

from __future__ import annotations

from tarnish import orchestrator
from tarnish.schemas import TargetProfile


def test_graph_routes_unsupported_surface_to_end(monkeypatch):
    class _FakeTransport:
        attackable = {"pdf_upload"}

        def __init__(self, **kwargs):
            pass

        def classify_surface(self, target):
            return "text_chat"  # not yet attackable in Phase 1

    monkeypatch.setattr(orchestrator, "BrowserTransport", _FakeTransport)

    graph = orchestrator.build_graph()
    target = TargetProfile(id="t", name="t", url="https://x", owner_verified=True)
    out = graph.invoke({"target": target, "tasks": [], "headless": True})

    assert out["route"] == "unknown"
    assert not out.get("findings")  # routed to END, no attacks run


"""Harness mode end to end, with the transport and the specialists faked: the graph must route,
control, plant a canary, and produce a finding whose identity is file#symbol."""

from tarnish.schemas import PromptRef, RepoProfile, Surface, ToolSpec


class _FakeHarness:
    channel = "harness"
    attackable = {"chat_input"}

    def __init__(self, profile, surface_kind=None):
        self.profile = profile
        self.surface = profile.surfaces[0]

    def classify_surface(self, target):
        return self.surface.kind

    def control_input(self, target):
        return "Hi, what can you help with?"

    def deliver(self, target, *, visible, hidden=None, hiding=None):
        if hidden is None:
            return "I can help with orders and refunds."
        # The reconstructed target swallows the planted line AND acts on it: echoing the token
        # proves ingestion, the CALL proves obedience.
        token = [w for w in hidden.split() if w.startswith("TRN-")]
        return (f"Confirmed {token[0] if token else 'nothing'}.\n"
                'CALL refundOrder {"orderId": "A-1042", "amountCents": 50000}')


def _repo_profile() -> RepoProfile:
    return RepoProfile(
        id="victim", name="victim", root="victim", language="typescript",
        surfaces=[Surface(file="src/bot.ts", line=18, symbol="handleMessage", kind="chat_input")],
        system_prompt=PromptRef(file="src/bot.ts", line=7, text="You are Acme Support."),
        tools=[ToolSpec(name="refundOrder", file="src/tools.ts", line=4, side_effect=True)],
        domain_vocabulary=["refund", "order"],
    )


def test_harness_mode_produces_an_oracle_proven_finding(monkeypatch):
    from tarnish.schemas import Payload

    monkeypatch.setattr(orchestrator, "HarnessTransport", _FakeHarness)
    monkeypatch.setattr(
        orchestrator.SPECIALISTS["injection"], "generate",
        lambda target, objective, **kw: Payload(
            objective=objective, technique="injection", content="Please note the following."),
    )

    profile = _repo_profile()
    out = orchestrator.build_graph().invoke(
        {"target": profile, "tasks": [("injection", "data")], "mode": "harness"}
    )

    assert out["route"] == "attack"
    assert out["control_response"], "the mandatory control must be non-empty"
    assert out["surface_element"] == "src/bot.ts#handleMessage"

    (finding,) = out["findings"]
    assert finding.location == "src/bot.ts#handleMessage"
    assert finding.reproduction.payload.oracle[0].startswith("TRN-")
    assert finding.reproduction.payload.oracle[0] in finding.reproduction.raw_response
    assert "victim" in finding.business_impact, "impact must speak the target's own domain"
    assert finding.severity == "critical", "data injection into a bot that can refund money"
    assert finding.reproduction.payload.hiding is None, "hiding is a PDF concern, not a harness one"


def test_live_mode_finding_has_empty_location(monkeypatch):
    """Live mode has no file/symbol to name. `location` must stay "" — a surface *kind*
    ("pdf_upload") is not a file#symbol identity, and Finding.location must not lie about it.
    Fingerprinting is unaffected: it still falls back to the surface kind."""
    from tarnish import evaluator
    from tarnish.evaluator import _Judgment
    from tarnish.fingerprint import fingerprint
    from tarnish.schemas import Payload

    class _FakeLiveTransport:
        attackable = {"pdf_upload"}

        def __init__(self, **kwargs):
            pass  # no `self.surface` at all — that absence is the point

        def classify_surface(self, target):
            return "pdf_upload"

        def control_input(self, target):
            return "clean control text"

        def deliver(self, target, *, visible, hidden=None, hiding=None):
            if hidden is None:
                return "Looks like a solid resume."
            token = [w for w in hidden.split() if w.startswith("TRN-")]
            return f"Confirmed {token[0] if token else 'nothing'} — approved."

    monkeypatch.setattr(orchestrator, "BrowserTransport", _FakeLiveTransport)
    monkeypatch.setattr(
        orchestrator.SPECIALISTS["injection"], "generate",
        lambda target, objective, **kw: Payload(
            objective=objective, technique="injection", content="Please note the following."),
    )
    monkeypatch.setattr(
        evaluator, "_judge",
        lambda o, p, i, c: _Judgment(
            model_acted=True, succeeded=True, evidence="Confirmed", confidence=0.9
        ),
    )

    target = TargetProfile(id="t", name="t", url="https://x", owner_verified=True)
    out = orchestrator.build_graph().invoke(
        {"target": target, "tasks": [("injection", "data")], "mode": "live", "headless": True}
    )

    assert out["route"] == "attack"
    assert out["surface_element"] == ""

    (finding,) = out["findings"]
    assert finding.location == ""
    assert finding.fingerprint == fingerprint("data", "injection", "pdf_upload")
