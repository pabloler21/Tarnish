"""Strip the invisible/bidi/control characters an attacker uses to smuggle hidden text past a
human reviewer (white-on-white payloads survive as normal characters, but zero-width and
control smuggling does not)."""

from __future__ import annotations

import re
import unicodedata

# zero-width, bidi/format overrides, word joiner, BOM.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠﻿]")


def sanitize(text: str) -> str:
    without_invisible = _INVISIBLE.sub("", text)
    return "".join(
        c for c in without_invisible
        if unicodedata.category(c)[0] != "C" or c in "\n\t"
    )
