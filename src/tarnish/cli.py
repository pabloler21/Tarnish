"""Tarnish CLI (Typer): `init` -> `explore` -> `check`, plus `report` and the Phase-0 `gate0`.
`check --fix` (M3) and a CI subcommand (Phase 3) are the ones still missing."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from langfuse import observe

from . import recon
from .authz import assert_authorized
from .backends import resolve_attacker_backend, resolve_backend
from .baseline import load_baseline
from .campaign import run_campaign
from .checkr import exit_code, run_check
from .config import load_target
from .cv import BENIGN_CV
from .langfuse_setup import get_langfuse, tracing_enabled
from .llm import attacker_can_generate, harness_has_privilege_gap
from .reporting.render import render_to_file
from .schemas import CampaignResult
from .transport.browser import BrowserTransport

app = typer.Typer(help="Tarnish — autonomous AI red-teaming (find -> fix -> verify).")


@app.callback()
def _root() -> None:
    """Keep subcommands named instead of collapsing the app into one default command."""


def _tracing_hint() -> None:
    """Say it once, at the end, ruff-style. Never a warning, never repeated."""
    if not tracing_enabled():
        typer.echo("tracing off — set LANGFUSE_PUBLIC_KEY/SECRET_KEY to trace this campaign")


def _privilege_gap_hint() -> None:
    """`explore` and `check` both run the harness through `get_target_model()`; a backend with no
    system-prompt channel over-reports on either command, so both must say so — `check` runs
    unattended (CI), so silence there is worse: a red build with nothing on stdout explaining why."""
    if not harness_has_privilege_gap():
        typer.echo(
            "Note: this backend has no system-prompt channel, so the harness runs your prompt "
            "at the same privilege as the payload. There is no hierarchy for an injection to "
            "cross, and findings will over-report. Use claude or an API key, or --live."
        )


@observe(name="gate0-benign-request")
def _benign_request(target, content: str, *, headless: bool = True) -> str:
    lf = get_langfuse()
    response = BrowserTransport(headless=headless).deliver(target, visible=content)
    lf.update_current_span(
        input={"target": target.id, "url": target.url, "cv_chars": len(content)},
        output={"status": "ok", "response_preview": response[:500]},
        metadata={"phase": "0", "gate": "gate0", "benign": True},
    )
    return response


@app.command()
def gate0(
    target: str = typer.Option("aurea", help="Target profile id (targets/<id>.yaml)."),
    headless: bool = typer.Option(True, help="Run the browser headless."),
):
    """Phase 0 gate: send ONE benign request to the target and trace it in Langfuse. No attacks."""
    get_langfuse()  # configure env + init the Langfuse client BEFORE the first @observe span
    profile = load_target(target)
    assert_authorized(profile)

    response = _benign_request(profile, BENIGN_CV, headless=headless)
    get_langfuse().flush()

    typer.echo(f"Benign request delivered to '{profile.id}'. Response preview:")
    typer.echo(response[:1000])
    _tracing_hint()


@app.command()
def init(root: Path = typer.Argument(Path("."), help="The repo to profile.")):
    """Read the repo and write .tarnish/profile.json: surfaces, system prompt, tool inventory."""
    profile = recon.profile_repo(root)
    path = recon.write_profile(profile)
    typer.echo(f"{profile.name}: {profile.language}, {len(profile.surfaces)} surface(s), "
               f"{len(profile.tools)} tool(s)")
    for s in profile.surfaces:
        typer.echo(f"  {s.kind:16} {s.file}:{s.line} ({s.symbol})")
    for t in profile.tools:
        typer.echo(f"  tool             {t.name}{'  [side effect]' if t.side_effect else ''}")
    typer.echo(f"Profile: {path}")
    _tracing_hint()


@app.command()
def explore(
    root: Path = typer.Option(Path("."), help="Repo to attack (harness mode, the default)."),
    live: str = typer.Option("", help="Attack a running target instead: targets/<id>.yaml."),
    headless: bool = typer.Option(True, help="Browser headless (--live only)."),
    max_tasks: int = typer.Option(0, help="Cap the number of attack tasks (0 = all)."),
    report: bool = typer.Option(True, help="Also render the HTML report next to the JSON."),
):
    """The full campaign: 3 RAG specialists -> evaluate vs control -> remediate -> report.
    Harness mode reconstructs the target from .tarnish/profile.json; --live drives the browser."""
    get_langfuse()  # configure env + init the client BEFORE run_campaign's @observe span opens
    target = load_target(live) if live else recon.load_profile(root)
    if not live:
        _privilege_gap_hint()
    if attacker_can_generate():
        # The honest counterpart to the warning below: generation only works because it resolved
        # to an API backend, which spends a key — on a product whose headline is "no API key".
        # Name the OTHER roles' backend too rather than assuming a CLI: with no agent CLI on PATH
        # `resolve_backend` falls through to the same API key and every role is billed.
        typer.echo(
            f"Note: attack payloads are generated on `{resolve_attacker_backend()}`, a billed API "
            f"key (both agent CLIs refuse to generate). Every other role runs on "
            f"`{resolve_backend()}`."
        )
    else:
        typer.echo(
            "Note: no backend here will generate attack payloads (both the claude and codex CLIs "
            "refuse), so the campaign will find nothing. Set OPENAI_API_KEY / ANTHROPIC_API_KEY."
        )
    result, json_path = run_campaign(
        target, mode="live" if live else "harness",
        headless=headless, max_tasks=max_tasks or None,
    )

    typer.echo(f"Campaign complete. {len(result.findings)} finding(s). JSON: {json_path}")
    for f in result.findings:
        location = f" {f.location}" if f.location else ""
        typer.echo(f"  [{f.severity}] {f.objective} via {f.reproduction.payload.technique}"
                   f"{location} ({f.status})")
    if report:
        typer.echo(f"Report: {render_to_file(result, json_path.with_suffix('.html'))}")
    _tracing_hint()


@app.command()
def check(root: Path = typer.Argument(Path("."), help="The repo to check.")):
    """Replay the payloads `explore` proved: a CI exit code, deterministic where it can be — each
    row names the instrument that decided it. No campaign, but it does run the target model, and
    the judge whenever an oracle cannot decide."""
    profile = recon.load_profile(root)
    baseline = load_baseline(root, profile.id)
    if not baseline.proofs:
        typer.echo("Nothing to replay. Run `tarnish explore` first.")
        raise typer.Exit(0)

    _privilege_gap_hint()
    try:
        rows = run_check(profile, baseline)
    except ValueError as e:
        # A stored proof can name a surface kind the profile no longer has (the repo was
        # reorganized and re-`init`ed). Not a verdict about the target — an unverifiable gate,
        # reported and failed, never a traceback.
        typer.echo(f"Baseline is stale: {e}")
        typer.echo("Run `tarnish explore` to rebuild it against the current profile.")
        raise typer.Exit(1) from None

    for row in rows:
        typer.echo(f"  [{row.severity}] {row.objective} {row.fingerprint} — {row.status}"
                   f"  ({row.instrument})")
        typer.echo(f"      {row.evidence[:160]}")
    code = exit_code(rows)
    typer.echo(
        f"{sum(r.status in ('open', 'regression') for r in rows)} reproducing / {len(rows)} checked"
        # "nothing reproduced", not "clean": each proof was delivered once, and a proof that
        # reproduces intermittently lands here. Exit 0 is the gate's decision, not a clean bill.
        + ("" if code else " — nothing reproduced this run")
    )
    if code:
        typer.echo("Run `tarnish check --fix` to apply and verify the mitigation.  [M3]")
    raise typer.Exit(code)


@app.command()
def report(
    json_path: Path = typer.Argument(..., help="A campaign JSON report to render to HTML."),
):
    """Render an existing campaign JSON report to the four-part HTML report."""
    result = CampaignResult.model_validate_json(json_path.read_text(encoding="utf-8"))
    html_path = render_to_file(result, json_path.with_suffix(".html"))
    typer.echo(f"Report: {html_path}")


def main() -> None:
    # Targets return arbitrary unicode; don't let a Windows cp1252 console crash the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    app()


if __name__ == "__main__":
    main()
