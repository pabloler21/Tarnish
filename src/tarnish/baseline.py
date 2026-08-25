"""Fingerprint diff across runs → the `status` field and the fixed/new lists. This is what the
`rescan` verification uses: apply a fix, re-run, and a finding that no longer reproduces flips to
`fixed`; a previously-fixed finding that reappears is a `regression`."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import CampaignResult


def diff(current: set[str], previous: set[str]) -> tuple[set[str], set[str], set[str]]:
    """Return (new, persisting, fixed) fingerprint sets."""
    return current - previous, current & previous, previous - current


def _previous_fingerprints(target_id: str, before_iso: str, reports_dir: str) -> set[str]:
    """Fingerprints from the most recent prior report for this target."""
    best_time, best_fps = "", set()
    for path in Path(reports_dir).glob(f"{target_id}-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        created = data.get("created_at", "")
        if created < before_iso and created > best_time:
            best_time, best_fps = created, {f["fingerprint"] for f in data.get("findings", [])}
    return best_fps


def apply_status(result: CampaignResult, target_id: str, reports_dir: str = "reports") -> CampaignResult:
    previous = _previous_fingerprints(target_id, result.created_at.isoformat(), reports_dir)
    current = {f.fingerprint for f in result.findings}
    new, _persisting, fixed = diff(current, previous)
    for finding in result.findings:
        finding.status = "new" if finding.fingerprint in new else "persisting"
    result.new_findings = sorted(new)
    result.fixed_findings = sorted(fixed)
    return result
