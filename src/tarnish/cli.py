"""Tarnish CLI (Typer). Phase 0 ships the `gate0` command; run/report/remediate/ci land later."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from langfuse import observe

from .authz import assert_authorized
from .campaign import run_campaign
from .config import load_target
from .cv import BENIGN_CV
from .langfuse_setup import get_langfuse
from .reporting.render import render_to_file
from .schemas import CampaignResult
from .transport.browser import BrowserTransport

app = typer.Typer(help="Tarnish — autonomous AI red-teaming (find -> fix -> verify).")


@app.callback()
def _root() -> None:
    """Keep subcommands named (run/report/remediate/ci land alongside gate0 in later phases)."""


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


@app.command()
def run(
    target: str = typer.Option("aurea", help="Target profile id (targets/<id>.yaml)."),
    headless: bool = typer.Option(True, help="Run the browser headless."),
    max_tasks: int = typer.Option(0, help="Cap the number of attack tasks (0 = all)."),
    report: bool = typer.Option(True, help="Also render the HTML report next to the JSON."),
):
    """Run a full campaign: control + attacks -> evaluate -> remediate -> JSON + HTML report."""
    result, json_path = run_campaign(target, headless=headless, max_tasks=max_tasks or None)

    typer.echo(f"Campaign complete. {len(result.findings)} finding(s). JSON: {json_path}")
    for f in result.findings:
        typer.echo(f"  [{f.severity}] {f.objective} via {f.reproduction.payload.technique} ({f.status})")
    if report:
        html_path = render_to_file(result, json_path.with_suffix(".html"))
        typer.echo(f"Report: {html_path}")


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
