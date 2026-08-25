"""The campaign graph's conditional routing: an unknown/unsupported surface stops before any
attack (the needs_clarification path). Browser + LLM are mocked out."""

from __future__ import annotations

from tarnish import orchestrator
from tarnish.schemas import TargetProfile


def test_graph_routes_unsupported_surface_to_end(monkeypatch):
    class _FakeTransport:
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
