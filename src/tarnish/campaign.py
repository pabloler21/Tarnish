"""Run a full campaign against a target: build the graph, invoke it (checkpointed), assemble a
CampaignResult, diff against the previous run, and persist the JSON report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from langfuse import observe

from .authz import assert_authorized
from .baseline import apply_status, write_baseline
from .checkpointer import get_checkpointer
from .langfuse_setup import get_langfuse
from .orchestrator import DEFAULT_TASKS, build_graph
from .schemas import CampaignResult, RepoProfile, TargetProfile


def _coverage(tasks: list[tuple[str, str]], findings) -> dict:
    """Count attempts and successful findings grouped by objective.

    Example return: {"instruction": {"attempts": 1, "successes": 0},
    "data": {"attempts": 1, "successes": 1}}.
    """
    coverage: dict[str, dict[str, int]] = {}
    for _family, objective in tasks:
        coverage.setdefault(objective, {"attempts": 0, "successes": 0})["attempts"] += 1
    for finding in findings:
        coverage.setdefault(finding.objective, {"attempts": 0, "successes": 0})["successes"] += 1
    return coverage


def _persist(result: CampaignResult, reports_dir: str = "reports") -> Path:
    """Write the campaign result as a timestamped JSON file.

    Example return: Path("reports/victim-20260827T135103.json").
    """
    Path(reports_dir).mkdir(exist_ok=True)
    path = Path(reports_dir) / f"{result.target.id}-{result.created_at.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


@observe(name="campaign")
def run_campaign(
    target: TargetProfile | RepoProfile,
    *,
    mode: str = "live",
    tasks: list[tuple[str, str]] | None = None,
    headless: bool = True,
    max_tasks: int | None = None,
) -> tuple[CampaignResult, Path]:
    """Run the campaign and return its result plus the saved JSON report path.

    Example return: (CampaignResult(findings=[...]),
    Path("reports/victim-20260827T135103.json")).
    """
    get_langfuse()  # init before any @observe span
    assert_authorized(target)

    tasks = list(tasks or DEFAULT_TASKS)
    if max_tasks:
        tasks = tasks[:max_tasks]

    graph = build_graph(get_checkpointer())
    thread = f"{target.id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
    final = graph.invoke(
        {"target": target, "tasks": tasks, "headless": headless, "mode": mode},
        {"configurable": {"thread_id": thread}},
    )

    findings = final.get("findings", []) or []
    result = CampaignResult(
        target=target,
        findings=findings,
        control_baseline=final.get("control_response", ""),
        coverage=_coverage(tasks, findings),
        delivery_ceiling=final.get("delivery_ceiling", 1),
    )
    result = apply_status(result, target.id)
    path = _persist(result)
    if mode == "harness":  # the committed gate file lives in the user's repo, not ours
        write_baseline(result, target.root)
    get_langfuse().flush()
    return result, path
