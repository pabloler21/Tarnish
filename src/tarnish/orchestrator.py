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
from .cv import BENIGN_CV
from .evaluator import evaluate
from .fingerprint import fingerprint
from .remediation.static_map import remediate, severity_for
from .schemas import AttackAttempt, Finding, TargetProfile
from .transport.browser import BrowserTransport

SPECIALISTS = {"injection": INJECTION, "leakage": LEAKAGE, "business_logic": BUSINESS_LOGIC}

# Default (specialist, objective) tasks a campaign runs against a CV-evaluator surface.
DEFAULT_TASKS: list[tuple[str, str]] = [
    ("injection", "data"),
    ("injection", "instruction"),
    ("business_logic", "logic"),
    ("leakage", "leak"),
    ("leakage", "jailbreak"),
]

_IMPACT = {
    "instruction": "An attacker can hijack the evaluation with a hidden instruction, forcing a chosen verdict regardless of the real resume.",
    "data": "An attacker can inflate their evaluation with fabricated skills or experience the model treats as true.",
    "leak": "An attacker can extract the evaluator's hidden scoring criteria or system prompt, enabling targeted gaming.",
    "jailbreak": "An attacker can push the evaluator outside its intended task, bypassing its scope and safety guards.",
    "logic": "An attacker can abuse the evaluator's business logic to force a favorable verdict or process out-of-scope input.",
}


class CampaignState(TypedDict, total=False):
    target: TargetProfile
    tasks: list[tuple[str, str]]
    headless: bool
    surface: str
    control_response: str
    attempts: list[AttackAttempt]
    findings: list[Finding]
    route: str


def _classify(state: CampaignState) -> dict:
    target = state["target"]
    transport = BrowserTransport(headless=state.get("headless", True))
    surface = transport.classify_surface(target)
    if surface != "pdf_upload":
        return {"surface": surface, "route": "unknown", "control_response": ""}
    control = transport.deliver(target, visible=BENIGN_CV)  # the mandatory control
    return {"surface": surface, "route": "attack", "control_response": control}


def _route(state: CampaignState) -> str:
    return state["route"]


def _attack(state: CampaignState) -> dict:
    target = state["target"]
    transport = BrowserTransport(headless=state.get("headless", True))
    attempts: list[AttackAttempt] = []
    for family, objective in state["tasks"]:
        payload = SPECIALISTS[family].generate(target, objective)  # type: ignore[arg-type]
        response = transport.deliver(
            target, visible=BENIGN_CV, hidden=payload.content, hiding="white_on_white"
        )
        attempts.append(
            AttackAttempt(id=uuid.uuid4().hex[:8], payload=payload,
                          surface=state["surface"], raw_response=response)
        )
    return {"attempts": attempts}


def _assess(state: CampaignState) -> dict:
    control = state["control_response"]
    findings: list[Finding] = []
    for attempt in state["attempts"]:
        verdict = evaluate(attempt, control)
        if not verdict.succeeded:
            continue
        objective = attempt.payload.objective
        findings.append(
            Finding(
                fingerprint=fingerprint(objective, attempt.payload.technique, state["surface"]),
                severity=severity_for(objective),  # type: ignore[arg-type]
                objective=objective,
                business_impact=_IMPACT[objective],
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
