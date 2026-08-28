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


def test_corpora_are_domain_neutral():
    """The corpus must describe attack TECHNIQUES, not CV-evaluation instances, so a payload for a
    support bot (or any target) isn't dragged toward resumes. The domain comes from the target
    profile's vocabulary at generation time, never from the corpus."""
    import tarnish.corpora.build as cb

    banned = ("resume", "cv", "candidate", "recruiter", "ats", "hiring", "job applicant",
              "rust expertise", "acting cto", "years of experience")
    for family in cb.FAMILIES:
        text = (cb.CORPORA_DIR / family / "patterns.md").read_text(encoding="utf-8").lower()
        hits = [w for w in banned if re.search(rf"\b{w}\b", text)]
        assert not hits, f"{family}/patterns.md still CV-specific: {hits}"
