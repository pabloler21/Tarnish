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


def _counting_transport():
    """A harness-shaped transport that counts deliveries and returns a distinct response each
    time. Whether a delivery 'succeeds' is decided by the faked evaluate, not by this text."""
    class _T:
        channel = "harness"
        attackable = {"chat_input"}
        deliveries = 0

        def __init__(self, profile, surface_kind=None):
            self.surface = profile.surfaces[0]

        def classify_surface(self, target):
            return self.surface.kind

        def control_input(self, target):
            return "Hi, what can you help with?"

        def deliver(self, target, *, visible, hidden=None, hiding=None):
            if hidden is None:
                return "control"
            _T.deliveries += 1
            return f"attacked response {_T.deliveries}"

    _T.deliveries = 0
    return _T


def _fixed_payload(monkeypatch):
    from tarnish.schemas import Payload
    calls = {"generate": 0}

    def _gen(target, objective, **kw):
        calls["generate"] += 1
        return Payload(objective=objective, technique="injection", content="Please note this.")

    monkeypatch.setattr(orchestrator.SPECIALISTS["injection"], "generate", _gen)
    return calls


def _succeed_on(monkeypatch, nth):
    """Fake evaluate that returns succeeded=True only on its nth call (1-based). nth=None: never."""
    from tarnish.schemas import Verdict
    calls = {"evaluate": 0}

    def _eval(attempt, control, tools=None):
        calls["evaluate"] += 1
        ok = nth is not None and calls["evaluate"] == nth
        return Verdict(attempt_id=attempt.id, succeeded=ok, model_acted=ok,
                       evidence="faked", confidence=1.0, judge_model="fake")

    monkeypatch.setattr(orchestrator, "evaluate", _eval)
    return calls


def test_best_of_n_finds_a_vulnerability_that_lands_late(monkeypatch):
    """The regression this branch removes: a payload that only reproduces on a later delivery
    was reported as 'no finding' by the single-shot code. Now it is found."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 3)  # lands on the 3rd delivery

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        (finding,) = out["findings"]
        assert finding.reproduction.delivery_index == 3
        assert finding.reproduction.delivery_ceiling == 5
        assert T.deliveries == 3, "must stop at the first success, not deliver all 5"
    finally:
        get_settings.cache_clear()


def test_a_target_that_never_lands_is_clean_at_bounded_cost(monkeypatch):
    """A non-vulnerable target: no finding, and exactly attack_attempts deliveries (the honest
    cost of a confident negative), never more."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, None)  # never lands

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert not out.get("findings")
        assert T.deliveries == 5
    finally:
        get_settings.cache_clear()


def test_early_stop_pays_once_when_it_lands_first(monkeypatch):
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 1)

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        (finding,) = out["findings"]
        assert finding.reproduction.delivery_index == 1
        assert T.deliveries == 1
    finally:
        get_settings.cache_clear()


def test_assess_does_not_re_evaluate(monkeypatch):
    """The verdict is computed once in the loop and carried. If _assess re-evaluated, the judge
    (stochastic on the real path) could contradict the loop. evaluate must be called exactly as
    many times as there were deliveries — never once more for assessment."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        calls = _succeed_on(monkeypatch, 1)

        orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert calls["evaluate"] == 1, "one delivery, one evaluation — assess must not re-evaluate"
    finally:
        get_settings.cache_clear()


def test_generation_is_not_multiplied_by_n(monkeypatch):
    """best-of-N re-delivers the SAME payload; generation (the API-key cost) happens once."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "5")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        gen = _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, None)  # never lands -> 5 deliveries

        orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert gen["generate"] == 1, "generation must not be multiplied by the delivery ceiling"
        assert T.deliveries == 5
    finally:
        get_settings.cache_clear()


def test_attack_attempts_one_is_the_old_single_shot(monkeypatch):
    """The bisect anchor: ceiling 1 == today's single delivery, no finding on a target that
    would have landed on a later try."""
    monkeypatch.setenv("ATTACK_ATTEMPTS", "1")
    from tarnish.config import get_settings
    get_settings.cache_clear()
    try:
        T = _counting_transport()
        monkeypatch.setattr(orchestrator, "HarnessTransport", T)
        _fixed_payload(monkeypatch)
        _succeed_on(monkeypatch, 2)  # would land on the 2nd — but there is no 2nd

        out = orchestrator.build_graph().invoke(
            {"target": _repo_profile(), "tasks": [("injection", "instruction")], "mode": "harness"}
        )

        assert not out.get("findings")
        assert T.deliveries == 1
    finally:
        get_settings.cache_clear()
