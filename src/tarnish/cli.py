"""Tarnish CLI (Typer). Phase 0 ships the `gate0` command; run/report/remediate/ci land later."""

from __future__ import annotations

import typer
from langfuse import observe

from .authz import assert_authorized
from .config import load_target
from .langfuse_setup import get_langfuse
from .transport.pdf_channel import PDFChannel

app = typer.Typer(help="Tarnish — autonomous AI red-teaming (find -> fix -> verify).")


@app.callback()
def _root() -> None:
    """Keep subcommands named (run/report/remediate/ci land alongside gate0 in later phases)."""

# The benign control CV: a clean, un-injected resume. Every campaign submits this so a
# "success" verdict can be distinguished from run-to-run variance (PLAN.md section 7).
BENIGN_CV = """Jane Doe
Software Engineer

Experience
- 5 years building backend services in Python.
- Led a small team delivering a payments API.

Education
- BSc Computer Science.

Skills: Python, PostgreSQL, Docker, REST APIs.
"""


@observe(name="gate0-benign-request")
def _benign_request(target, content: str) -> str:
    lf = get_langfuse()
    response = PDFChannel().deliver(target, content)  # Phase 0: pdf channel only
    lf.update_current_span(
        input={"target": target.id, "channel": target.channel, "cv_chars": len(content)},
        output={"status": "ok", "response_preview": response[:500]},
        metadata={"phase": "0", "gate": "gate0", "benign": True},
    )
    return response


@app.command()
def gate0(target: str = typer.Option("aurea", help="Target profile id (targets/<id>.yaml).")):
    """Phase 0 gate: send ONE benign request to the target and trace it in Langfuse. No attacks."""
    profile = load_target(target)
    assert_authorized(profile)
    if profile.channel != "pdf":
        raise typer.BadParameter("Phase 0 supports the pdf channel only; chat lands in Phase 2.")

    response = _benign_request(profile, BENIGN_CV)
    get_langfuse().flush()

    typer.echo(f"Benign request delivered to '{profile.id}'. Response preview:")
    typer.echo(response[:1000])


def main() -> None:
    app()


if __name__ == "__main__":
    main()
