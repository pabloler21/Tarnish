# M1 — Keyless Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tarnish's existing campaign runs end-to-end with **zero API keys**, using the coding-agent CLI the developer already has logged in, and with Langfuse off by default.

**Architecture:** Three seams, no structural change. (1) `llm.py`'s `get_chat_model()` dispatches to a `BaseChatModel` subclass that shells out to `claude -p` / `codex exec` instead of `ChatOpenAI`. (2) `get_embeddings()` swaps `OpenAIEmbeddings` for local `FastEmbedEmbeddings`. (3) `get_langfuse()` returns a no-op when keys are absent. Every caller (`agents/base.py`, `evaluator.py`, `corpora/build.py`, `campaign.py`, `cli.py`) is untouched except where noted.

**Tech Stack:** Python 3.12+, `uv`, LangChain (`langchain-core`, `langchain-community`), `fastembed`, `langchain-chroma`, Langfuse v4, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-tarnish-oss-cli-plugin-design.md` (§3.2 backend resolution, §7.1 embeddings, §9 non-negotiables)

## Global Constraints

- **`uv` exclusively.** No `pip`, `poetry`, `conda`. Add deps with `uv add <pkg>`; run anything with `uv run`.
- **Python 3.12+.**
- **TDD.** Every task writes the failing test first, watches it fail, then implements.
- **One commit per task**, ending with the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Branch:** `phase-2-m1-keyless-engine`, cut from `phase-2-oss-cli-plugin`. Never commit to `main`.
- **Closed enums over free strings** where a value is one of a fixed set.
- **Backend names are a closed set:** `"claude_cli" | "codex_cli" | "openai" | "anthropic"`. Use these exact strings everywhere.
- **Do not rename `run` to `explore` in this milestone.** The command surface is designed in M2 alongside `init`/`check`; renaming now creates churn for no gate. The spec's Gate M1 wording ("`explore` against Aurea") means the existing `tarnish run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/tarnish/backends.py` | **new.** Pure resolution: which backend is available, in what order, and the error when none is. No I/O beyond `shutil.which`. |
| `src/tarnish/agent_cli.py` | **new.** `AgentCliChatModel`, a `BaseChatModel` that shells out to an agent CLI. Owns the subprocess contract and prompt-based structured output. |
| `src/tarnish/llm.py` | modify. Factory only — dispatches on the resolved backend, builds embeddings. Stays under 40 lines. |
| `src/tarnish/langfuse_setup.py` | modify. Adds `tracing_enabled()` and the no-op client. |
| `src/tarnish/config.py` | modify. `embedding_model` default, `llm_backend` override. |
| `src/tarnish/cli.py` | modify. One-line tracing hint at the end of a run. |
| `tests/test_backends.py` | **new.** Resolution order and the no-backend error. |
| `tests/test_agent_cli.py` | **new.** Subprocess contract, structured output, retry. |
| `tests/test_embeddings.py` | **new.** Local embeddings, correct dimension, no API key needed. |
| `tests/test_langfuse_optional.py` | **new.** No-op without keys; real client with them. |

---

## Task 1: Langfuse becomes optional

**Files:**
- Modify: `src/tarnish/langfuse_setup.py`
- Modify: `src/tarnish/cli.py:53-55` (the `gate0` echo block) and `src/tarnish/cli.py:68` (the `run` echo block)
- Test: `tests/test_langfuse_optional.py`

**Interfaces:**
- Consumes: `get_settings()` from `config.py`.
- Produces: `tracing_enabled() -> bool`; `get_langfuse()` returns either a real Langfuse client or a no-op with the same attribute access; `get_callback_handler() -> CallbackHandler | None`.

> Context: `get_callback_handler()` has no callers today (`campaign.py` invokes the graph without callbacks). Keep it — M2 wires graph tracing — but make it `None`-safe now so M2 doesn't have to.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_langfuse_optional.py
"""Langfuse is opt-in: a trace holds the system prompt, working payloads and unfixed
vulnerabilities, so it must never leave the machine unless the operator asks."""

from __future__ import annotations

import tarnish.langfuse_setup as ls


def _clear_caches():
    ls.get_langfuse.cache_clear()
    from tarnish.config import get_settings
    get_settings.cache_clear()


def test_tracing_disabled_without_keys(monkeypatch):
    for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ls, "_settings_keys", lambda: ("", ""))
    _clear_caches()

    assert ls.tracing_enabled() is False
    client = ls.get_langfuse()
    # A no-op must absorb every call the codebase makes, without raising.
    client.update_current_span(input={"a": 1}, output={"b": 2}, metadata={})
    client.flush()
    assert ls.get_callback_handler() is None


def test_tracing_enabled_with_keys(monkeypatch):
    monkeypatch.setattr(ls, "_settings_keys", lambda: ("pk-lf-test", "sk-lf-test"))
    _clear_caches()

    assert ls.tracing_enabled() is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_langfuse_optional.py -v`
