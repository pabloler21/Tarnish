"""Pydantic data models. Phase 0 only needs TargetProfile; the rest of PLAN.md section 5
(Payload, AttackAttempt, Verdict, Remediation, Finding, ...) lands when each phase needs it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TargetProfile(BaseModel):
    id: str
    name: str
    url: str  # the target's web page; the browser transport drives its real input surface
    owner_verified: bool  # authorization gate (real ownership proof enforced in Phase 3)
    # OPTIONAL, best-effort auto-detected — never required. Operators paste a URL and don't
    # know their model; falsifiability comes from the mandatory control, not the judge family.
    target_model_family: str | None = None
    system_prompt: str | None = None  # if exposed, enables prompt_level verification (Phase 2)
    # "auto" = detect the surface from the DOM; override only when detection fails.
    surface: Literal["auto", "pdf_upload", "text_chat"] = "auto"
