"""`GeminiProvider` (TASK-014 follow-up): `LLMProvider` backed by the
official `google-genai` Python SDK (Gemini Developer API).

Dependency justification (CLAUDE.md §6): `google-genai` is Google's
official, vendor-maintained client for the Gemini API (authentication,
request/response serialization, retries and error types) -- the same
rationale already recorded for `anthropic`/`openai` in
`app/llm/anthropic_provider.py` and `app/llm/openai_provider.py`: a
hand-rolled REST client over `requests`, or a third-party unifying
library on top of the `LLMProvider` abstraction this module already
builds, were both considered and rejected for the same reasons.

Motivation for a third provider: Anthropic and OpenAI both require a paid
API key. The Gemini Developer API (Google AI Studio) has a free tier with
no billing required -- `DEFAULT_GEMINI_MODEL` is a Flash-tier model,
confirmed free-tier eligible, not the more expensive Pro tier.

Gemini's `generate_content` API differs from both existing providers:
- A conversation turn is a `Content` with `role="user"` or `role="model"`
  (not `"assistant"`) plus a list of `Part`s; the provider-agnostic
  `Message.role="assistant"` is mapped to `"model"`.
- A system prompt is not a message in the turn list (unlike OpenAI) nor a
  top-level parameter to the same call (unlike Anthropic's
  `messages.create`); it is `GenerateContentConfig.system_instruction`, so
  it is split out of `messages` the same way `AnthropicProvider` already
  splits out its `system` parameter.
- `max_tokens` is optional, like OpenAI's Chat Completions API -- Gemini
  imposes no equivalent required parameter, so none is sent.

The `client` (a `genai.Client` instance) is always injected by the
caller, never constructed here -- see `app.llm.factory` for how a real
client is built from `Settings`, and the test suite for how a fake
client is injected to test this module without any network call.
"""

from __future__ import annotations

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.llm.errors import LLMProviderError
from app.llm.provider import CompletionRequest, CompletionResponse, LLMProvider, Message, Usage

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

_ROLE_MAP: dict[str, str] = {"user": "user", "assistant": "model"}


class GeminiProvider(LLMProvider):
    """`LLMProvider` implementation wrapping `google.genai.Client`."""

    def __init__(self, client: genai.Client, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self._client = client
        self._model = model

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        system, turns = _split_system_message(request.messages)
        contents = [
            types.Content(
                role=_ROLE_MAP[message.role],
                parts=[types.Part.from_text(text=message.content)],
            )
            for message in turns
        ]
        config = (
            types.GenerateContentConfig(system_instruction=system) if system is not None else None
        )

        try:
            # `contents` is `list[Content]`; `generate_content` declares its
            # parameter as `list[Content | ...]`, and mypy's list invariance
            # rejects the narrower type even though it is always valid at
            # runtime (same kind of SDK-typing mismatch already worked
            # around in `app.llm.openai_provider`).
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,  # type: ignore[arg-type]
                config=config,
            )
        except APIError as exc:
            raise LLMProviderError(f"Gemini completion failed: {exc}") from exc

        text = response.text or ""
        usage = None
        if response.usage_metadata is not None:
            usage = Usage(
                input_tokens=response.usage_metadata.prompt_token_count or 0,
                output_tokens=response.usage_metadata.candidates_token_count or 0,
            )
        return CompletionResponse(text=text, usage=usage)


def _split_system_message(messages: list[Message]) -> tuple[str | None, list[Message]]:
    """Extract a leading system message, if any (see module docstring of
    `app.llm.provider` for why Gemini, like Anthropic, needs `system`
    split out of `messages`).
    """
    if messages and messages[0].role == "system":
        return messages[0].content, messages[1:]
    return None, messages
