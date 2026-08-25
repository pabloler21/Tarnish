"""A LangChain chat model that shells out to an already-authenticated coding-agent CLI.

This is the seam that makes Tarnish keyless: `claude -p` and `codex exec` draw on the
developer's existing subscription, so no API key is needed. Every caller keeps using the
LangChain interface and knows nothing about subprocesses."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda


class AgentCliChatModel(BaseChatModel):
    """Text in, text out, via a subprocess. `temperature` is accepted and ignored - agent
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
        # The prompt goes over stdin: a RAG-assembled one can exceed the OS argv limit.
        # which() because Windows CreateProcess ignores PATHEXT, so a bare `codex`
        # (a .CMD shim) raises FileNotFoundError while the resolved path works.
        executable, *rest = self.argv
        completed = subprocess.run(
            [shutil.which(executable) or executable, *rest],
            input=prompt,
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
