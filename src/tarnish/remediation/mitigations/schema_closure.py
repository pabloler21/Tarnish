"""Constrain the evaluator's output to a closed schema so a payload cannot hijack it into free
text ('output HIRE only'). The model can emit only these fields."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClosedEvaluation(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["reject", "maybe", "advance"]
    reasons: list[str] = Field(default_factory=list, max_length=5)
