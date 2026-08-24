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


class SurfaceDetector:
    def detect(self, page) -> Surface:
        """Classify the target's attack surface from its DOM."""
        if page.query_selector('input[type="file"]'):
            return Surface(kind="pdf_upload", input_selector='input[type="file"]')
        return Surface(kind="unknown")