Expected: FAIL — `AttributeError: module 'tarnish.langfuse_setup' has no attribute 'tracing_enabled'`

- [ ] **Step 3: Implement**

Replace the body of `src/tarnish/langfuse_setup.py` below the imports with:

```python
def _settings_keys() -> tuple[str, str]:
    """Seam so tests can force the keyless path without touching real env."""
    s = get_settings()
    return s.langfuse_public_key, s.langfuse_secret_key


def tracing_enabled() -> bool:
    public, secret = _settings_keys()
    return bool(public and secret)


class _NoopClient:
    """Absorbs every Langfuse call. Tracing off is the default, so this is the common path."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _configure_env() -> None:
    """Push settings into os.environ (the SDK reads env, not our Settings object).
    setdefault so real shell env vars always win over .env-derived values."""
    s = get_settings()
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", s.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", s.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", s.langfuse_host)
    os.environ.setdefault("LANGFUSE_BASE_URL", s.langfuse_host)  # both names seen across SDK versions
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", s.langfuse_tracing_environment)


@lru_cache(maxsize=1)
def get_langfuse():
    if not tracing_enabled():
        return _NoopClient()
    _configure_env()
    return get_client()


def get_callback_handler() -> CallbackHandler | None:
    """The LangChain/LangGraph callback handler. None when tracing is off."""
    if not tracing_enabled():
        return None
    get_langfuse()  # ensure env is configured before the handler is built
    return CallbackHandler()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_langfuse_optional.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Add the one-line hint to the CLI**

In `src/tarnish/cli.py`, import `tracing_enabled` alongside `get_langfuse`:

```python
from .langfuse_setup import get_langfuse, tracing_enabled
```

Add this helper after the `_root` callback:

```python
def _tracing_hint() -> None:
    """Say it once, at the end, ruff-style. Never a warning, never repeated."""
    if not tracing_enabled():
        typer.echo("tracing off — set LANGFUSE_PUBLIC_KEY/SECRET_KEY to trace this campaign")
```

Call `_tracing_hint()` as the last line of both `gate0()` and `run()`.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all previously-green tests still pass, plus the 2 new ones.

- [ ] **Step 7: Commit**

```bash
git add src/tarnish/langfuse_setup.py src/tarnish/cli.py tests/test_langfuse_optional.py
git commit -m "M1: Langfuse is opt-in — no-op client without keys

A trace contains the system prompt, the payloads that worked and the
unfixed vulnerabilities. It must not leave the machine unless asked.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Local embeddings (fastembed)

**Files:**
- Modify: `src/tarnish/llm.py:9,19-22`
- Modify: `src/tarnish/config.py:33`
- Modify: `pyproject.toml` (dependencies)
- Test: `tests/test_embeddings.py`

**Interfaces:**
- Produces: `get_embeddings()` returns a `langchain_core.embeddings.Embeddings` that runs locally. `Settings.embedding_model` holds a fastembed model id (a string like `"sentence-transformers/all-MiniLM-L6-v2"`), no longer an OpenAI model id.

> Why: `llm.py:20` uses `OpenAIEmbeddings` with an API key. CLAUDE.md always specified fastembed (local, zero cost). If RAG needs an OpenAI key, the whole "runs on your subscription" promise collapses. This is spec §7.1.

- [ ] **Step 1: Add the dependencies**

```bash
uv add langchain-community fastembed
```

- [ ] **Step 2: Find the exact MiniLM model id — do not guess it**

Run:

```bash
uv run python -c "from fastembed import TextEmbedding; [print(m['model'], m['dim']) for m in TextEmbedding.list_supported_models()]"
```

Record the entry whose name contains `MiniLM` and its `dim`. Use that exact string as `MODEL_ID` and that number as `EXPECTED_DIM` in the next two steps. If no MiniLM entry exists, pick the smallest English model listed and use its values instead — the test asserts consistency, not a specific model.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_embeddings.py
"""Embeddings run locally. If they needed an API key, `runs on your own subscription`
would be false — see spec section 7.1."""

