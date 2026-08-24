"""PDF crafting. Turns attack content into a CV PDF that the browser transport uploads.
Phase 0 renders a clean control CV. Phase 1 (1a) adds payload embedding + hiding
techniques (white_on_white, tiny_font, off_page, metadata)."""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


class PDFChannel:
    def render(self, content: str) -> bytes:
        """Render plain text into a single-page PDF. No hiding — Phase 0 crafts clean CVs only."""
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=LETTER)
        text = c.beginText(72, 720)
        for line in content.splitlines() or [content]:
            text.textLine(line)
        c.drawText(text)
        c.showPage()
        c.save()
        return buf.getvalue()
