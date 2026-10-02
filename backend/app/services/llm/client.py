"""The boundary to LLM providers. Services depend on `ChatClient`; tests replace it."""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol

import groq

from app.config import get_settings
from app.services.llm.retry import call_with_retries


class LLMError(Exception):
    """An LLM call failed. Messages are safe to show to the user."""


class LLMNotConfiguredError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    """Rate-limited, overloaded or unreachable even after retries."""


class LLMRequestError(LLMError):
    """The provider rejected the request (bad key, bad model, invalid input)."""


class ChatClient(Protocol):
    def complete_json(
        self, *, model: str, system: str, user: str, schema_name: str, schema: dict[str, Any]
    ) -> str:
        """Return the model's reply: a JSON document that follows `schema`."""
        ...


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, exactly as the model wrote it (may be invalid)


@dataclass(frozen=True)
class AgentTurn:
    """One model reply: either text, or a request to run tools (or both)."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()


class AgentClient(Protocol):
    def complete_with_tools(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        force_answer: bool,
    ) -> AgentTurn:
        """One chat turn with tools offered. `force_answer` forbids further tool calls."""
        ...


def _is_retryable(exc: Exception) -> bool:
    # 429, 5xx, and network failures/timeouts (APITimeoutError is an APIConnectionError).
    return isinstance(exc, groq.RateLimitError | groq.InternalServerError | groq.APIConnectionError)


def _rejected_generation(exc: LLMRequestError) -> str | None:
    """The model's reply when Groq rejected it only for not matching the JSON schema
    (`json_validate_failed`, e.g. a nullable field left out). Our callers validate every reply
    with their own models, which decide; any other rejection gives None."""
    cause = exc.__cause__
    if not isinstance(cause, groq.BadRequestError) or not isinstance(cause.body, dict):
        return None
    error = cause.body.get("error", cause.body)
    if not isinstance(error, dict) or error.get("code") != "json_validate_failed":
        return None
    generation = error.get("failed_generation")
    return generation if isinstance(generation, str) and generation else None


def _retry_after(exc: Exception) -> float | None:
    if isinstance(exc, groq.APIStatusError):
        try:
            return float(exc.response.headers.get("retry-after", ""))
        except ValueError:
            return None
    return None


class GroqChatClient:
    """Groq chat completions with strict JSON-schema output and our own retry policy."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60.0,
        attempts: int = 4,
        max_delay: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # SDK retries are off so `call_with_retries` is the single, tested policy.
        self._client = groq.Groq(api_key=api_key, max_retries=0, timeout=timeout)
        self._attempts = attempts
        self._max_delay = max_delay
        self._sleep = sleep

    def _send[T](self, call: Callable[[], T]) -> T:
        """Run one API call with our retry policy, mapping failures to LLMError."""
        try:
            return call_with_retries(
                call,
                is_retryable=_is_retryable,
                retry_after=_retry_after,
                attempts=self._attempts,
                max_delay=self._max_delay,
                sleep=self._sleep,
            )
        except (groq.RateLimitError, groq.InternalServerError, groq.APIConnectionError) as exc:
            raise LLMUnavailableError(
                "The AI service is busy or unreachable. Please try again in a minute."
            ) from exc
        except groq.APIStatusError as exc:
            if exc.status_code == 413:
                raise LLMRequestError(
                    "The text was too large for the AI service's free tier (status 413)."
                ) from exc
            raise LLMRequestError(
                f"The AI service rejected the request (status {exc.status_code})."
            ) from exc

    def complete_json(
        self, *, model: str, system: str, user: str, schema_name: str, schema: dict[str, Any]
    ) -> str:
        def call() -> str:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                temperature=0,
                seed=0,
                reasoning_effort="low",
                reasoning_format="hidden",
                # Even a large health-checkup report fits; a runaway reply is cut off and then
                # fails validation instead of running up to the model's 65k-token limit.
                max_completion_tokens=16_384,
            )
            return response.choices[0].message.content or ""

        try:
            content = self._send(call)
        except LLMRequestError as exc:
            rejected = _rejected_generation(exc)
            if rejected is None:
                raise
            content = rejected
        try:
            json.loads(content)
        except ValueError as exc:
            raise LLMRequestError("The AI service returned something that is not JSON.") from exc
        return content

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        force_answer: bool,
    ) -> AgentTurn:
        tool_choice: Literal["none", "auto"] = "none" if force_answer else "auto"
        # Plain dicts in the documented shape (the SDK's TypedDicts are stricter than needed).
        sent_messages: list[Any] = list(messages)
        sent_tools: list[Any] = list(tools)

        def call() -> AgentTurn:
            response = self._client.chat.completions.create(
                model=model,
                messages=sent_messages,
                tools=sent_tools,
                tool_choice=tool_choice,
                temperature=0,
                seed=0,
                reasoning_effort="low",
                include_reasoning=False,  # gpt-oss: keep the reasoning out of the response
                max_completion_tokens=4096,
            )
            message = response.choices[0].message
            return AgentTurn(
                content=message.content or "",
                tool_calls=tuple(
                    ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
                    for c in message.tool_calls or ()
                ),
            )

        return self._send(call)


@lru_cache
def get_agent_client() -> AgentClient:
    """The query agent's client (one per process)."""
    key = get_settings().groq_api_key
    if key is None:
        raise LLMNotConfiguredError("GROQ_API_KEY is not set, so the assistant is not available.")
    return GroqChatClient(key.get_secret_value())


@lru_cache
def get_structuring_client() -> ChatClient:
    """Reads reports in the background, so it can wait: a large report is sent in parts, and
    later parts wait for the free tier's per-minute token window (Groq's Retry-After, up to a
    minute each time). One shared client (and HTTP connection pool) for the process."""
    key = get_settings().groq_api_key
    if key is None:
        raise LLMNotConfiguredError("GROQ_API_KEY is not set, so reports cannot be structured.")
    return GroqChatClient(key.get_secret_value(), attempts=6, max_delay=60.0)


@lru_cache
def get_explanation_client() -> ChatClient:
    """Explains findings while someone waits on the page: the usual, shorter retries."""
    key = get_settings().groq_api_key
    if key is None:
        raise LLMNotConfiguredError("GROQ_API_KEY is not set, so explanations are not available.")
    return GroqChatClient(key.get_secret_value())
