"""Browser transport: surface detection + delivery. Uses a real headless Chromium
against local HTML (set_content / a local file) — no external network."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from tarnish.schemas import TargetProfile
from tarnish.transport.browser import BrowserTransport, ResponseReader, SurfaceUnknownError
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


def test_detects_pdf_upload_rendered_late_by_spa():
    """SPAs (like Aurea) inject the file input after hydration — detection must wait for it."""
    html = """<div>loading...</div><script>
      setTimeout(() => {
        const i = document.createElement('input');
        i.type = 'file';
        document.body.appendChild(i);
      }, 800);
    </script>"""
    with browser_page(html) as page:
        surface = SurfaceDetector().detect(page)
    assert surface.kind == "pdf_upload"


def test_returns_unknown_when_no_recognizable_surface():
    with browser_page("<p>just some text, nothing to attack here</p>") as page:
        surface = SurfaceDetector().detect(page, timeout_ms=500)
    assert surface.kind == "unknown"


def test_browser_transport_uploads_pdf_and_reads_response():
    """End-to-end: load page -> detect dropzone -> craft+upload PDF -> read the verdict."""
    target = TargetProfile(
        id="fix", name="fix", url=(FIXTURES / "dropzone.html").as_uri(),
        owner_verified=True, target_model_family="openai",
    )
    response = BrowserTransport().deliver(target, visible="Jane Doe\nSoftware Engineer")
    assert "SCORE 42/100" in response  # the target's rendered response was read
    assert "cv.pdf" in response  # the crafted PDF actually rode the upload


def test_response_reader_waits_for_backend_not_loading_state():
    """The target shows a static 'analyzing...' message while its backend works, then renders
    the result. The reader must wait for the network call to finish, not grab the loading text."""
    import threading
    import time as _time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from playwright.sync_api import sync_playwright

    page_html = """<button id='go'>go</button><div id='out'>0 Score</div><script>
      document.getElementById('go').addEventListener('click', async () => {
        const o = document.getElementById('out');
        o.innerText = 'Analyzing your resume, this may take a few seconds...';
        await fetch('/eval');
        o.innerText = 'DONE: SCORE 88/100';
      });
    </script>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/eval":
                _time.sleep(1.0)  # backend "evaluation" work
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page_html.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            result = ResponseReader().read_after(
                page, lambda: page.click("#go"), timeout_ms=10000, settle_ms=800
            )
            browser.close()
    finally:
        server.shutdown()

    assert "DONE: SCORE 88/100" in result
    assert "Analyzing" not in result  # did NOT return the loading state


def test_browser_transport_raises_on_unknown_surface(tmp_path):
    blank = tmp_path / "blank.html"
    blank.write_text("<p>nothing to attack</p>", encoding="utf-8")
    target = TargetProfile(
        id="b", name="b", url=blank.as_uri(),
        owner_verified=True, target_model_family="openai",
    )
    with pytest.raises(SurfaceUnknownError):
        BrowserTransport(detect_timeout_ms=500).deliver(target, visible="x")
