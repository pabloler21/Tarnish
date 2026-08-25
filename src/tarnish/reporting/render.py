"""Render a CampaignResult to the four-part HTML report."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas import CampaignResult

_TEMPLATES = Path(__file__).parent / "templates"


def render_html(result: CampaignResult) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    return env.get_template("report.html.j2").render(r=result)


def render_to_file(result: CampaignResult, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.write_text(render_html(result), encoding="utf-8")
    return path
