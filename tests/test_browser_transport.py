"""Browser transport: surface detection + delivery. Uses a real headless Chromium
against local HTML (set_content / a local file) — no external network."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from tarnish.transport.surface import Surface, SurfaceDetector


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
