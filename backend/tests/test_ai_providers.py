"""Providers: Groq's error mapping, replay by prompt hash, and the fake.

``GroqProvider`` is tested through the real ``openai`` SDK with a stubbed HTTP transport rather
than by mocking the SDK. Mocking the SDK would test what the mock returns; this tests what the SDK
actually raises for a 429 or a 503, which is the thing the chain's decisions rest on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import openai
import pytest

from app.ai.intent import Action, ExtraStage, Intent, TargetEnvironment, Urgency
from app.ai.providers import (
    ChatMessage,
    FakeProvider,
    GroqProvider,
    InvalidResponseError,
    ProviderRejectedError,
    ProviderUnavailableError,
    RateLimitedError,
    RecordingProvider,
    ReplayMissError,
    ReplayProvider,
    prompt_hash,
)
from app.ai.providers.groq import parse_duration

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action"],
    "properties": {"action": {"type": "string"}},
}
MESSAGES = [ChatMessage(role="user", content="Build payment-service from main")]
MODEL = "openai/gpt-oss-120b"


def completion_body(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 171, "completion_tokens": 47, "total_tokens": 218},
    }


def groq_with(handler: Any) -> GroqProvider:
    client = openai.AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return GroqProvider("test-key", client=client)


async def call(provider: GroqProvider) -> Any:
    return await provider.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)


# ---------------------------------------------------------------------------
# GroqProvider
# ---------------------------------------------------------------------------


async def test_a_good_answer_parses_with_usage_and_headers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        # The request must ask for a strict schema; that is what 4.5.1 requires.
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["temperature"] == 0
        return httpx2.Response(
            200,
            json=completion_body('{"action":"BUILD"}'),
            headers={
                "x-ratelimit-remaining-requests": "999",
                "x-ratelimit-limit-tokens": "8000",
            },
        )

    result = await call(groq_with(handler))

    assert result.data == {"action": "BUILD"}
    assert result.prompt_tokens == 171
    assert result.completion_tokens == 47
    assert result.rate_limit["x-ratelimit-remaining-requests"] == "999"


async def test_a_short_429_is_retryable_with_its_wait() -> None:
    provider = groq_with(
        lambda request: httpx2.Response(
            429,
            json={"error": {"message": "slow down"}},
            headers={"retry-after": "2", "x-ratelimit-remaining-requests": "500"},
        )
    )

    with pytest.raises(RateLimitedError) as exc:
        await call(provider)

    assert exc.value.retry_after == 2.0
    assert exc.value.exhausted is False


async def test_a_429_with_no_requests_left_is_exhaustion() -> None:
    """The daily bucket is empty: waiting inside a request would be absurd."""
    provider = groq_with(
        lambda request: httpx2.Response(
            429,
            json={"error": {"message": "daily limit"}},
            headers={
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "1h12m",
            },
        )
    )

    with pytest.raises(RateLimitedError) as exc:
        await call(provider)

    assert exc.value.exhausted is True
    assert exc.value.retry_after == pytest.approx(4320.0)


async def test_a_long_retry_after_is_treated_as_exhaustion() -> None:
    provider = groq_with(
        lambda request: httpx2.Response(429, json={}, headers={"retry-after": "120"})
    )

    with pytest.raises(RateLimitedError) as exc:
        await call(provider)

    assert exc.value.exhausted is True


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_5xx_is_unavailable_and_retryable(status: int) -> None:
    provider = groq_with(lambda request: httpx2.Response(status, json={}))

    with pytest.raises(ProviderUnavailableError) as exc:
        await call(provider)

    assert exc.value.retryable


async def test_a_connection_failure_is_unavailable() -> None:
    def explode(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(ProviderUnavailableError):
        await call(groq_with(explode))


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_4xx_is_rejected_and_not_retryable(status: int) -> None:
    """A bad key or a rejected schema fails the same way on every retry."""
    provider = groq_with(lambda request: httpx2.Response(status, json={"error": {"message": "no"}}))

    with pytest.raises(ProviderRejectedError) as exc:
        await call(provider)

    assert not exc.value.retryable


async def test_a_truncated_answer_is_invalid_not_parsed() -> None:
    """A cut-off object is worse than none: it might parse into something wrong."""
    provider = groq_with(
        lambda request: httpx2.Response(200, json=completion_body('{"action":"BU', finish="length"))
    )

    with pytest.raises(InvalidResponseError, match="truncated"):
        await call(provider)


async def test_an_answer_that_is_not_json_is_invalid() -> None:
    provider = groq_with(lambda request: httpx2.Response(200, json=completion_body("Sure! Here")))

    with pytest.raises(InvalidResponseError, match="not JSON"):
        await call(provider)


async def test_a_json_array_is_invalid() -> None:
    provider = groq_with(lambda request: httpx2.Response(200, json=completion_body("[1,2]")))

    with pytest.raises(InvalidResponseError, match="not a JSON object"):
        await call(provider)


def test_the_provider_refuses_to_start_without_a_key() -> None:
    """Better than a 401 on the first user's first command."""
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqProvider("")


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("2", 2.0),
        ("4.282s", 4.282),
        ("1m26.4s", 86.4),
        ("2h3m", 7380.0),
        ("500ms", 0.5),
        ("", None),
        (None, None),
        ("soon", None),
    ],
)
def test_groq_durations_parse(text: str | None, seconds: float | None) -> None:
    """The formats observed in live x-ratelimit-reset-* headers."""
    assert parse_duration(text) == (pytest.approx(seconds) if seconds is not None else None)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


