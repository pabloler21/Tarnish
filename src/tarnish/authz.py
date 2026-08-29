"""Authorization gate. Non-negotiable: Tarnish only attacks targets the operator owns.
Phase 0-2 assert `owner_verified`; Phase 3 replaces the assertion with real proof-of-ownership."""

from __future__ import annotations

from pathlib import Path

from .schemas import RepoProfile, TargetProfile


class AuthorizationError(RuntimeError):
    pass


def assert_authorized(target: TargetProfile | RepoProfile) -> None:
    """Live targets must be owner-verified. Repo targets must be the checkout you are standing
    in — you cannot point Tarnish at someone else's clone on the same disk."""
    if isinstance(target, RepoProfile):
        root = Path(target.root).resolve()
        if not root.is_relative_to(Path.cwd().resolve()):
            raise AuthorizationError(
                f"Repo '{root}' is outside the working directory. Tarnish only attacks the "
                "checkout you are standing in — cd into the repo and run it there."
            )
        return
    if not target.owner_verified:
        raise AuthorizationError(
            f"Target '{target.id}' is not owner-verified. Tarnish only attacks targets the "
            "operator has proven they own. Set owner_verified: true in the target profile "
            "(real ownership proof — DNS TXT / file-at-path / prompt token — lands in Phase 3)."
        )
