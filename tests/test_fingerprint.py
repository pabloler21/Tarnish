"""The fingerprint contract: a stable identity for "the same vulnerability" across runs.
Hash of (objective, technique, attacked-surface element) — deliberately independent of the
payload text, so regression detection and the CI gate work even when the payload varies."""

from __future__ import annotations

from tarnish.fingerprint import fingerprint


def test_same_inputs_produce_same_fingerprint():
    a = fingerprint("data", "white_on_white", "cv_pdf")
    b = fingerprint("data", "white_on_white", "cv_pdf")
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_fingerprint_is_case_and_whitespace_insensitive():
    # Normalization keeps "the same vulnerability" identical across cosmetic variation.
    assert fingerprint("Data", "  White_On_White ", "CV_PDF") == fingerprint(
        "data", "white_on_white", "cv_pdf"
    )


def test_different_technique_changes_fingerprint():
    assert fingerprint("data", "white_on_white", "cv_pdf") != fingerprint(
        "data", "tiny_font", "cv_pdf"
    )


def test_different_objective_changes_fingerprint():
    assert fingerprint("data", "white_on_white", "cv_pdf") != fingerprint(
        "instruction", "white_on_white", "cv_pdf"
    )


def test_different_surface_element_changes_fingerprint():
    assert fingerprint("data", "white_on_white", "cv_pdf") != fingerprint(
        "data", "white_on_white", "chat_message"
    )


def test_surface_element_is_file_and_symbol_never_the_line():
    from tarnish.fingerprint import fingerprint, surface_element

    before = surface_element("src/bot.ts", "handleMessage")
    after = surface_element("src/bot.ts", "handleMessage")  # same symbol, moved 40 lines down
    assert before == after == "src/bot.ts#handleMessage"
    assert "31" not in before

    same = fingerprint("data", "injection", before)
    moved = fingerprint("data", "injection", after)
    other = fingerprint("data", "injection", surface_element("src/bot.ts", "ingestTicket"))
    assert same == moved, "a refactor that moves lines must not invent a new finding"
    assert same != other, "two injection points in one file must not collapse to one identity"
