"""Surface detection: given a loaded page, decide what input surface a target exposes
so the transport knows how to deliver a payload. DOM heuristics only (no LLM/vision).

Phase 0 recognizes `pdf_upload`; `text_chat` delivery + detection land in Phase 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class Surface:
    kind: Literal["pdf_upload", "text_chat", "unknown"]
    input_selector: str | None = None


# Candidate elements for any attack surface we might recognize — wait for one to appear.
_CANDIDATES = 'input[type="file"], textarea, input[type="text"], [contenteditable="true"]'


class SurfaceDetector:
    def detect(self, page, timeout_ms: int = 15000) -> Surface:
        """Classify the target's attack surface from its DOM. SPAs render the surface
        after hydration, so wait for a candidate element before classifying."""
        try:
            # state="attached": the file input is often hidden behind a styled dropzone.
            page.wait_for_selector(_CANDIDATES, state="attached", timeout=timeout_ms)
        except Exception:
            pass  # nothing recognizable appeared within the window
        if page.query_selector('input[type="file"]'):
            return Surface(kind="pdf_upload", input_selector='input[type="file"]')
        return Surface(kind="unknown")
