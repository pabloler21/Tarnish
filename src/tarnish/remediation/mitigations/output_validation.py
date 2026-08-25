"""Validate the target's response before trusting it: reject outputs that leak the system
prompt/rubric or otherwise look hijacked. A post-response guard."""

from __future__ import annotations

import re

_LEAK_MARKERS = re.compile(
    r"system prompt|scoring rubric|my instructions|you are a|ignore (all|previous)", re.I
)


def validate(response: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the response should be blocked/flagged."""
    if _LEAK_MARKERS.search(response):
        return False, "response appears to leak instructions or echo an injected command"
    return True, "ok"
