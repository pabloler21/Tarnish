"""text_of: the response-content extraction shared by every chat-model call site."""

from __future__ import annotations

from tarnish.llm import text_of


class _R:
    def __init__(self, content):
        self.content = content


def test_text_of_passes_through_a_plain_string():
    assert text_of(_R("hello")) == "hello"


def test_text_of_joins_text_blocks_with_no_repr_noise():
    """The API-key fallback backends can return content as a list of blocks
    (`[{"type": "text", "text": "..."}]`) instead of a bare string."""
    content = [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]
    result = text_of(_R(content))
    assert result == "hello world"
    assert "{" not in result and "'" not in result
