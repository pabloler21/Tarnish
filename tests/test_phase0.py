"""Phase 0 checks: target loading + authz gate, PDF crafting, checkpointer persistence.
The browser transport (delivery) is covered in test_browser_transport.py."""

from __future__ import annotations

import operator
from typing import Annotated

import pytest
from typing_extensions import TypedDict

from tarnish.authz import AuthorizationError, assert_authorized
from tarnish.checkpointer import get_checkpointer
from tarnish.config import load_target
from tarnish.schemas import TargetProfile
from tarnish.transport.pdf_channel import PDFChannel


class _State(TypedDict):
    # Module-level so LangGraph's get_type_hints can resolve Annotated (fails if nested in a func).
    messages: Annotated[list, operator.add]


def test_target_loads_with_expected_fields():
    t = load_target("aurea")
    assert t.id == "aurea"
    assert t.surface == "auto"
    assert t.url.startswith("http")
    assert t.owner_verified is True


def test_authz_gate_blocks_unverified_targets():
    unverified = TargetProfile(
        id="x", name="x", url="https://example.com",
        owner_verified=False, target_model_family="openai",
    )
    with pytest.raises(AuthorizationError):
        assert_authorized(unverified)
    # verified target passes silently
    assert assert_authorized(load_target("aurea")) is None


def test_pdf_render_produces_valid_pdf_bytes():
    pdf = PDFChannel().render("Hello\nWorld")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 100


def test_checkpointer_persists_state_across_invocations(tmp_path):
    """Prove the SqliteSaver is wired: a trivial graph accumulates state across calls on one thread."""
    from langgraph.graph import START, END, StateGraph

    checkpointer = get_checkpointer(str(tmp_path / "cp.sqlite"))
    graph = (
        StateGraph(_State)
        .add_node("respond", lambda s: {"messages": ["ack"]})
        .add_edge(START, "respond")
        .add_edge("respond", END)
        .compile(checkpointer=checkpointer)
    )
    config = {"configurable": {"thread_id": "t1"}}
    graph.invoke({"messages": ["hi"]}, config)
    out = graph.invoke({"messages": ["again"]}, config)
    assert len(out["messages"]) == 4  # persisted: hi, ack, again, ack
