"""`AnthropicProvider` (TASK-014): `LLMProvider` backed by the official
`anthropic` Python SDK.

Dependency justification (CLAUDE.md §6): the `anthropic` package is the
official, vendor-maintained client for the Anthropic Messages API
(authentication, request/response serialization, retries and error
types). The alternative -- calling the REST API directly with the
already-present `requests` dependency -- was considered and rejected: it
would require reimplementing and maintaining authentication, versioning
and error handling for an external API by hand, exactly the kind of
fragile, high-maintenance code an official SDK avoids (CLAUDE.md §6.3).
A third-party unifying library (e.g. LiteLLM) was also considered and
rejected: it would add a further abstraction layer on top of the one
this module already builds (`LLMProvider`), against CLAUDE.md §5.

The Anthropic Messages API requires `max_tokens` on every call (unlike
OpenAI's Chat Completions API, where it is optional) -- `DEFAULT_MAX_TOKENS`
is therefore an internal implementation constant needed to make any call
at all, not a capability exposed on the provider-agnostic
`CompletionRequest` contract (approved TASK-014 spec).

The `client` (an `anthropic.Anthropic` instance) is always injected by
the caller, never constructed here -- see `app.llm.factory` for how a
real client is built from `Settings`, and the test suite for how a fake
client is injected to test this module without any network call.
"""

from __future__ import annotations

import anthropic

from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Message, Usage

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024


class AnthropicProvider(LLMProvider):
    """`LLMProvider` implementation wrapping `anthropic.Anthropic`."""

    def __init__(self, client: anthropic.Anthropic, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        self._client = client
        self._model = model

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        system, turns = _split_system_message(request.messages)
        anthropic_messages: list[anthropic.types.MessageParam] = [
            {"role": message.role, "content": message.content} for message in turns
        ]

        try:
            if system is not None:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    system=system,
                    messages=anthropic_messages,
                )
            else:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    messages=anthropic_messages,
                )
        except anthropic.APIError as exc:
            raise LLMProviderError(f"Anthropic completion failed: {exc}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return CompletionResponse(text=text, usage=usage)


def _split_system_message(messages: list[Message]) -> tuple[str | None, list[Message]]:
    """Extract a leading system message, if any (see module docstring of
    `app.llm.provider` for why Anthropic needs `system` split out of `messages`).
    """
    if messages and messages[0].role == "system":
        return messages[0].content, messages[1:]
    return None, messages