from __future__ import annotations

from tarnish.llm import get_embeddings

EXPECTED_DIM = 384  # replace with the dim recorded in Step 2


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
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: FAIL — either an OpenAI auth error or a dimension mismatch (1536 != 384).

- [ ] **Step 5: Implement**

In `src/tarnish/config.py:33`, change the default:

```python
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # fastembed id from Step 2
```

In `src/tarnish/llm.py`, replace the import on line 9 and the `get_embeddings` body:

```python
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_openai import ChatOpenAI


@lru_cache(maxsize=1)
def get_embeddings() -> FastEmbedEmbeddings:
    """Local MiniLM. No API key, no network after the first model download."""
    return FastEmbedEmbeddings(model_name=get_settings().embedding_model)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: PASS (the first run downloads the model — allow a minute).

- [ ] **Step 7: Rebuild the Chroma index — mandatory, non-obvious**

The vector dimension changed (1536 → 384), so the existing collection is invalid and queries against it will fail or return garbage.

```bash
rm -rf .tarnish/chroma
uv run python -c "from tarnish.corpora.build import build_all; print(build_all())"
```

Expected: a dict with three families, **each count ≥ 50**. Record the three numbers; they must match the 53/51/51 recorded in CLAUDE.md. If any count differs, stop — the chunker changed behaviour and that is a separate bug.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all green, including `tests/test_corpora.py` and `tests/test_specialists.py`.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/tarnish/llm.py src/tarnish/config.py tests/test_embeddings.py
git commit -m "M1: local embeddings via fastembed

OpenAIEmbeddings required an API key for RAG retrieval, which broke the
keyless promise. CLAUDE.md always specified fastembed. Chroma rebuilt:
the vector dimension changed, so the old collection was invalid.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Backend resolution

**Files:**
- Create: `src/tarnish/backends.py`
- Modify: `src/tarnish/config.py` (add `llm_backend`)
- Test: `tests/test_backends.py`

**Interfaces:**
- Produces:
  - `Backend = Literal["claude_cli", "codex_cli", "openai", "anthropic"]`
  - `ARGV: dict[str, list[str]]` — the CLI invocation prefix, keyed by the CLI backend names only (`"claude_cli"`, `"codex_cli"`); the API-key backends are absent, and `get_chat_model` uses `backend in ARGV` as the "is this a CLI backend" test
  - `resolve_backend() -> Backend` — raises `NoBackendAvailable` when nothing is usable
  - `class NoBackendAvailable(RuntimeError)`

> Why: spec §3.2. Order matters — the subscription CLIs come first because they cost the user nothing beyond a plan they already pay for. The error must name all three routes; "authentication failed" is the failure mode that kills first-run adoption (spec §10).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backends.py
"""Backend resolution order and, above all, the error when nothing is available:
a first-run user with no agent CLI and no key must be told exactly what to do."""

from __future__ import annotations

import pytest

from tarnish import backends


def _only(monkeypatch, *available: str):
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}" if name in available else None)


def _no_keys(monkeypatch):
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "", "anthropic": ""})


def test_claude_cli_wins_when_present(monkeypatch):
    _only(monkeypatch, "claude", "codex")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "claude_cli"


def test_codex_cli_is_second(monkeypatch):
    _only(monkeypatch, "codex")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "codex_cli"


def test_api_key_is_the_fallback(monkeypatch):
    _only(monkeypatch)
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "openai"


def test_explicit_override_wins(monkeypatch):
    _only(monkeypatch, "claude")
    monkeypatch.setattr(backends, "_forced_backend", lambda: "openai")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert backends.resolve_backend() == "openai"


def test_error_names_all_three_routes(monkeypatch):
    _only(monkeypatch)
    _no_keys(monkeypatch)
    with pytest.raises(backends.NoBackendAvailable) as excinfo:
        backends.resolve_backend()
    message = str(excinfo.value)
    for route in ("claude", "codex", "OPENAI_API_KEY"):
        assert route in message
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_backends.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tarnish.backends'`

- [ ] **Step 3: Implement**

