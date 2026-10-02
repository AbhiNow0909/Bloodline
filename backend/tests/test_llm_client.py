"""Our retry policy and error mapping around the Groq SDK (no network calls)."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import groq
import httpx
import pytest

from app.config import Settings
from app.services.llm import (
    AgentTurn,
    GroqChatClient,
    LLMNotConfiguredError,
    LLMRequestError,
    LLMUnavailableError,
    ToolCall,
    get_agent_client,
    get_explanation_client,
    get_structuring_client,
)
from app.services.llm import client as client_module
from app.services.llm.retry import call_with_retries

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
FAKE_KEY = "gsk_test_not_a_real_key"


def status_error(
    error: type[groq.APIStatusError], status: int, headers: dict[str, str] | None = None
) -> groq.APIStatusError:
    return error(
        "error", response=httpx.Response(status, headers=headers, request=REQUEST), body=None
    )


class FakeCreate:
    """Stands in for `chat.completions.create`: raises or returns the queued outcomes."""

    def __init__(self, *outcomes: Exception | str) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))])


@pytest.fixture
def sleeps() -> list[float]:
    return []


def make_client(monkeypatch: pytest.MonkeyPatch, fake: FakeCreate, sleeps: list[float]) -> Any:
    client = GroqChatClient(FAKE_KEY, sleep=sleeps.append)
    monkeypatch.setattr(client._client.chat.completions, "create", fake)
    return client


def complete(client: GroqChatClient) -> str:
    return client.complete_json(
        model="some-model", system="sys", user="text", schema_name="s", schema={"type": "object"}
    )


def test_request_uses_strict_json_schema_and_deterministic_settings(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate('{"tests": []}')

    assert complete(make_client(monkeypatch, fake, sleeps)) == '{"tests": []}'

    sent = fake.calls[0]
    assert sent["model"] == "some-model"
    assert sent["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "text"},
    ]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert (sent["temperature"], sent["reasoning_format"]) == (0, "hidden")
    assert sent["max_completion_tokens"] == 16_384


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda: status_error(groq.RateLimitError, 429), id="429"),
        pytest.param(lambda: status_error(groq.InternalServerError, 503), id="503"),
        pytest.param(lambda: groq.APIConnectionError(request=REQUEST), id="connection"),
        pytest.param(lambda: groq.APITimeoutError(request=REQUEST), id="timeout"),
    ],
)
def test_transient_failures_are_retried(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], failure: Any
) -> None:
    fake = FakeCreate(failure(), failure(), '{"ok": true}')

    assert complete(make_client(monkeypatch, fake, sleeps)) == '{"ok": true}'
    assert len(fake.calls) == 3
    assert len(sleeps) == 2


def test_retry_after_header_is_honoured(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate(status_error(groq.RateLimitError, 429, {"retry-after": "7"}), "{}")

    complete(make_client(monkeypatch, fake, sleeps))

    assert sleeps == [7.0]


def test_gives_up_with_a_friendly_error_after_four_attempts(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate(*(status_error(groq.RateLimitError, 429) for _ in range(4)))

    with pytest.raises(LLMUnavailableError, match="busy"):
        complete(make_client(monkeypatch, fake, sleeps))
    assert len(fake.calls) == 4
    assert len(sleeps) == 3


def test_rejected_requests_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate(status_error(groq.AuthenticationError, 401))

    with pytest.raises(LLMRequestError, match="status 401") as excinfo:
        complete(make_client(monkeypatch, fake, sleeps))
    assert len(fake.calls) == 1
    assert sleeps == []
    assert FAKE_KEY not in str(excinfo.value)


def test_a_reply_that_is_not_json_is_an_error(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate("Sure! Here are the results: ...")

    with pytest.raises(LLMRequestError, match="not JSON"):
        complete(make_client(monkeypatch, fake, sleeps))


def test_backoff_doubles_with_jitter_and_is_capped() -> None:
    sleeps: list[float] = []
    attempts: Iterator[Exception | str] = iter([ValueError(), ValueError(), ValueError(), "done"])

    def flaky() -> str:
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = call_with_retries(
        flaky,
        is_retryable=lambda exc: isinstance(exc, ValueError),
        base_delay=1.0,
        max_delay=3.0,
        sleep=sleeps.append,
        jitter=lambda: 1.0,  # the largest possible random fraction
    )

    assert result == "done"
    assert sleeps == [1.0, 2.0, 3.0]  # 1, 2, then 4 capped at 3


def test_non_retryable_errors_propagate_immediately() -> None:
    def broken() -> str:
        raise KeyError("bug")

    def never_sleep(seconds: float) -> None:
        pytest.fail("a non-retryable error must not be retried")

    with pytest.raises(KeyError):
        call_with_retries(broken, is_retryable=lambda exc: False, sleep=never_sleep)


def test_structuring_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "jwt_secret": "s" * 32,
        "groq_api_key": "   ",  # as when .env has an empty GROQ_API_KEY=
    }
    settings = Settings(_env_file=None, **values)
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)
    get_structuring_client.cache_clear()  # the client is cached per process

    assert settings.groq_api_key is None  # blank means "not configured"
    with pytest.raises(LLMNotConfiguredError, match="GROQ_API_KEY"):
        get_structuring_client()


# --- tool calling (the query agent) ---------------------------------------------------------


class FakeToolCreate:
    """`chat.completions.create` returning tool calls or text, or raising."""

    def __init__(self, *outcomes: Exception | SimpleNamespace) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=outcome)])


def tool_message(content: str | None, *calls: tuple[str, str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        tool_calls=[
            SimpleNamespace(id=i, function=SimpleNamespace(name=n, arguments=a))
            for i, n, a in calls
        ]
        or None,
    )


TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]


def test_tool_calls_are_requested_and_parsed(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeToolCreate(tool_message(None, ("call_1", "f", '{"x": 1}')))
    client = GroqChatClient(FAKE_KEY, sleep=sleeps.append)
    monkeypatch.setattr(client._client.chat.completions, "create", fake)
    messages = [{"role": "user", "content": "hi"}]

    turn = client.complete_with_tools(model="m", messages=messages, tools=TOOLS, force_answer=False)

    assert turn == AgentTurn("", (ToolCall("call_1", "f", '{"x": 1}'),))
    sent = fake.calls[0]
    assert sent["messages"] == messages
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "auto"
    assert sent["include_reasoning"] is False  # gpt-oss reasoning stays out of the response
    assert sent["reasoning_effort"] == "low"
    assert (sent["temperature"], sent["seed"]) == (0, 0)


def test_forcing_an_answer_turns_tools_off(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeToolCreate(tool_message("Done."))
    client = GroqChatClient(FAKE_KEY, sleep=sleeps.append)
    monkeypatch.setattr(client._client.chat.completions, "create", fake)

    turn = client.complete_with_tools(model="m", messages=[], tools=TOOLS, force_answer=True)

    assert turn == AgentTurn("Done.")
    assert fake.calls[0]["tool_choice"] == "none"


def test_tool_calling_shares_the_retry_policy_and_errors(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeToolCreate(
        status_error(groq.RateLimitError, 429), tool_message("ok"),
        *(status_error(groq.RateLimitError, 429) for _ in range(4)),
        status_error(groq.AuthenticationError, 401),
    )  # fmt: skip
    client = GroqChatClient(FAKE_KEY, sleep=sleeps.append)
    monkeypatch.setattr(client._client.chat.completions, "create", fake)

    def ask() -> AgentTurn:
        return client.complete_with_tools(model="m", messages=[], tools=TOOLS, force_answer=False)

    assert ask().content == "ok"
    with pytest.raises(LLMUnavailableError, match="busy"):
        ask()
    with pytest.raises(LLMRequestError, match="status 401"):
        ask()


def test_the_agent_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "jwt_secret": "s" * 32,
        "groq_api_key": "",
    }
    settings = Settings(_env_file=None, **values)
    get_agent_client.cache_clear()
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)
    try:
        with pytest.raises(LLMNotConfiguredError, match="assistant is not available"):
            get_agent_client()
    finally:
        get_agent_client.cache_clear()


# --- large reports ----------------------------------------------------------------------------


def test_a_too_large_request_is_explained_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeCreate(status_error(groq.APIStatusError, 413))

    with pytest.raises(LLMRequestError, match="too large for the AI service's free tier"):
        complete(make_client(monkeypatch, fake, sleeps))
    assert len(fake.calls) == 1


def test_a_patient_client_waits_as_long_as_retry_after_asks(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    def busy() -> FakeCreate:
        return FakeCreate(
            *(status_error(groq.RateLimitError, 429, {"retry-after": "45"}) for _ in range(5)), "{}"
        )

    patient = GroqChatClient(FAKE_KEY, attempts=6, max_delay=60.0, sleep=sleeps.append)
    monkeypatch.setattr(patient._client.chat.completions, "create", busy())
    complete(patient)
    assert sleeps == [45.0] * 5

    sleeps.clear()
    with pytest.raises(LLMUnavailableError):
        complete(make_client(monkeypatch, busy(), sleeps))  # the usual client gives up sooner
    assert sleeps == [20.0] * 3


def test_reports_are_read_patiently_and_explanations_quickly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "jwt_secret": "s" * 32,
        "groq_api_key": FAKE_KEY,
    }
    monkeypatch.setattr(client_module, "get_settings", lambda: Settings(_env_file=None, **values))
    get_structuring_client.cache_clear()
    get_explanation_client.cache_clear()
    try:
        structuring: Any = get_structuring_client()
        explanation: Any = get_explanation_client()
        assert (structuring._attempts, structuring._max_delay) == (6, 60.0)
        assert (explanation._attempts, explanation._max_delay) == (4, 20.0)
    finally:
        get_structuring_client.cache_clear()
        get_explanation_client.cache_clear()


def rejected(code: str, generation: str | None) -> groq.BadRequestError:
    """Groq's 400 for a reply it judged not to match the JSON schema."""
    error: dict[str, Any] = {"message": "Generated JSON does not match", "code": code}
    if generation is not None:
        error["failed_generation"] = generation
    return groq.BadRequestError(
        "error", response=httpx.Response(400, request=REQUEST), body={"error": error}
    )


def test_a_reply_groq_rejected_for_the_schema_is_handed_back_for_our_own_checks(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    reply = '{"tests": [{"raw_name": "FERRITIN", "value": "48.3"}]}'  # "panel" left out
    fake = FakeCreate(rejected("json_validate_failed", reply))

    assert complete(make_client(monkeypatch, fake, sleeps)) == reply
    assert len(fake.calls) == 1  # no retry, no extra tokens


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (rejected("invalid_request_error", '{"tests": []}'), "status 400"),
        (rejected("json_validate_failed", None), "status 400"),
        (rejected("json_validate_failed", "{not json"), "not JSON"),
    ],
)
def test_other_rejections_are_still_errors(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], error: Exception, message: str
) -> None:
    with pytest.raises(LLMRequestError, match=message):
        complete(make_client(monkeypatch, FakeCreate(error), sleeps))
