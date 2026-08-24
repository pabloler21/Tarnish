"""PDF transport channel. Phase 0: render a clean CV and POST it (the benign control request).
Phase 1 (1a) extends this same class with payload embedding + hiding techniques
(white_on_white, tiny_font, off_page, metadata)."""

from __future__ import annotations

import io

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from ..schemas import TargetProfile


class PDFChannel:
    channel = "pdf"

    def render(self, content: str) -> bytes:
        """Render plain text into a single-page PDF. No hiding — Phase 0 sends clean CVs only."""
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=LETTER)
        text = c.beginText(72, 720)
        for line in content.splitlines() or [content]:
            text.textLine(line)
        c.drawText(text)
        c.showPage()
        c.save()
        return buf.getvalue()

    def deliver(
        self, target: TargetProfile, content: str, *, hiding: str | None = None
    ) -> str:
        if hiding is not None:
            raise NotImplementedError("PDF hiding techniques land in Phase 1 (1a).")
        pdf = self.render(content)
        files = {target.upload_field: (target.upload_filename, pdf, "application/pdf")}
        resp = httpx.post(
            target.endpoint, files=files, headers=target.headers, timeout=60.0
        )
        resp.raise_for_status()
        return resp.text
