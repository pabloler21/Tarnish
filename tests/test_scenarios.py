"""scenarios.json is the declared attack matrix. Keep it well-formed and pinned to the closed
enums (a typo'd objective or an orphan family would silently drop coverage), and >=10 as PLAN.md
requires. Also assert DEFAULT_TASKS is a subset of the declared matrix."""

from __future__ import annotations

import json
from pathlib import Path

from tarnish.orchestrator import DEFAULT_TASKS, SPECIALISTS
from tarnish.schemas import HidingTechnique, Objective

_OBJECTIVES = set(Objective.__args__)
_HIDING = set(HidingTechnique.__args__)
_SCENARIOS = json.loads((Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]


def test_at_least_ten_scenarios():
    assert len(_SCENARIOS) >= 10


def test_scenarios_pin_to_closed_enums():
    ids = set()
    for s in _SCENARIOS:
        assert s["id"] not in ids, f"duplicate scenario id {s['id']}"
        ids.add(s["id"])
        assert s["family"] in SPECIALISTS, f"{s['id']}: unknown specialist {s['family']}"
        assert s["objective"] in _OBJECTIVES, f"{s['id']}: bad objective {s['objective']}"
        assert s["hiding"] in _HIDING, f"{s['id']}: bad hiding {s['hiding']}"
        assert s["objective"] in SPECIALISTS[s["family"]].objectives, \
            f"{s['id']}: {s['family']} does not own objective {s['objective']}"
        assert s["risk"].strip()


def test_default_tasks_are_declared_scenarios():
    declared = {(s["family"], s["objective"]) for s in _SCENARIOS}
    for task in DEFAULT_TASKS:
        assert task in declared, f"DEFAULT_TASKS entry {task} not in scenarios.json"
