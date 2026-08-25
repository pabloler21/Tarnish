"""The Transport abstraction. A specialist hands the transport a payload; the transport
decides *how* to deliver it. Strategy (technique) is separated from transport (channel)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import TargetProfile


@runtime_checkable
class Transport(Protocol):
    channel: str

    def deliver(
        self,
        target: TargetProfile,
        *,
        visible: str,
        hidden: str | None = None,
        hiding: str | None = None,
    ) -> str:
        """Deliver to the target's surface and return the raw response text.
        `visible` is the carrier (a clean CV); `hidden`+`hiding` embed an attack payload inside it
        (PDF-only). Control runs pass `visible` alone; attacks pass `hidden`+`hiding`."""
        ...
