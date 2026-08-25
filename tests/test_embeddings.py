"""Embeddings run locally. If they needed an API key, `runs on your own subscription`
would be false — see spec section 7.1."""

from __future__ import annotations

from tarnish.llm import get_embeddings

EXPECTED_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2, per fastembed's own model list


def test_embeddings_are_local_and_keyless(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_embeddings.cache_clear()

    vector = get_embeddings().embed_query("hidden instruction in a resume")

    assert len(vector) == EXPECTED_DIM
    assert all(isinstance(x, float) for x in vector)


def test_embeddings_are_deterministic():
    get_embeddings.cache_clear()
    embedder = get_embeddings()
    assert embedder.embed_query("same text") == embedder.embed_query("same text")
