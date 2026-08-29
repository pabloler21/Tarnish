"""The campaign graph (LangGraph). Classifies the target's attack surface and routes by
conditional edge (known surface -> attack; unknown -> stop for clarification), then delivers
each specialist's payload, evaluates against the control, and assembles remediated findings.

Nodes each return the full value for a key (last-write-wins), so no reducers are needed."""

from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agents.business_logic import BUSINESS_LOGIC
from .agents.injection import INJECTION
from .agents.leakage import LEAKAGE
from .canary import canary, impact
from .config import get_settings
from .evaluator import evaluate
from .fingerprint import fingerprint, surface_element
from .remediation.static_map import remediate, severity_for
from .schemas import AttackAttempt, Finding, HidingTechnique, RepoProfile, TargetProfile, Verdict
from .transport.browser import BrowserTransport
from .transport.harness import HarnessTransport

SPECIALISTS = {"injection": INJECTION, "leakage": LEAKAGE, "business_logic": BUSINESS_LOGIC}

# Default (specialist, objective) tasks a campaign runs against any target surface.
DEFAULT_TASKS: list[tuple[str, str]] = [
    ("injection", "data"),
    ("injection", "instruction"),
    ("business_logic", "logic"),
    ("leakage", "leak"),
    ("leakage", "jailbreak"),
]

# Which hiding technique the default campaign fires per objective. white_on_white reliably reaches
# the model on Aurea (real selectable text, just colored white); tiny_font extraction is flaky and
# off_page text never reaches the model. ponytail: one technique per objective; a fuller campaign
# sweeps all of scenarios.json's techniques per objective and keeps the first that succeeds.
_HIDING_FOR: dict[str, HidingTechnique] = {
    "data": "white_on_white",
    "instruction": "white_on_white",
    "leak": "white_on_white",
    "jailbreak": "white_on_white",
    "logic": "white_on_white",
}

class CampaignState(TypedDict, total=False):
    target: TargetProfile | RepoProfile
    mode: str  # "harness" (repo, default) | "live" (browser). Chooses the transport.
    tasks: list[tuple[str, str]]
    headless: bool
    surface: str
    surface_element: str  # repo mode: file#symbol — the finding's stable identity
    control_response: str
    attempts: list[AttackAttempt]
    verdicts: list[Verdict]  # carried from _attack so _assess never re-evaluates (best-of-N)
    delivery_ceiling: int  # the ceiling _attack actually used (1 if live, else attack_attempts)
    findings: list[Finding]
    route: str


def _transport(state: CampaignState):
    """Built per node, never stored in state: LangGraph checkpoints state to SQLite and a
    transport (browser, model client) is not serializable."""
    if state.get("mode", "live") == "harness":
        return HarnessTransport(state["target"])
    return BrowserTransport(headless=state.get("headless", True))


def _classify(state: CampaignState) -> dict:
    target = state["target"]
    transport = _transport(state)
    surface = transport.classify_surface(target)
    if surface not in transport.attackable:
        return {"surface": surface, "surface_element": "", "route": "unknown",
                "control_response": ""}
    profiled = getattr(transport, "surface", None)  # repo mode only
    # Live mode has no profiled surface at all — leave "" so `location` stays honestly empty
    # instead of a surface *kind* masquerading as a file#symbol identity. `_assess` already
    # falls back to state["surface"] for fingerprinting, so this does not touch fingerprints.
    element = surface_element(profiled.file, profiled.symbol) if profiled else ""
    control = transport.deliver(target, visible=transport.control_input(target))  # mandatory control
    return {"surface": surface, "surface_element": element, "route": "attack",
            "control_response": control}


def _route(state: CampaignState) -> str:
    return state["route"]


def _attack(state: CampaignState) -> dict:
    target = state["target"]
    transport = _transport(state)
    carrier = transport.control_input(target)
    control = state["control_response"]
    live = state.get("mode", "live") == "live"
    vocabulary = getattr(target, "domain_vocabulary", None)
    tools = getattr(target, "tools", None)
    # Live mode drives a real, operator-owned app with tools NOT stubbed — a side effect that
    # fires but isn't judged a success would otherwise fire again on every re-delivery. Best-of-N
    # is a harness-only cost/reliability trade; live stays single-shot, no opt-in.
    ceiling = 1 if live else get_settings().attack_attempts
    attempts: list[AttackAttempt] = []
    verdicts: list[Verdict] = []
    for family, objective in state["tasks"]:
        # Generate ONCE — generation is the step that spends the API key. best-of-N re-delivers
        # this same payload; it does not regenerate.
        payload = SPECIALISTS[family].generate(target, objective, surface=state["surface"])  # type: ignore[arg-type]
        updates: dict = {}
        if live:  # hiding is a PDF-rendering concern; a harness has nothing to hide text in
            updates["hiding"] = _HIDING_FOR.get(objective, "white_on_white")
        if objective == "data":  # plant a canary for the deterministic oracle (fixed tokens, ok to re-deliver)
            line, tokens = canary(state["surface"], vocabulary)
            updates["content"] = f"{payload.content}\n{line}"
            updates["oracle"] = tokens
        payload = payload.model_copy(update=updates)
        # Deliver up to `ceiling` times, evaluating each; stop at the first success. The
        # deciding (attempt, verdict) — the winner, or the last failure — is what we carry.
        attempt: AttackAttempt | None = None
        verdict: Verdict | None = None
        for index in range(1, ceiling + 1):
            response = transport.deliver(target, visible=carrier, hidden=payload.content,
                                         hiding=updates.get("hiding"))
            attempt = AttackAttempt(
                id=uuid.uuid4().hex[:8], payload=payload, surface=state["surface"],
                raw_response=response, delivery_index=index, delivery_ceiling=ceiling,
            )
            verdict = evaluate(attempt, control, tools=tools)
            if verdict.succeeded:
                break
        attempts.append(attempt)  # type: ignore[arg-type]
        verdicts.append(verdict)  # type: ignore[arg-type]
    return {"attempts": attempts, "verdicts": verdicts, "delivery_ceiling": ceiling}


def _assess(state: CampaignState) -> dict:
    control, target = state["control_response"], state["target"]
    element = state.get("surface_element") or state["surface"]
    verdicts = {v.attempt_id: v for v in state.get("verdicts", [])}
    findings: list[Finding] = []
    for attempt in state["attempts"]:
        verdict = verdicts.get(attempt.id)
        if verdict is None or not verdict.succeeded:
            continue
        objective = attempt.payload.objective
        findings.append(
            Finding(
                fingerprint=fingerprint(objective, attempt.payload.technique, element),
                location=state.get("surface_element", ""),
                severity=severity_for(objective, target),  # type: ignore[arg-type]
                objective=objective,
                business_impact=impact(objective, target, where=element),
                reproduction=attempt,
                control_diff=(
                    f"Control: {' '.join(control.split())[:160]} || "
                    f"Injected: {' '.join(attempt.raw_response.split())[:160]}"
                ),
                remediation=remediate(objective, attempt.payload.technique),
            )
        )
    return {"findings": findings}


def build_graph(checkpointer=None):
    graph = StateGraph(CampaignState)
    graph.add_node("classify", _classify)
    graph.add_node("attack", _attack)
    graph.add_node("assess", _assess)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", _route, {"attack": "attack", "unknown": END})
    graph.add_edge("attack", "assess")
    graph.add_edge("assess", END)
    return graph.compile(checkpointer=checkpointer)
