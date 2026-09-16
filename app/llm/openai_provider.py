"""`OpenAIProvider` (TASK-014): `LLMProvider` backed by the official
`openai` Python SDK.

Dependency justification (CLAUDE.md §6): same rationale as
`app.llm.anthropic_provider` -- the `openai` package is the official,
vendor-maintained client for the OpenAI Chat Completions API; calling the
REST API by hand with `requests`, or adding a third-party unifying
library on top of the `LLMProvider` abstraction this module already
builds, were both considered and rejected for the same reasons.

Unlike Anthropic's Messages API, OpenAI's Chat Completions API accepts a
`role="system"` message directly inside `messages` and does not require
`max_tokens` to be set. This provider therefore passes the
provider-agnostic `CompletionRequest.messages` straight through, with no
message splitting and no `max_tokens` (approved TASK-014 correction: the
Anthropic-only `DEFAULT_MAX_TOKENS` constant must not be applied to the
OpenAI call "for symmetry" -- only parameters the OpenAI API actually
needs are sent).

The `client` (an `openai.OpenAI` instance) is always injected by the
caller, never constructed here -- see `app.llm.factory` for how a real
client is built from `Settings`, and the test suite for how a fake
client is injected to test this module without any network call.
"""

from __future__ import annotations

import openai
from openai.types.chat import ChatCompletionMessageParam

from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Usage

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"


class OpenAIProvider(LLMProvider):
    """`LLMProvider` implementation wrapping `openai.OpenAI`."""

    def __init__(self, client: openai.OpenAI, model: str = DEFAULT_OPENAI_MODEL) -> None:
        self._client = client
        self._model = model

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        openai_messages: list[ChatCompletionMessageParam] = [
            {"role": message.role, "content": message.content}  # type: ignore[misc]
            for message in request.messages
        ]

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=openai_messages,
            )
        except openai.APIError as exc:
            raise LLMProviderError(f"OpenAI completion failed: {exc}") from exc

        text = response.choices[0].message.content or ""
        usage = None
        if response.usage is not None:
            usage = Usage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )
        return CompletionResponse(text=text, usage=usage)
