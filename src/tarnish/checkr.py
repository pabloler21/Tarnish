# src/tarnish/checkr.py
"""`check`: replay what `explore` proved. No graph, no RAG, no specialists. This is the CI gate.

Deterministic where it can be, and it tells you when it isn't. Two oracles decide without a model
(`oracle:tool-call`, `oracle:canary`); everything else falls through to the LLM judge, and each row
names whichever instrument decided it. Even a deterministic instrument is reading a
non-deterministic target: the same proof delivered five times to the same unchanged target
reproduced once (measured 2026-08-28), and `run_check` delivers it once.
It writes nothing: recording a fix is `--fix`'s job (M3)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

from .evaluator import evaluate
from .remediation.static_map import severity_for
from .schemas import Baseline, RepoProfile
from .transport.harness import HarnessTransport

# `not_reproducing`, NOT `fixed`: one delivery of the proof produced no verdict. That is an
# observation about this run, not evidence anyone closed the hole.
Status = Literal["open", "regression", "accepted", "not_reproducing"]


class CheckRow(BaseModel):
    fingerprint: str
    objective: str
    severity: str
    status: Status
    evidence: str
    # Which instrument decided: "oracle:tool-call" and "oracle:canary" are deterministic, a
    # model id means the LLM judge ran. The gate says so rather than claiming a blanket
    # determinism it cannot deliver.
    instrument: str = ""


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
            tools=profile.tools,
        )
        prior = baseline.fingerprints.get(fingerprint_)
        if not verdict.succeeded:
            status: Status = "not_reproducing"
        elif prior == "not_reproducing":
            # It did not reproduce when the baseline was written and it does now. Worth flagging,
            # but it names a change in observation — it does not assert you had closed it.
            status = "regression"
        else:
            status = "accepted" if prior == "accepted" else "open"
        rows.append(CheckRow(
            fingerprint=fingerprint_, objective=proof.payload.objective,
            severity=severity_for(proof.payload.objective, profile),  # same rule `explore` used
            status=status, evidence=verdict.evidence, instrument=verdict.judge_model,
        ))
    return rows


def exit_code(rows: list[CheckRow]) -> int:
    """Non-zero breaks the build. `accepted` is a decision you made; `not_reproducing` passes.

    `not_reproducing` passing is a deliberate instrument choice, not an assertion that the finding
    is fixed: `run_check` delivers each proof once, and a proof that reproduces intermittently can
    land here. Whether a flaky proof should break the build is an open product decision."""
    return int(any(row.status in ("open", "regression") for row in rows))
