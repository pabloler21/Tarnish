"""LLM factory (OpenAI via LangChain). One place to configure the models Tarnish uses for
attack generation, judging, and remediation, plus the embeddings for the RAG corpora.
Keys/model come from Settings so nothing is hardcoded."""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .config import get_settings


def get_chat_model(temperature: float = 0.7) -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, temperature=temperature)


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(model=s.embedding_model, api_key=s.openai_api_key)