async def test_a_recorded_answer_replays(tmp_path: Path) -> None:
    inner = FakeProvider(script=[{"action": "BUILD"}])
    recorder = RecordingProvider(inner, tmp_path)
    await recorder.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)

    replayed = await ReplayProvider(tmp_path).complete_json(
        schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL
    )

    assert replayed.data == {"action": "BUILD"}
    assert replayed.provider == "replay"


async def test_a_changed_prompt_misses_rather_than_replaying_a_stale_answer(
    tmp_path: Path,
) -> None:
    """A fixture that matched after a prompt edit would replay an answer the new prompt might
    never produce."""
    recorder = RecordingProvider(FakeProvider(script=[{"action": "BUILD"}]), tmp_path)
    await recorder.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)

    with pytest.raises(ReplayMissError):
        await ReplayProvider(tmp_path).complete_json(
            schema=SCHEMA, system="s v2", messages=MESSAGES, model=MODEL
        )


async def test_a_different_model_misses(tmp_path: Path) -> None:
    recorder = RecordingProvider(FakeProvider(script=[{"action": "BUILD"}]), tmp_path)
    await recorder.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)

    with pytest.raises(ReplayMissError):
        await ReplayProvider(tmp_path).complete_json(
            schema=SCHEMA, system="s", messages=MESSAGES, model="openai/gpt-oss-20b"
        )


async def test_a_failure_is_never_recorded(tmp_path: Path) -> None:
    """Recording a failure would make the replay fail the same way forever."""
    recorder = RecordingProvider(FakeProvider(script=[ProviderUnavailableError("down")]), tmp_path)

    with pytest.raises(ProviderUnavailableError):
        await recorder.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)

    assert not fixtures_in(tmp_path)


def fixtures_in(directory: Path) -> list[Path]:
    """Synchronous, so the async test body does no blocking file I/O."""
    return list(directory.rglob("*.json"))


def plant_corrupt_fixture(replay: ReplayProvider) -> None:
    """Synchronous setup, kept out of the async test body where file I/O would block the loop."""
    digest = prompt_hash(model=MODEL, system="s", messages=MESSAGES, schema=SCHEMA)
    path = replay.fixture_path(digest)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")


async def test_a_corrupt_fixture_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    replay = ReplayProvider(tmp_path)
    plant_corrupt_fixture(replay)

    with pytest.raises(ReplayMissError, match="unreadable"):
        await replay.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)


def test_the_prompt_hash_ignores_key_order() -> None:
    """The schema builder does not promise an order; equal schemas must hash equal."""
    first = {"type": "object", "properties": {"a": {}, "b": {}}}
    second = {"properties": {"b": {}, "a": {}}, "type": "object"}

    assert prompt_hash(model=MODEL, system="s", messages=MESSAGES, schema=first) == prompt_hash(
        model=MODEL, system="s", messages=MESSAGES, schema=second
    )


