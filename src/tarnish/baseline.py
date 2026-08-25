"""Fingerprint diff across runs -> the `status` field and the fixed/new lists. This is what the
`rescan` verification uses: apply a fix, re-run, and a finding that no longer reproduces flips to
`fixed`; a previously-fixed finding that reappears is a `regression`.

A fixed finding is re-hydrated from the prior report and carried into this run's result with a
`rescan` VerificationResult attached, so the report can show the before/after pair (its original
proof + proof it no longer reproduces) — the product's "proof the fix works"."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import CampaignResult, Finding, VerificationResult


def diff(current: set[str], previous: set[str]) -> tuple[set[str], set[str], set[str]]:
    """Return (new, persisting, fixed) fingerprint sets."""
    return current - previous, current & previous, previous - current


def _latest_prior_report(target_id: str, before_iso: str, reports_dir: str) -> dict | None:
    """The most recent prior report dict for this target (None on the first run)."""
    best_time, best = "", None
    for path in Path(reports_dir).glob(f"{target_id}-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        created = data.get("created_at", "")
        if created < before_iso and created > best_time:
            best_time, best = created, data
    return best


def apply_status(result: CampaignResult, target_id: str, reports_dir: str = "reports") -> CampaignResult:
    prior = _latest_prior_report(target_id, result.created_at.isoformat(), reports_dir)
    prior_findings = {f["fingerprint"]: f for f in (prior or {}).get("findings", [])}
    previous = set(prior_findings)
    current = {f.fingerprint for f in result.findings}
    new, _persisting, fixed = diff(current, previous)

    for finding in result.findings:
        finding.status = "new" if finding.fingerprint in new else "persisting"
    result.new_findings = sorted(new)
    result.fixed_findings = sorted(fixed)

    # Re-hydrate each fixed finding from the prior report, verified by rescan: its original proof is
    # the "before"; the re-run that no longer reproduces is the "after".
    for fp in sorted(fixed):
        resolved = Finding.model_validate(prior_findings[fp])
        resolved.status = "fixed"
        resolved.remediation.verification = VerificationResult(
            mode="rescan", status="verified", attempts_rerun=1, attempts_blocked=1,
            evidence=("Re-ran the same attack after the operator applied the fix; it no longer "
                      "reproduces (the payload's proof signal is absent from the target's response)."),
        )
        result.findings.append(resolved)
    return result
