"""Reject out-of-scope documents: a CV evaluator should only process CV-like inputs, not a menu,
an essay, or a general question dressed up as a 'resume'."""

from __future__ import annotations

_CV_MARKERS = ("experience", "education", "skills", "work", "employment", "resume", "cv")


def is_in_scope(document_text: str) -> bool:
    text = document_text.lower()
    return sum(marker in text for marker in _CV_MARKERS) >= 2
