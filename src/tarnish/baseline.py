"""Fingerprint diff across runs -> the `status` field and the fixed/new lists. This is what the
`rescan` verification uses: apply a fix, re-run, and a finding that no longer reproduces flips to
`fixed`; a previously-fixed finding that reappears is a `regression`.

A fixed finding is re-hydrated from the prior report and carried into this run's result. A `rescan`
VerificationResult — the product's "proof the fix works" — is attached only when `fix_applied=True`,
i.e. a fix was actually applied (M3's `--fix`, or a manual rescan). In the MVP nothing is applied
through Tarnish, so by default the finding merely stopped reproducing: honest per the project's
convention, `verification: None` = proposed, not verified."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import Baseline, CampaignResult, Finding, VerificationResult


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


def apply_status(result: CampaignResult, target_id: str, reports_dir: str = "reports",
                  fix_applied: bool = False) -> CampaignResult:
    prior = _latest_prior_report(target_id, result.created_at.isoformat(), reports_dir)
    prior_findings = {f["fingerprint"]: f for f in (prior or {}).get("findings", [])}
    previous = set(prior_findings)
    current = {f.fingerprint for f in result.findings}
    new, _persisting, fixed = diff(current, previous)

    for finding in result.findings:
        finding.status = "new" if finding.fingerprint in new else "persisting"
    result.new_findings = sorted(new)
    result.fixed_findings = sorted(fixed)

    # A fingerprint that was present before and is absent now goes into fixed_findings for the
    # diff and the regression gate either way. But a `rescan verified` VerificationResult claims a
    # fix was applied and proven — true only when one actually was. In the MVP nothing is applied
    # through Tarnish, so `fix_applied` is False and we re-hydrate the finding WITHOUT that claim.
    for fp in sorted(fixed):
        resolved = Finding.model_validate(prior_findings[fp])
        resolved.status = "fixed"
        if fix_applied:
            resolved.remediation.verification = VerificationResult(
                mode="rescan", status="verified", attempts_rerun=1, attempts_blocked=1,
                evidence=("Re-ran the same attack after the operator applied the fix; it no longer "
                          "reproduces (the payload's proof signal is absent from the response)."),
            )
        else:
            resolved.remediation.verification = None  # honest: it stopped reproducing; unproven as a fix
        result.findings.append(resolved)
    return result


def baseline_path(root: str | Path) -> Path:
    return Path(root) / ".tarnish" / "baseline.json"


def load_baseline(root: str | Path, target_id: str) -> Baseline:
    path = baseline_path(root)
    if not path.exists():
        return Baseline(target_id=target_id)
    try:
        return Baseline.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as e:  # malformed JSON or a schema mismatch (both subclass ValueError)
        raise RuntimeError(
            f"{path} is unreadable — corrupt, or holding unresolved merge conflict markers: {e}"
        ) from e


def write_baseline(result: CampaignResult, root: str | Path) -> Path:
    """Merge this run into the committed gate file: refresh the proofs `check` replays, record
    what got fixed, keep prior suppressions. NEVER auto-accept a finding — an accepted entry is
    a human decision, and inventing one here would make the CI gate green forever."""
    baseline = load_baseline(root, result.target.id)
    for finding in result.findings:
        baseline.proofs[finding.fingerprint] = finding.reproduction
    for fingerprint_ in result.fixed_findings:
        baseline.fingerprints[fingerprint_] = "fixed"
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
    return path
