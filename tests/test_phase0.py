"""Phase 0 checks: target loading + authz gate, PDF render, transport POST, checkpointer persistence.
These prove the Gate 0 plumbing without needing Aurea or Langfuse keys."""

from __future__ import annotations

import operator
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
    assert t.channel == "pdf"
    assert t.owner_verified is True


def test_authz_gate_blocks_unverified_targets():
    unverified = TargetProfile(
        id="x", name="x", channel="pdf", endpoint="http://x",
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


def test_pdf_channel_delivers_via_http():
    """End-to-end transport (minus Langfuse): render a clean PDF and POST it to a local server."""
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = self.rfile.read(length)
            received["ctype"] = self.headers.get("Content-Type", "")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"verdict": "ok"}')

        def log_message(self, *args):  # silence test server logging
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    port = server.server_address[1]

    target = TargetProfile(
        id="local", name="local", channel="pdf",
        endpoint=f"http://127.0.0.1:{port}/evaluate",
        owner_verified=True, target_model_family="openai",
    )
    response = PDFChannel().deliver(target, "Jane Doe\nEngineer")

    assert response == '{"verdict": "ok"}'
    assert received["ctype"].startswith("multipart/form-data")
    assert b"%PDF" in received["body"]  # the PDF actually rode the request


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
