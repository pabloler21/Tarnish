"""Browser transport: the universal web-delivery mechanism. Drives a headless
Chromium to attack a target through its real input surface (a PDF dropzone, a chat
box) the way a person would — so any web page works with no per-target API wiring.

Phase 0 implements the pdf_upload surface (enough to close Gate 0 against Aurea).
text_chat delivery + PDF hiding techniques land in Phase 1."""

from __future__ import annotations

import re
import time

from ..schemas import TargetProfile
from .pdf_channel import PDFChannel
from .surface import SurfaceDetector

_SUBMIT_KEYWORDS = re.compile(r"analyz|analiz|evaluat|submit|upload|send|start", re.I)
# "still working" markers — never return the loading state as if it were the response.
_PROGRESS = re.compile(
    r"analy[sz]ing|reading your|please wait|\bloading\b|thinking|processing|"
    r"evaluating|may take|working on it|generating|one moment",
    re.I,
)


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
    Deliberately isolated — this is the fragile part and will be refined per target.

    The target renders a result only after its backend finishes, showing a static
    'analyzing...' message meanwhile. `wait_for_load_state('networkidle')` is one-shot per
    navigation and returns instantly for a later XHR, so instead we track the requests the
    submit itself triggers and wait until: the DOM is stable, no tracked request is in
    flight, and the text no longer looks like a loading state."""

    def read_after(self, page, trigger, *, timeout_ms: int = 90000, settle_ms: int = 1200) -> str:
        pending: set = set()
        page.on("request", lambda r: pending.add(r))
        page.on("requestfinished", lambda r: pending.discard(r))
        page.on("requestfailed", lambda r: pending.discard(r))

        trigger()  # perform the submit; the resulting requests are now tracked

        deadline = time.monotonic() + timeout_ms / 1000
        last = page.inner_text("body")
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            page.wait_for_timeout(250)
            current = page.inner_text("body")
            if current != last:
                last = current
                stable_since = time.monotonic()
                continue
            stable = (time.monotonic() - stable_since) * 1000 >= settle_ms
            if stable and not pending and not _PROGRESS.search(current):
                break
        return last


class PdfUploadSurface:
    """Deliver a crafted PDF by uploading it through a file input and reading the result."""

    def deliver(self, page, surface, pdf_bytes: bytes) -> str:
        def trigger():
            page.set_input_files(
                surface.input_selector,
                files=[{"name": "cv.pdf", "mimeType": "application/pdf", "buffer": pdf_bytes}],
            )
            self._click_submit(page)

        return ResponseReader().read_after(page, trigger)

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

    def __init__(self, *, headless: bool = True, detect_timeout_ms: int = 15000):
        self.headless = headless
        self.detect_timeout_ms = detect_timeout_ms

    def deliver(self, target: TargetProfile, content: str, *, hiding: str | None = None) -> str:
        with WebTarget(target.url, headless=self.headless) as page:
            surface = SurfaceDetector().detect(page, timeout_ms=self.detect_timeout_ms)
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
