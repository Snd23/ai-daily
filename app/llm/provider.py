"""The `LLMProvider` abstraction (TASK-014).

Defines the provider-agnostic contract every LLM provider implementation
(`app.llm.anthropic_provider.AnthropicProvider`,
`app.llm.openai_provider.OpenAIProvider`) must satisfy, and the minimal
typed request/response shapes that contract uses.

Scope (approved TASK-014 spec, docs/PRD.md §22, CLAUDE.md §19): this
module exposes a single generic completion primitive. It deliberately
does NOT define `summarize`, `explain`, `classify` or `rank` -- those are
domain-specific use cases owned by their own future consumer tasks
(TASK-015 Summarization, TASK-016 AI Senza Sbatti, and, respectively, a
not-yet-scheduled classification task; ranking is already fully
deterministic, see `app.ranking.event_ranker`, and never needs an LLM
call). Defining those methods here now would mean inventing their
request/response domain models (e.g. `Summary`, `ConceptExplanation`)
ahead of the task that actually owns them -- explicitly out of scope.

`CompletionRequest.messages` models a provider-agnostic chat turn list
(`role` + `content` only -- no tools, no JSON schema/structured output, no
temperature/top_p or other generation parameters not requested by the
approved spec). At most one message may have `role="system"`, and if
present it must be the first message: this is the minimum rule needed to
translate the same `CompletionRequest` deterministically into both
supported APIs, since Anthropic's Messages API takes the system prompt as
a separate top-level parameter while OpenAI's Chat Completions API takes
it as a message in the list.

`CompletionResponse.usage` is intentionally minimal (raw input/output
token counts): it serves CLAUDE.md §35 (cost control) without
implementing any cost/budget logic, which is out of scope here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    """One turn in a provider-agnostic chat conversation."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class CompletionRequest(BaseModel):
    """A provider-agnostic completion request.

    `messages` must be non-empty. At most one message may have
    `role="system"`, and if present it must be `messages[0]` (see module
    docstring) -- a missing or malformed system placement fails
    validation rather than being silently reordered or dropped
    (CLAUDE.md §41).
    """

    model_config = ConfigDict(frozen=True)

    messages: list[Message]

    @model_validator(mode="after")
    def _validate_messages(self) -> CompletionRequest:
        if not self.messages:
            raise ValueError("messages must not be empty")

        system_indices = [i for i, message in enumerate(self.messages) if message.role == "system"]
        if len(system_indices) > 1:
            raise ValueError("at most one system message is allowed")
        if system_indices and system_indices[0] != 0:
            raise ValueError("a system message, if present, must be first")

        return self


class Usage(BaseModel):
    """Raw token usage for one completion call (CLAUDE.md §35)."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class CompletionResponse(BaseModel):
    """A provider-agnostic completion result. `usage` is optional."""

    model_config = ConfigDict(frozen=True)

    text: str
    usage: Usage | None = None


class LLMProvider(ABC):
    """Provider-agnostic abstraction over a single LLM completion call.

    Concrete implementations (`AnthropicProvider`, `OpenAIProvider`) wrap
    a specific vendor SDK and never leak vendor-specific exceptions to
    the caller: any underlying SDK failure is raised as
    `app.llm.errors.LLMProviderError` instead (CLAUDE.md §19 -- the rest
    of the application must not depend on a specific provider's SDK).
    """

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run one completion call and return its result.

        Raises:
            app.llm.errors.LLMProviderError: if the underlying provider
                call fails.
        """
        raise NotImplementedError
