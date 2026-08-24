"""The Transport abstraction. A specialist hands the transport a payload; the transport
decides *how* to deliver it. Strategy (technique) is separated from transport (channel)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import TargetProfile


@runtime_checkable
class Transport(Protocol):
    channel: str

    def deliver(
        self, target: TargetProfile, content: str, *, hiding: str | None = None
    ) -> str:
        """Render `content` into the channel medium and deliver it; return the raw response text.
        `hiding` is a PDF-channel-only concern (Phase 1); other channels ignore it."""
        ...
