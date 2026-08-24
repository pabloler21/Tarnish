"""Pydantic data models. Phase 0 only needs TargetProfile; the rest of PLAN.md section 5
(Payload, AttackAttempt, Verdict, Remediation, Finding, ...) lands when each phase needs it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TargetProfile(BaseModel):
    id: str
    name: str
    channel: Literal["pdf", "chat"]
    endpoint: str
    owner_verified: bool  # authorization gate (real ownership proof enforced in Phase 3)
    target_model_family: str  # pins a different-family judge (anti score-inflation)
    system_prompt: str | None = None  # if exposed, enables prompt_level verification (Phase 2)

    # Delivery contract for the pdf channel — kept in config so a new target is a YAML edit.
    upload_field: str = "file"  # multipart field name the target expects
    upload_filename: str = "cv.pdf"
    headers: dict[str, str] = Field(default_factory=dict)
