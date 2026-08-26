"""Tarnish CLI (Typer). Phase 0 ships the `gate0` command; run/report/remediate/ci land later."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from langfuse import observe

from . import recon
from .authz import assert_authorized
from .campaign import run_campaign
from .config import load_target
from .cv import BENIGN_CV
from .langfuse_setup import get_langfuse, tracing_enabled
from .reporting.render import render_to_file
from .schemas import CampaignResult
from .transport.browser import BrowserTransport

app = typer.Typer(help="Tarnish — autonomous AI red-teaming (find -> fix -> verify).")


@app.callback()
def _root() -> None:
    """Keep subcommands named (run/report/remediate/ci land alongside gate0 in later phases)."""


def _tracing_hint() -> None:
    """Say it once, at the end, ruff-style. Never a warning, never repeated."""
    if not tracing_enabled():
        typer.echo("tracing off — set LANGFUSE_PUBLIC_KEY/SECRET_KEY to trace this campaign")


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
    result, json_path = run_campaign(
        target, mode="live" if live else "harness",
        headless=headless, max_tasks=max_tasks or None,
    )

    typer.echo(f"Campaign complete. {len(result.findings)} finding(s). JSON: {json_path}")
    for f in result.findings:
        typer.echo(f"  [{f.severity}] {f.objective} via {f.reproduction.payload.technique} "
                   f"{f.location} ({f.status})")
    if report:
        typer.echo(f"Report: {render_to_file(result, json_path.with_suffix('.html'))}")
    _tracing_hint()


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
