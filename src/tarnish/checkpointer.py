"""LangGraph checkpointer (SqliteSaver) so a campaign persists and remediation can resume
against it without re-attacking. The graph itself lands in Phase 1; this wires the store."""

from __future__ import annotations

import os
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from .config import get_settings


def get_checkpointer(db_path: str | None = None) -> SqliteSaver:
    path = db_path or get_settings().checkpoint_db
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()  # idempotent: create checkpoint tables on first use
    return saver
