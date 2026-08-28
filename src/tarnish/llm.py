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
from .backends import ARGV, resolve_backend, resolve_attacker_backend
from .config import get_settings

# Which CLI backends can carry a real system prompt. Without one, the persona and the payload
# arrive at the same privilege level and there is no hierarchy for an injection to violate —
# so the harness biases toward false positives rather than failing safe.
_SYSTEM_FLAG = {"claude_cli": "--system-prompt"}


def harness_has_privilege_gap() -> bool:
    """False when the resolved backend cannot separate system from user. The API backends can
    (a native `system` message); claude can (`--system-prompt`); codex cannot."""
    backend = resolve_backend()
    return backend not in ARGV or backend in _SYSTEM_FLAG


def get_target_model() -> BaseChatModel:
    """The model that PLAYS the target in harness mode. Same resolved backend as every other
    role — no second subscription — but its own model id, picked for resemblance to production
    rather than for capability. temperature=0: the target is being measured, not created."""
    s = get_settings()
    backend = resolve_backend()
    if backend in ARGV:
        argv = list(ARGV[backend])
        if backend == "claude_cli":
            argv += ["--model", s.target_model, "--exclude-dynamic-system-prompt-sections"]
        return AgentCliChatModel(
            argv=argv, system_flag=_SYSTEM_FLAG.get(backend), temperature=0
        )
    if backend == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=s.anthropic_model, api_key=s.anthropic_api_key, temperature=0)
    return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, temperature=0)


def attacker_can_generate() -> bool:
    """False when the attacker role resolves to the claude CLI, which refuses attack generation.
    The findings are then empty rather than over-reported — the opposite failure from the harness
    privilege gap, and the caller says so."""
    return resolve_attacker_backend() != "claude_cli"


def get_attacker_model() -> BaseChatModel:
    """The model that GENERATES payloads. Same shape as get_chat_model, but on the attacker
    backend (claude last, because it refuses). temperature stays at the specialist's default —
    generation wants variety."""
    s = get_settings()
    backend = resolve_attacker_backend()
    if backend in ARGV:
        argv = list(ARGV[backend])
        if backend == "claude_cli":
            argv += ["--model", s.claude_model]
        return AgentCliChatModel(argv=argv)
    if backend == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=s.anthropic_model, api_key=s.anthropic_api_key, temperature=0.7)
    return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, temperature=0.7)


def text_of(response) -> str:
    """Extract plain text from a chat model response. `.content` is a plain string for most
    backends, but some (the API-key fallback backends) return a list of content blocks
    (`[{"type": "text", "text": "..."}]`); `str()` on that list would leak Python repr noise
    into evidence the report shows verbatim, so join the text blocks instead."""
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if parts:
            return "".join(parts)
    return str(content)


def get_chat_model(temperature: float = 0.7) -> BaseChatModel:
    """Attack generation, judging and remediation all come through here. The backend is
    resolved per call so tests and `llm_backend` overrides take effect without a restart."""
    s = get_settings()
    backend = resolve_backend()
    if backend in ARGV:
        argv = list(ARGV[backend])
        if backend == "claude_cli":
            # Pin the model: Claude Code's default (Opus 5) refuses red-team payload
            # generation via its AUP safeguards ([cyber]); Opus 4.8 does not. VOLATILE id,
            # so it lives in Settings — swap to `haiku` for a cheaper/faster run.
            argv += ["--model", s.claude_model]
        return AgentCliChatModel(argv=argv, temperature=temperature)
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
