"""Each corpus has >=50 retrievable chunks (assignment requirement). No API — just chunking."""

from __future__ import annotations

import re

import pytest

from tarnish.corpora.build import FAMILIES, load_chunks


@pytest.mark.parametrize("family", FAMILIES)
def test_corpus_has_at_least_50_chunks(family):
    chunks = load_chunks(family)
    assert len(chunks) >= 50
    assert all(c.metadata["family"] == family for c in chunks)
    assert all(c.page_content.strip() for c in chunks)


def test_build_replaces_stale_chunks_on_rebuild(tmp_path, monkeypatch):
    """build() used to append to the persistent Chroma collection instead of replacing it, so a
    rebuild after editing patterns.md silently left the old chunks retrievable alongside the new
    ones (chunk count doubled to 106 instead of holding at 53). Guard the fix: building the same
    family twice must not double the stored count."""
    from tarnish.config import get_settings
    import tarnish.corpora.build as cb

    class _StubEmbeddings:
        """No real model: the bug lived in Chroma's append-vs-replace behaviour, not embedding."""

        def embed_documents(self, texts):
            return [[0.0] * 8 for _ in texts]

        def embed_query(self, text):
            return [0.0] * 8

    monkeypatch.setenv("CHROMA_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(cb, "get_embeddings", lambda: _StubEmbeddings())
    try:
        first = len(cb.build("injection").get()["ids"])
        second = len(cb.build("injection").get()["ids"])
        assert first == second == len(cb.load_chunks("injection"))
    finally:
        get_settings.cache_clear()


def test_corpora_have_no_cv_vocabulary():
    """A denylist of the ONE domain the corpora used to be locked to. It proves the CV leak is
    gone; it does not prove domain neutrality — a corpus fully locked to some other domain would
    pass. Named for what it checks. The domain is meant to come from the target profile's
    vocabulary at generation time, never from the corpus."""
    import tarnish.corpora.build as cb

    banned = ("resume", "cv", "candidate", "recruiter", "ats", "hiring", "job applicant",
              "rust expertise", "acting cto", "years of experience")
    for family in cb.FAMILIES:
        text = (cb.CORPORA_DIR / family / "patterns.md").read_text(encoding="utf-8").lower()
        hits = [w for w in banned if re.search(rf"\b{w}\b", text)]
        assert not hits, f"{family}/patterns.md still CV-specific: {hits}"
