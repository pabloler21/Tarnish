"""Run a full campaign against a target: build the graph, invoke it (checkpointed), assemble a
CampaignResult, diff against the previous run, and persist the JSON report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from langfuse import observe

from .authz import assert_authorized
from .baseline import apply_status
from .checkpointer import get_checkpointer
from .config import load_target
from .langfuse_setup import get_langfuse
from .orchestrator import DEFAULT_TASKS, build_graph
from .schemas import CampaignResult


def _coverage(tasks: list[tuple[str, str]], findings) -> dict:
    coverage: dict[str, dict[str, int]] = {}
    for _family, objective in tasks:
        coverage.setdefault(objective, {"attempts": 0, "successes": 0})["attempts"] += 1
    for finding in findings:
        coverage.setdefault(finding.objective, {"attempts": 0, "successes": 0})["successes"] += 1
    return coverage


def _persist(result: CampaignResult, reports_dir: str = "reports") -> Path:
    Path(reports_dir).mkdir(exist_ok=True)
    path = Path(reports_dir) / f"{result.target.id}-{result.created_at.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


@observe(name="campaign")
def run_campaign(
    target_id: str = "aurea",
    *,
    tasks: list[tuple[str, str]] | None = None,
    headless: bool = True,
    max_tasks: int | None = None,
) -> tuple[CampaignResult, Path]:
    get_langfuse()  # init before any @observe span
    target = load_target(target_id)
    assert_authorized(target)

    tasks = list(tasks or DEFAULT_TASKS)
    if max_tasks:
        tasks = tasks[:max_tasks]

    graph = build_graph(get_checkpointer())
    thread = f"{target_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
    final = graph.invoke(
        {"target": target, "tasks": tasks, "headless": headless},
        {"configurable": {"thread_id": thread}},
    )

    findings = final.get("findings", []) or []
    result = CampaignResult(
        target=target,
        findings=findings,
        control_baseline=final.get("control_response", ""),
        coverage=_coverage(tasks, findings),
    )
    result = apply_status(result, target_id)
    path = _persist(result)
    get_langfuse().flush()
    return result, path