```python
# src/tarnish/backends.py
"""Which LLM backend to use, resolved once per process.

Order is deliberate: the agent CLIs come first because they draw on a subscription the
developer already pays for, so a keyless first run works. API keys are the CI path."""

from __future__ import annotations

import shutil
from typing import Literal

from .config import get_settings

Backend = Literal["claude_cli", "codex_cli", "openai", "anthropic"]

# How to invoke each CLI backend. The prompt is appended by agent_cli.py.
ARGV: dict[str, list[str]] = {
    "claude_cli": ["claude", "-p"],
    "codex_cli": ["codex", "exec"],
}

_CLI_EXECUTABLE: dict[str, str] = {"claude_cli": "claude", "codex_cli": "codex"}


class NoBackendAvailable(RuntimeError):
    """No agent CLI on PATH and no API key. The message must be actionable."""


def _api_keys() -> dict[str, str]:
    s = get_settings()
    return {"openai": s.openai_api_key, "anthropic": s.anthropic_api_key}


def _forced_backend() -> str:
    return get_settings().llm_backend


def resolve_backend() -> Backend:
    forced = _forced_backend()
    if forced:
        return forced  # type: ignore[return-value]

    for backend, executable in _CLI_EXECUTABLE.items():
        if shutil.which(executable):
            return backend  # type: ignore[return-value]

    keys = _api_keys()
    for backend in ("openai", "anthropic"):
        if keys.get(backend):
            return backend  # type: ignore[return-value]

    raise NoBackendAvailable(
        "Tarnish needs a model. Pick one:\n"
        "  1. Claude Code   — install it and run `claude login` (uses your plan)\n"
        "  2. Codex         — install it and sign in (uses your ChatGPT plan)\n"
        "  3. An API key    — set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env\n"
        "Then run this command again."
    )
```

In `src/tarnish/config.py`, add two fields next to `openai_api_key`:

```python
    anthropic_api_key: str = ""
    # "" = auto-detect (see backends.resolve_backend). Set to force one:
    # claude_cli | codex_cli | openai | anthropic
    llm_backend: str = ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_backends.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add src/tarnish/backends.py src/tarnish/config.py tests/test_backends.py
git commit -m "M1: backend resolution — agent CLI first, API key as fallback

The no-backend error names all three routes. 'authentication failed' is
the message that kills a first run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: `AgentCliChatModel`

**Files:**
- Create: `src/tarnish/agent_cli.py`
- Test: `tests/test_agent_cli.py`

**Interfaces:**
- Consumes: `ARGV` from `backends.py`.
- Produces: `AgentCliChatModel(argv: list[str], timeout: int = 180)`, a `langchain_core.language_models.chat_models.BaseChatModel` with `_generate`, `_llm_type`, and a prompt-based `with_structured_output(schema)`.

> Why prompt-based structured output: `evaluator.py:59` calls `get_chat_model(temperature=0).with_structured_output(_Judgment)`. The base-class implementation depends on native tool-calling, which a subprocess has no access to. Implementing it here keeps `evaluator.py` untouched — that is the point of the seam.

- [ ] **Step 1: Probe the real CLI contract before writing code against it**

Do not assume how the prompt is passed. Run both and record which works:

```bash
claude -p "Reply with exactly: PONG"
echo "Reply with exactly: PONG" | claude -p
```

Record: (a) which form returns the text, (b) whether output goes to stdout, (c) the exit code, (d) whether any banner/preamble wraps the answer. If the argv form works, keep `ARGV` as-is. **If only the stdin form works, change `_run()` in Step 3 to pass `input=prompt` and drop the prompt from the argv list.** If `claude` is not installed, run the same probe with `codex exec` and implement against that.

Long prompts are the reason this matters: a RAG-assembled prompt can exceed the OS argv length limit, so stdin is the safer form when both work.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_agent_cli.py
"""The subprocess contract. The model is a seam: every caller keeps talking LangChain."""

from __future__ import annotations

import subprocess

import pytest
from pydantic import BaseModel

from tarnish.agent_cli import AgentCliChatModel


class _Reply(BaseModel):
    verdict: bool
    reason: str


def _fake_run(stdout: str, returncode: int = 0):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")
    return run


def test_generate_returns_stdout_as_message(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("  PONG  \n"))
    model = AgentCliChatModel(argv=["fake-cli"])

    assert model.invoke([("human", "ping")]).content == "PONG"


def test_nonzero_exit_raises_with_the_command_named(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("", returncode=2))
    model = AgentCliChatModel(argv=["fake-cli"])

    with pytest.raises(RuntimeError, match="fake-cli"):
        model.invoke([("human", "ping")])


def test_structured_output_parses_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run('{"verdict": true, "reason": "canary echoed"}'))
    model = AgentCliChatModel(argv=["fake-cli"])

    result = model.with_structured_output(_Reply).invoke([("human", "judge this")])

    assert result.verdict is True
    assert result.reason == "canary echoed"


def test_structured_output_tolerates_a_fenced_block(monkeypatch):
    fenced = '```json\n{"verdict": false, "reason": "control matched"}\n```'
    monkeypatch.setattr(subprocess, "run", _fake_run(fenced))
    model = AgentCliChatModel(argv=["fake-cli"])

    assert model.with_structured_output(_Reply).invoke([("human", "judge this")]).verdict is False
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_agent_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tarnish.agent_cli'`

