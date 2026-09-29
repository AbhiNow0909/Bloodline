"""The boundary to LLM providers. Services depend on `ChatClient`; tests replace it."""

import json
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol

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


def _is_retryable(exc: Exception) -> bool:
    # 429, 5xx, and network failures/timeouts (APITimeoutError is an APIConnectionError).
    return isinstance(exc, groq.RateLimitError | groq.InternalServerError | groq.APIConnectionError)


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
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # SDK retries are off so `call_with_retries` is the single, tested policy.
        self._client = groq.Groq(api_key=api_key, max_retries=0, timeout=timeout)
        self._attempts = attempts
        self._sleep = sleep

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
            content = call_with_retries(
                call,
                is_retryable=_is_retryable,
                retry_after=_retry_after,
                attempts=self._attempts,
                sleep=self._sleep,
            )
        except (groq.RateLimitError, groq.InternalServerError, groq.APIConnectionError) as exc:
            raise LLMUnavailableError(
                "The AI service is busy or unreachable. Please try again in a minute."
            ) from exc
        except groq.APIStatusError as exc:
            raise LLMRequestError(
                f"The AI service rejected the request (status {exc.status_code})."
            ) from exc
        try:
            json.loads(content)
        except ValueError as exc:
            raise LLMRequestError("The AI service returned something that is not JSON.") from exc
        return content


@lru_cache
def get_structuring_client() -> ChatClient:
    """One shared client (and HTTP connection pool) for the process."""
    key = get_settings().groq_api_key
    if key is None:
        raise LLMNotConfiguredError("GROQ_API_KEY is not set, so reports cannot be structured.")
    return GroqChatClient(key.get_secret_value())
