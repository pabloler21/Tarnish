"""Build and read the attack-pattern corpora (Chroma, one collection per family).

Chunking is one pattern per chunk (each entry in patterns.md is self-contained), which keeps
retrieval clean and the chunk count deterministic (>=50 per family, per the assignment)."""

from __future__ import annotations

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from ..config import get_settings
from ..llm import get_embeddings

CORPORA_DIR = Path(__file__).parent
FAMILIES = ("injection", "leakage", "business_logic")


def load_chunks(family: str) -> list[Document]:
    """One Document per attack pattern (paragraphs starting with '**')."""
    text = (CORPORA_DIR / family / "patterns.md").read_text(encoding="utf-8")
    paras = [p.strip() for p in text.split("\n\n") if p.strip().startswith("**")]
    return [Document(page_content=p, metadata={"family": family}) for p in paras]


def _collection(family: str) -> str:
    return f"tarnish_{family}"


def build(family: str) -> Chroma:
    """Embed a family's patterns into its persistent Chroma collection, replacing any prior
    content (Chroma.from_documents appends, so a rebuild after editing patterns.md would leave
    stale chunks retrievable alongside the new ones)."""
    store = Chroma(
        embedding_function=get_embeddings(),
        persist_directory=get_settings().chroma_dir,
        collection_name=_collection(family),
    )
    store.reset_collection()
    store.add_documents(load_chunks(family))
    return store


def build_all() -> dict[str, int]:
    """Build every corpus; return chunk counts."""
    return {family: len(build(family).get()["ids"]) for family in FAMILIES}


def get_retriever(family: str, k: int = 4):
    store = Chroma(
        persist_directory=get_settings().chroma_dir,
        embedding_function=get_embeddings(),
        collection_name=_collection(family),
    )
    return store.as_retriever(search_kwargs={"k": k})
