"""LLM factory. One place to configure the models Tarnish uses for attack generation,
judging, and remediation, plus the embeddings for the RAG corpora.
Keys/model come from Settings so nothing is hardcoded."""

from __future__ import annotations

from functools import lru_cache

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .agent_cli import AgentCliChatModel
from .backends import ARGV, resolve_backend
from .config import get_settings


def get_chat_model(temperature: float = 0.7) -> BaseChatModel:
    """Attack generation, judging and remediation all come through here. The backend is
    resolved per call so tests and `llm_backend` overrides take effect without a restart."""
    s = get_settings()
    backend = resolve_backend()
    if backend in ARGV:
        return AgentCliChatModel(argv=ARGV[backend], temperature=temperature)
    if backend == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=s.anthropic_model, api_key=s.anthropic_api_key, temperature=temperature
        )
    return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, temperature=temperature)


class LocalEmbeddings(Embeddings):
    """fastembed behind the LangChain Embeddings interface Chroma consumes.

    langchain-community's FastEmbedEmbeddings does exactly this, but that package is sunset
    and pulls SQLAlchemy + langchain-classic for one adapter. `query_embed` (not `embed`) for
    queries so an asymmetric model stays correct if `embedding_model` is ever swapped."""

    def __init__(self, model_name: str) -> None:
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(self._model.query_embed(text)).tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> LocalEmbeddings:
    """Local MiniLM. No API key, no network after the first model download."""
    return LocalEmbeddings(get_settings().embedding_model)