- [ ] **Step 4: Implement**

```python
# src/tarnish/agent_cli.py
"""A LangChain chat model that shells out to an already-authenticated coding-agent CLI.

This is the seam that makes Tarnish keyless: `claude -p` and `codex exec` draw on the
developer's existing subscription, so no API key is needed. Every caller keeps using the
LangChain interface and knows nothing about subprocesses."""

from __future__ import annotations

import subprocess
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda


class AgentCliChatModel(BaseChatModel):
    """Text in, text out, via a subprocess. `temperature` is accepted and ignored — agent
    CLIs do not expose it; callers pass it because ChatOpenAI did."""

    argv: list[str]
    timeout: int = 180
    temperature: float = 0.7

    @property
    def _llm_type(self) -> str:
        return "agent-cli"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = "\n\n".join(f"{m.type.upper()}: {m.content}" for m in messages)
        completed = subprocess.run(
            [*self.argv, prompt],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{' '.join(self.argv)} exited {completed.returncode}: {completed.stderr.strip()[:400]}"
            )
        message = AIMessage(content=completed.stdout.strip())
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        """Prompt-based, because a subprocess has no tool-calling. One retry: agent CLIs
        occasionally wrap the answer in prose, and asking again is cheaper than failing."""
        parser = PydanticOutputParser(pydantic_object=schema)

        def _append_format_instructions(messages: Any) -> list[Any]:
            return [*list(messages), ("human", parser.get_format_instructions())]

        return (RunnableLambda(_append_format_instructions) | self | parser).with_retry(
            stop_after_attempt=2
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent_cli.py -v`
Expected: PASS, 4 tests.

If only `test_structured_output_tolerates_a_fenced_block` fails, `PydanticOutputParser` did not strip the code fence. Insert this step between `self` and `parser` in the chain:

