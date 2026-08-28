"""A LangChain chat model that shells out to an already-authenticated coding-agent CLI.

This is the seam that makes most of Tarnish keyless: `claude -p` and `codex exec` draw on
the developer's existing subscription, so the target, judge, recon and remediation roles
need no API key. Attack GENERATION is the measured exception (2026-08-28): both CLIs refuse
that prompt on AUP grounds, which is why `get_attacker_model()` puts the API backends first.
Every caller keeps using the LangChain interface and knows nothing about subprocesses."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from .config import get_settings


class AgentCliChatModel(BaseChatModel):
    """Text in, text out, via a subprocess. `temperature` is accepted and ignored - agent
    CLIs do not expose it; callers pass it because ChatOpenAI did."""

    argv: list[str]
    # How this CLI takes a system prompt, if it can. None = it cannot, and the messages fall
    # back to one flattened stdin blob. That fallback is D1: persona and payload arrive at the
    # same privilege level, so there is no hierarchy for an injection to violate.
    system_flag: str | None = None
    # Defaults from Settings (tunable without a code change); an explicit timeout= from a
    # caller (several tests rely on a short one) still wins over the setting.
    timeout: int = Field(default_factory=lambda: get_settings().agent_cli_timeout)
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
        argv = list(self.argv)
        system = [m for m in messages if m.type == "system"]
        if system and self.system_flag:
            argv += [self.system_flag, "\n\n".join(str(m.content) for m in system)]
            # Only the untrusted turn goes over stdin, unprefixed: exactly what the surface
            # would carry in production.
            prompt = "\n\n".join(str(m.content) for m in messages if m.type != "system")
        else:
            prompt = "\n\n".join(f"{m.type.upper()}: {m.content}" for m in messages)
        # The prompt goes over stdin: a RAG-assembled one can exceed the OS argv limit.
        # which() because Windows CreateProcess ignores PATHEXT, so a bare `codex`
        # (a .CMD shim) raises FileNotFoundError while the resolved path works.
        executable, *rest = argv
        completed = subprocess.run(
            [shutil.which(executable) or executable, *rest],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            encoding="utf-8",
            errors="replace",
            # A neutral cwd: agent CLIs auto-discover project context (CLAUDE.md, AGENTS.md)
            # from where they run, and inside our own repo the model answers as Tarnish's
            # assistant rather than as the target. Half of D1.
            cwd=tempfile.gettempdir(),
        )
        if completed.returncode != 0:
            # Agent CLIs put their real message on stdout (e.g. Claude Code's AUP refusal),
            # leaving stderr empty. Prefer whichever stream carried it, or the error is opaque.
            detail = (completed.stderr.strip() or completed.stdout.strip())[:400]
            raise RuntimeError(f"{' '.join(self.argv)} exited {completed.returncode}: {detail}")
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
