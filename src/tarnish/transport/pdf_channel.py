"""PDF crafting. Turns attack content into a CV PDF that the browser transport uploads.
`render` produces a clean control CV; `craft` embeds a payload into a benign CV using a
hiding technique (white_on_white, tiny_font, off_page, metadata) — visible reviewers don't
see it, but the parser/model does."""

from __future__ import annotations

import io

import pikepdf
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from ..schemas import HidingTechnique


def _draw(c: canvas.Canvas, text: str, x: float, y: float, size: float, rgb) -> None:
    c.setFillColorRGB(*rgb)
    c.setFont("Helvetica", size)
    to = c.beginText(x, y)
    for line in text.splitlines() or [text]:
        to.textLine(line)
    c.drawText(to)


class PDFChannel:
    def render(self, content: str) -> bytes:
        """A clean, un-injected CV (the control). No hiding, no payload."""
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=LETTER)
        _draw(c, content, x=72, y=720, size=11, rgb=(0, 0, 0))
        c.showPage()
        c.save()
        return buf.getvalue()

    def craft(self, visible_cv: str, *, hidden: str, technique: HidingTechnique) -> bytes:
        """A benign-looking CV carrying `hidden` embedded via `technique`."""
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=LETTER)
        _draw(c, visible_cv, x=72, y=720, size=11, rgb=(0, 0, 0))

        if technique == "white_on_white":
            _draw(c, hidden, x=72, y=690, size=11, rgb=(1, 1, 1))  # white text on white page
        elif technique == "tiny_font":
            _draw(c, hidden, x=72, y=36, size=1, rgb=(0, 0, 0))  # ~1px footer
        elif technique == "off_page":
            _draw(c, hidden, x=72, y=-200, size=11, rgb=(0, 0, 0))  # below the visible bounds
        elif technique == "metadata":
            pass  # embedded after rendering, below

        c.showPage()
        c.save()
        pdf = buf.getvalue()

        if technique == "metadata":
            pdf = self._embed_metadata(pdf, hidden)
        return pdf

    def _embed_metadata(self, pdf: bytes, hidden: str) -> bytes:
        with pikepdf.open(io.BytesIO(pdf)) as p:
            p.docinfo["/Keywords"] = hidden
            out = io.BytesIO()
            p.save(out)
            return out.getvalue()