```python
def _strip_fence(message: AIMessage) -> AIMessage:
    """Agent CLIs like to answer in a ```json block. The parser wants bare JSON."""
    text = message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return AIMessage(content=text.strip())
```

making the chain:

```python
return (
    RunnableLambda(_append_format_instructions) | self | RunnableLambda(_strip_fence) | parser
).with_retry(stop_after_attempt=2)
```

- [ ] **Step 6: Commit**

```bash
git add src/tarnish/agent_cli.py tests/test_agent_cli.py
git commit -m "M1: AgentCliChatModel — LangChain chat model over an agent CLI subprocess

Prompt-based with_structured_output because a subprocess has no native
tool-calling, and evaluator.py depends on that method. The seam keeps
every caller on the LangChain interface.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Wire `get_chat_model` to the resolved backend

**Files:**
- Modify: `src/tarnish/llm.py:14-16`
- Test: `tests/test_backends.py` (append)

**Interfaces:**
- Consumes: `resolve_backend()`, `ARGV` from `backends.py`; `AgentCliChatModel` from `agent_cli.py`.
- Produces: `get_chat_model(temperature: float = 0.7) -> BaseChatModel` — unchanged signature, so `agents/base.py:36` and `evaluator.py:59` need no edit.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_backends.py
from tarnish.agent_cli import AgentCliChatModel
from tarnish.llm import get_chat_model


def test_get_chat_model_returns_the_cli_model_when_a_cli_is_present(monkeypatch):
    _only(monkeypatch, "claude")
    monkeypatch.setattr(backends, "_forced_backend", lambda: "")
    model = get_chat_model(temperature=0)
    assert isinstance(model, AgentCliChatModel)
    assert model.argv == ["claude", "-p"]


def test_get_chat_model_falls_back_to_openai(monkeypatch):
    _only(monkeypatch)
    monkeypatch.setattr(backends, "_forced_backend", lambda: "")
    monkeypatch.setattr(backends, "_api_keys", lambda: {"openai": "sk-x", "anthropic": ""})
    assert type(get_chat_model()).__name__ == "ChatOpenAI"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_backends.py -v`
Expected: FAIL — `get_chat_model` still returns `ChatOpenAI` unconditionally.

- [ ] **Step 3: Implement**

Replace `get_chat_model` in `src/tarnish/llm.py`:

```python
def get_chat_model(temperature: float = 0.7) -> BaseChatModel:
    """Attack generation, judging and remediation all come through here. The backend is
    resolved per call so tests and `llm_backend` overrides take effect without a restart."""
    s = get_settings()
    backend = resolve_backend()
    if backend in ARGV:
        return AgentCliChatModel(argv=ARGV[backend], temperature=temperature)
    if backend == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=s.llm_model, api_key=s.anthropic_api_key, temperature=temperature)
    return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, temperature=temperature)
```

Add the imports at the top of `llm.py`:

```python
from langchain_core.language_models.chat_models import BaseChatModel

from .agent_cli import AgentCliChatModel
from .backends import ARGV, resolve_backend
```

If the `anthropic` branch is exercised, add the dependency: `uv add langchain-anthropic`. If it is not needed yet, delete that branch and its enum member rather than shipping an untested path.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_backends.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all green. `tests/test_specialists.py` and `tests/test_evaluator.py` exercise `get_chat_model` — if either now hits a real subprocess, it was relying on a live key and needs the same `monkeypatch.setattr(subprocess, "run", ...)` fake used in Task 4. Fix the test, not the seam.

- [ ] **Step 6: Commit**

```bash
git add src/tarnish/llm.py tests/test_backends.py
git commit -m "M1: get_chat_model dispatches on the resolved backend

Signature unchanged, so agents/base.py and evaluator.py are untouched.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Correct the stale documentation

**Files:**
- Modify: `.env.example`
- Modify: `PLAN.md`
- Modify: `README.md`

> Why now: these three contradict the current non-negotiables, and M2's plan will be written against them. Spec §9.

- [ ] **Step 1: Fix `.env.example`**

Replace the LLM block. The judge line is superseded — falsifiability comes from the mandatory control, not from the judge's provider family.

```bash
# --- Langfuse (OPTIONAL — tracing is off unless both keys are set) ---
# A trace contains your system prompt, the payloads that worked and your unfixed
# vulnerabilities. Enable it only if you want that recorded.
# Self-hosting: point LANGFUSE_HOST at your own instance (the core is MIT).
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com          # US cloud: https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=redteam              # ^(?!langfuse)[a-z0-9-_]+$, <=40 chars

# --- Model backend (OPTIONAL — auto-detected) ---
# Tarnish uses the coding-agent CLI you already have logged in: `claude -p`, then
# `codex exec`. Set a key only if you have neither, or for CI.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
# Force one backend instead of auto-detecting: claude_cli | codex_cli | openai | anthropic
TARNISH_LLM_BACKEND=
```

- [ ] **Step 2: Fix the two stale claims in `PLAN.md`**

Find the line stating Langfuse is the source of the report and replace it with: the report renders from the persisted `CampaignResult` JSON (`reporting/render.py`); Langfuse is observability only and is optional. Then add to the post-Phase-0 update block at the top:

```markdown
> - **Langfuse is optional and off by default.** A trace is a dossier of how to attack the
>   target, so it never leaves the machine unless both keys are set. The report renders from
>   the persisted `CampaignResult`, never from traces.
> - **The engine is keyless by default.** `llm.py` resolves to `claude -p` / `codex exec`
>   before any API key; embeddings are local (fastembed). See M1.
```

- [ ] **Step 3: Fix `README.md`**

Three edits.

(a) In `## Non-negotiables`, replace the `Judge != target model family` bullet with:

```markdown
- **Falsifiability comes from the mandatory control**, not from knowing the target's model.
  Operators paste a URL and don't know what model runs behind it, so Tarnish never asks.
```

(b) In `## Setup`, delete the `cp .env.example .env` line's Langfuse mention and replace the block with:

```markdown
## Setup

```bash
uv sync                              # create the venv, install deps + the project
uv run playwright install chromium   # one-time: headless browser (~115MB), only for --live
```

No API key needed if you have `claude` or `codex` on your PATH — Tarnish uses the coding-agent
CLI you are already logged into. Otherwise put `OPENAI_API_KEY` in a `.env`.
```

(c) Replace the whole `## Phase 0 - foundation (current)` section with:

```markdown
## Running a campaign

```bash
uv run tarnish run --target aurea         # control + attacks -> evaluate -> remediate -> report
uv run tarnish gate0 --target aurea       # one benign request only, no attacks
```

Findings land in `reports/<target>-<timestamp>.json` with an HTML report beside them.

## Optional: tracing

Tarnish runs with tracing off. A trace holds your system prompt, the payloads that worked and
your unfixed vulnerabilities — a dossier on how to attack you — so it stays local unless you
ask otherwise. To enable it, set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`; point
`LANGFUSE_HOST` at Langfuse Cloud or your own instance (the core is MIT and self-hostable).
The report itself never depends on Langfuse — it renders from the campaign JSON.
```

- [ ] **Step 4: Verify nothing else contradicts**

Run: `uv run python -c "import pathlib,re; [print(p, i+1, l.strip()) for p in map(pathlib.Path, ['README.md','PLAN.md','.env.example']) for i,l in enumerate(p.read_text(encoding='utf-8').splitlines()) if re.search(r'different (provider )?family|source of the report|anti score-inflation', l, re.I)]"`
Expected: no output. Any line printed is a leftover — fix it.

- [ ] **Step 5: Commit**

```bash
git add .env.example PLAN.md README.md
git commit -m "M1: correct stale docs — judge family, report source, optional Langfuse

Three documents still asserted superseded non-negotiables. M2's plan gets
written against these, so they cannot stay wrong.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Gate M1

**Files:** none modified — this task produces evidence.

> This is the milestone gate from spec §12. It is not green until every step below is observed, not assumed.

- [ ] **Step 1: Prove the suite is green**

Run: `uv run pytest -q`
Expected: every test passes. Record the count.

- [ ] **Step 2: Prove the campaign runs with zero API keys**

Temporarily move the key file aside so nothing can leak in from it:

```bash
mv .env .env.bak
uv run tarnish run --target aurea --max-tasks 2
```

Expected, and all four must hold:
1. It completes and writes a JSON report under `reports/`.
2. The last line reads `tracing off — set LANGFUSE_PUBLIC_KEY/SECRET_KEY to trace this campaign`.
3. No OpenAI authentication error appears anywhere in the output.
4. The control response is non-empty in the JSON (`control_baseline`).

If it fails with `NoBackendAvailable`, that is a **pass for the error path** but not for the gate: install or log into `claude` and run it again.

- [ ] **Step 3: Prove tracing still works when asked**

```bash
mv .env.bak .env
uv run tarnish run --target aurea --max-tasks 2
```

Expected: no `tracing off` line, and the campaign appears in Langfuse under environment `redteam`. Record the trace id.

- [ ] **Step 4: Record the gate in CLAUDE.md**

Add to the Phases section, under Phase 2:

```markdown
**M1 — keyless engine: DONE.** `llm.py` resolves `claude -p` -> `codex exec` -> API key;
embeddings are local (fastembed, Chroma rebuilt at 384 dims); Langfuse is opt-in and no-ops
without keys. *Gate passed:* full campaign on Aurea with `.env` removed, control non-empty,
no auth error; tracing re-verified with keys restored (trace `<id>`).
```

- [ ] **Step 5: Commit and merge**

```bash
git add CLAUDE.md
git commit -m "M1: gate passed — campaign runs keyless on Aurea

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git checkout main
git merge --no-ff phase-2-m1-keyless-engine
```

---

## Self-review notes

- **Spec coverage:** §3.2 → Tasks 3–5. §7.1 → Task 2. §9 (optional Langfuse, no telemetry) → Tasks 1 and 6. §12 M1 gate → Task 7. §7.2 (canaries) and §7.3 (helper drift) are **deliberately M2/M3**, not gaps.
- **Deviation from the spec, stated:** the spec's Gate M1 says "`explore`"; this plan keeps the command named `run`. Rationale in Global Constraints.
- **Open risk carried into Task 4:** the exact `claude -p` prompt-passing form is unverified, which is why Step 1 of that task is a probe rather than an assumption. If stdin is required, the change is confined to `_run()`.
