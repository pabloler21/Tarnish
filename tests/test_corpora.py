"""Each corpus has >=50 retrievable chunks (assignment requirement). No API — just chunking."""

from __future__ import annotations

import pytest

from tarnish.corpora.build import FAMILIES, load_chunks


@pytest.mark.parametrize("family", FAMILIES)
def test_corpus_has_at_least_50_chunks(family):
    chunks = load_chunks(family)
    assert len(chunks) >= 50
    assert all(c.metadata["family"] == family for c in chunks)
    assert all(c.page_content.strip() for c in chunks)
