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


def test_text_of_survives_a_malformed_block_and_a_non_dict_entry():
    """A block can declare `type: "text"` with no `text` key, or the list can hold something
    that isn't a dict at all. Neither should raise — this helper's whole job is to never crash
    a campaign at the moment it tries to record evidence."""
    content = ["not-a-dict", {"type": "text"}, {"type": "text", "text": "hello"}]
    assert text_of(_R(content)) == "hello"
