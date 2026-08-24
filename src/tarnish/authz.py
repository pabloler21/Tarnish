"""Authorization gate. Non-negotiable: Tarnish only attacks targets the operator owns.
Phase 0-2 assert `owner_verified`; Phase 3 replaces the assertion with real proof-of-ownership."""

from __future__ import annotations

from .schemas import TargetProfile


class AuthorizationError(RuntimeError):
    pass


def assert_authorized(target: TargetProfile) -> None:
    if not target.owner_verified:
        raise AuthorizationError(
            f"Target '{target.id}' is not owner-verified. Tarnish only attacks targets the "
            "operator has proven they own. Set owner_verified: true in the target profile "
            "(real ownership proof — DNS TXT / file-at-path / prompt token — lands in Phase 3)."
        )
