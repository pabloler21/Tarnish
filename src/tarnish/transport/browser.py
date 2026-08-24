"""Browser transport: the universal web-delivery mechanism. Drives a headless
Chromium to attack a target through its real input surface (a PDF dropzone, a chat
box) the way a person would — so any web page works with no per-target API wiring.

Phase 0 implements the pdf_upload surface (enough to close Gate 0 against Aurea).
text_chat delivery + PDF hiding techniques land in Phase 1."""

from __future__ import annotations

import re

from ..schemas import TargetProfile
from .pdf_channel import PDFChannel
from .surface import SurfaceDetector

_SUBMIT_KEYWORDS = re.compile(r"analyz|analiz|evaluat|submit|upload|send|start", re.I)


class SurfaceUnknownError(RuntimeError):
    """No recognizable attack surface on the page — routes to the orchestrator's
    needs_clarification path so the operator can declare a selector override."""


class WebTarget:
    """A headless browser session for one target page (context manager)."""

    def __init__(self, url: str, *, headless: bool = True):
        self.url = url
        self.headless = headless

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self.page = self._browser.new_page()
        self.page.goto(self.url, wait_until="domcontentloaded")
        return self.page

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()


class ResponseReader:
    """Capture the target's rendered response after a payload is delivered.
    Deliberately isolated — this is the fragile part and will be refined per target."""

    def read(self, page, before_text: str, timeout_ms: int = 20000) -> str:
        page.wait_for_function(
            "prev => document.body.innerText !== prev",
            arg=before_text,
            timeout=timeout_ms,
        )
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass  # some UIs render locally with no network settle
        return page.inner_text("body")


class PdfUploadSurface:
    """Deliver a crafted PDF by uploading it through a file input and reading the result."""

    def deliver(self, page, surface, pdf_bytes: bytes) -> str:
        before = page.inner_text("body")
        page.set_input_files(
            surface.input_selector,
            files=[{"name": "cv.pdf", "mimeType": "application/pdf", "buffer": pdf_bytes}],
        )
        self._click_submit(page)
        return ResponseReader().read(page, before)

    def _click_submit(self, page) -> None:
        """Best-effort: click an analyze/submit control if present (some dropzones auto-submit)."""
        for getter in (
            lambda: page.get_by_role("button", name=_SUBMIT_KEYWORDS),
            lambda: page.get_by_role("link", name=_SUBMIT_KEYWORDS),
            lambda: page.get_by_text(_SUBMIT_KEYWORDS),
        ):
            try:
                loc = getter()
                if loc.count() > 0:
                    loc.first.click(timeout=3000)
                    return
            except Exception:
                pass


class BrowserTransport:
    """The Transport implementation the campaign uses. Loads the page, detects the
    surface, and delivers `content` through the matching interaction."""

    channel = "web"

    def __init__(self, *, headless: bool = True):
        self.headless = headless

    def deliver(self, target: TargetProfile, content: str, *, hiding: str | None = None) -> str:
        with WebTarget(target.url, headless=self.headless) as page:
            surface = SurfaceDetector().detect(page)
            if surface.kind == "pdf_upload":
                if hiding is not None:
                    raise NotImplementedError("PDF hiding techniques land in Phase 1.")
                pdf = PDFChannel().render(content)  # Phase 0: clean control CV
                return PdfUploadSurface().deliver(page, surface, pdf)
            if surface.kind == "text_chat":
                raise NotImplementedError("text_chat delivery lands in Phase 1.")
            raise SurfaceUnknownError(
                f"No recognizable attack surface at {target.url}. "
                "Declare `surface` + a selector override in the target profile."
            )
