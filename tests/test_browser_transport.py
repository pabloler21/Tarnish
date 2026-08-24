"""Browser transport: surface detection + delivery. Uses a real headless Chromium
against local HTML (set_content / a local file) — no external network."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from tarnish.schemas import TargetProfile
from tarnish.transport.browser import BrowserTransport, SurfaceUnknownError
from tarnish.transport.surface import Surface, SurfaceDetector

FIXTURES = Path(__file__).parent / "fixtures"


@contextmanager
def browser_page(html: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        try:
            yield page
        finally:
            browser.close()


def test_detects_pdf_upload_from_file_input():
    with browser_page('<div>Drop your CV here</div><input type="file" id="cv">') as page:
        surface = SurfaceDetector().detect(page)
    assert surface.kind == "pdf_upload"
    assert surface.input_selector == 'input[type="file"]'


def test_returns_unknown_when_no_recognizable_surface():
    with browser_page("<p>just some text, nothing to attack here</p>") as page:
        surface = SurfaceDetector().detect(page)
    assert surface.kind == "unknown"


def test_browser_transport_uploads_pdf_and_reads_response():
    """End-to-end: load page -> detect dropzone -> craft+upload PDF -> read the verdict."""
    target = TargetProfile(
        id="fix", name="fix", url=(FIXTURES / "dropzone.html").as_uri(),
        owner_verified=True, target_model_family="openai",
    )
    response = BrowserTransport().deliver(target, "Jane Doe\nSoftware Engineer")
    assert "SCORE 42/100" in response  # the target's rendered response was read
    assert "cv.pdf" in response  # the crafted PDF actually rode the upload


def test_browser_transport_raises_on_unknown_surface(tmp_path):
    blank = tmp_path / "blank.html"
    blank.write_text("<p>nothing to attack</p>", encoding="utf-8")
    target = TargetProfile(
        id="b", name="b", url=blank.as_uri(),
        owner_verified=True, target_model_family="openai",
    )
    with pytest.raises(SurfaceUnknownError):
        BrowserTransport().deliver(target, "x")
