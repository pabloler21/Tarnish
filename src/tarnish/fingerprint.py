"""The fingerprint contract (PLAN.md section 5, Phase 1 blocker).

`fingerprint` is a stable identity for "the same vulnerability" across runs: a normalized
hash of (objective, technique, attacked-surface element). It deliberately takes NO payload
text — so the same hole keeps the same identity even when the generated payload varies.
Without this, `status` (new/persisting/fixed/regression), regression detection, and the CI
gate do not work. Never hash the payload."""

from __future__ import annotations

import hashlib


def _normalize(part: str) -> str:
    return " ".join(part.strip().lower().split())


def fingerprint(objective: str, technique: str, surface_element: str) -> str:
    """Stable 16-hex-char identity for (objective, technique, surface_element)."""
    raw = "|".join(_normalize(p) for p in (objective, technique, surface_element))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