# ---------------------------------------------------------------------------
# Fake
# ---------------------------------------------------------------------------


async def test_the_fake_follows_a_per_model_script() -> None:
    fake = FakeProvider(
        per_model={MODEL: [RateLimitedError("x", exhausted=True)], "small": [{"action": "TEST"}]}
    )

    with pytest.raises(RateLimitedError):
        await fake.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model=MODEL)
    result = await fake.complete_json(schema=SCHEMA, system="s", messages=MESSAGES, model="small")

    assert result.data == {"action": "TEST"}
    assert fake.calls_to(MODEL) == 1


async def test_the_fake_streams() -> None:
    chunks = [
        chunk
        async for chunk in FakeProvider().stream_text(system="s", messages=MESSAGES, model=MODEL)
    ]

    assert "".join(chunks) == "This is a fake explanation."


# ---------------------------------------------------------------------------
# Intent coercion: the model is never trusted
# ---------------------------------------------------------------------------


def test_a_well_formed_answer_becomes_an_intent() -> None:
    intent, notes = Intent.from_untrusted(
        {
            "action": "DEPLOY",
            "service": "auth-service",
            "environment": "staging",
            "urgency": "HIGH",
            "justification": "hotfix for login bug",
            "extra_stages": ["lint"],
            "confidence": 0.9,
        }
    )

    assert notes == []
    assert intent.action is Action.DEPLOY
    assert intent.environment is TargetEnvironment.STAGING
    assert intent.urgency is Urgency.HIGH
    assert intent.extra_stages == (ExtraStage.LINT,)


def test_an_unknown_value_becomes_null_with_a_note() -> None:
    """A null field asks one question; an exception would show an error page."""
    intent, notes = Intent.from_untrusted(
        {"action": "DEPLOY", "environment": "moon", "urgency": "extreme", "confidence": 0.5}
    )

    assert intent.environment is None
    assert intent.urgency is None
    assert len(notes) == 2


def test_production_is_parsed_faithfully_not_rewritten() -> None:
    """Appendix E: let the policy layer refuse it; never silently change it to staging."""
    intent, _ = Intent.from_untrusted({"action": "DEPLOY", "environment": "Production"})

    assert intent.environment is TargetEnvironment.PRODUCTION


def test_an_unknown_action_is_unsupported() -> None:
    intent, notes = Intent.from_untrusted({"action": "LAUNCH_MISSILES"})

    assert intent.action is Action.UNSUPPORTED
    assert notes


def test_confidence_is_clamped_not_rejected() -> None:
    """The strict schema cannot express bounds; 1.2 still means "very sure"."""
    high, _ = Intent.from_untrusted({"action": "BUILD", "confidence": 1.2})
    low, _ = Intent.from_untrusted({"action": "BUILD", "confidence": -3})
    junk, notes = Intent.from_untrusted({"action": "BUILD", "confidence": "very"})

    assert high.confidence == 1.0
    assert low.confidence == 0.0
    assert junk.confidence == 0.0
    assert notes


def test_an_empty_string_is_null() -> None:
    """``""`` for a branch would read as an explicit branch called nothing."""
    intent, _ = Intent.from_untrusted({"action": "BUILD", "branch": "  ", "service": ""})

    assert intent.branch is None
    assert intent.service is None


def test_duplicate_extra_stages_collapse() -> None:
    intent, _ = Intent.from_untrusted({"action": "BUILD", "extra_stages": ["lint", "LINT", "lint"]})

    assert intent.extra_stages == (ExtraStage.LINT,)


def test_a_non_text_field_is_dropped_with_a_note() -> None:
    intent, notes = Intent.from_untrusted({"action": "BUILD", "service": ["payment-service"]})

    assert intent.service is None
    assert any("service" in note for note in notes)


def test_an_overlong_justification_is_truncated() -> None:
    """It is copied into an audit entry; a megabyte of text there is a problem of its own."""
    intent, _ = Intent.from_untrusted({"action": "DEPLOY", "justification": "x" * 5000})

    assert intent.justification is not None
    assert len(intent.justification) == 500
