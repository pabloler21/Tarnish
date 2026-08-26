# src/tarnish/checkr.py
"""`check`: replay what `explore` proved. No graph, no RAG, no specialists.

Deterministic in VERDICT, not in transcript — the target answers differently every time, and the
mandatory control plus the canary oracle produce a binary result anyway. This is the CI gate.
It writes nothing: recording a fix is `--fix`'s job (M3)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

from .evaluator import evaluate
from .remediation.static_map import severity_for
from .schemas import Baseline, RepoProfile
from .transport.harness import HarnessTransport

Status = Literal["open", "regression", "accepted", "fixed"]


class CheckRow(BaseModel):
    fingerprint: str
    objective: str
    severity: str
    status: Status
    evidence: str


def run_check(profile: RepoProfile, baseline: Baseline, transport=None) -> list[CheckRow]:
    rows: list[CheckRow] = []
    controls: dict[str, str] = {}  # one control per surface kind, not per payload
    for fingerprint_, proof in baseline.proofs.items():
        target = transport or HarnessTransport(profile, surface_kind=proof.surface)
        carrier = target.control_input(profile)
        if proof.surface not in controls:
            controls[proof.surface] = target.deliver(profile, visible=carrier)
        response = target.deliver(profile, visible=carrier, hidden=proof.payload.content)
        verdict = evaluate(
            proof.model_copy(update={"id": uuid.uuid4().hex[:8], "raw_response": response}),
            controls[proof.surface],
        )
        prior = baseline.fingerprints.get(fingerprint_)
        if not verdict.succeeded:
            status: Status = "fixed"
        elif prior == "fixed":
            status = "regression"  # you closed this and it came back
        else:
            status = "accepted" if prior == "accepted" else "open"
        rows.append(CheckRow(
            fingerprint=fingerprint_, objective=proof.payload.objective,
            severity=severity_for(proof.payload.objective, profile),  # same rule `explore` used
            status=status, evidence=verdict.evidence,
        ))
    return rows


def exit_code(rows: list[CheckRow]) -> int:
    """Non-zero breaks the build. `accepted` is a decision you made; `fixed` is good news."""
    return int(any(row.status in ("open", "regression") for row in rows))
