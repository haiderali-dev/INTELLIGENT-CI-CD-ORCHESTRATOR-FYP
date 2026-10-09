"""``ModelChain``, the quota tracker and the response cache.

The acceptance clause these serve: "with Groq unreachable, the rule parser answers and the response
carries ``ai_fallback: true``". The rest pins the decisions 4.5.1 leaves to judgement -- that a long
retry-after rests a model instead of making a user wait, that a second model answering is already a
fallback, and that every attempt is recorded, including the ones that failed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.cache import ResponseCache, cache_key, normalise
from app.ai.chain import ModelChain
from app.ai.providers import (
    ChatMessage,
    FakeProvider,
    InvalidResponseError,
    ProviderRejectedError,
    ProviderUnavailableError,
    RateLimitedError,
    ReplayMissError,
)
from app.ai.quota import ModelLimits, QuotaTracker

BIG = "openai/gpt-oss-120b"
SMALL = "openai/gpt-oss-20b"
MESSAGES = [ChatMessage(role="user", content="Build payment-service")]
SCHEMA: dict[str, Any] = {"type": "object"}
RULES_ANSWER = {"action": "BUILD", "service": "payment-service", "confidence": 0.6}


class Clock:
    def __init__(self, start: float = 1_760_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Sleeper:
    """Records waits instead of performing them, so tests stay instant."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def chain_with(
    fake: FakeProvider,
    *,
    models: tuple[str, ...] = (BIG, SMALL),
    quota: QuotaTracker | None = None,
    cache: ResponseCache | None = None,
    sleeper: Sleeper | None = None,
    max_wait: float = 10.0,
) -> ModelChain:
    return ModelChain(
        fake,
        models,
        quota=quota or QuotaTracker(),
        cache=cache,
        sleep=sleeper or Sleeper(),
        max_wait=max_wait,
    )


async def run(chain: ModelChain, key: str | None = None) -> Any:
    return await chain.complete(
        schema=SCHEMA,
        system="system",
        messages=MESSAGES,
        rules_fallback=lambda: dict(RULES_ANSWER),
        cache_key=key,
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_the_first_model_answers_with_no_fallback() -> None:
    result = await run(chain_with(FakeProvider(script=[{"action": "BUILD"}])))

    assert result.parser == "llm"
    assert result.model == BIG
    assert result.ai_fallback is False
    assert [call.outcome for call in result.calls] == ["ok"]


# ---------------------------------------------------------------------------
# The acceptance clause
# ---------------------------------------------------------------------------


async def test_with_groq_unreachable_the_rule_parser_answers_with_ai_fallback() -> None:
    """Phase 4 acceptance, verbatim: every model unreachable, every retry spent."""
    down = ProviderUnavailableError("connection refused")
    fake = FakeProvider(per_model={BIG: [down, down, down], SMALL: [down, down, down]})

    result = await run(chain_with(fake))

    assert result.parser == "rules"
    assert result.ai_fallback is True
    assert result.data == RULES_ANSWER
    assert result.model is None
    # Three attempts per model -- the first and two retries, as 4.5.1 allows -- all recorded.
    assert [call.outcome for call in result.calls] == ["unavailable"] * 6
    assert fake.calls_to(BIG) == 3
    assert fake.calls_to(SMALL) == 3


async def test_no_configured_models_still_gets_an_answer() -> None:
    result = await run(chain_with(FakeProvider(), models=()))

    assert result.parser == "rules"
    assert result.ai_fallback is True
    assert result.fallback_reasons == ("no models configured",)


# ---------------------------------------------------------------------------
# Moving down the chain
# ---------------------------------------------------------------------------


async def test_the_second_model_answering_is_already_a_fallback() -> None:
    """The UI should be able to show that the answer came from the smaller model."""
    fake = FakeProvider(
        per_model={BIG: [InvalidResponseError("not JSON")], SMALL: [{"action": "BUILD"}]}
    )

    result = await run(chain_with(fake))

    assert result.parser == "llm"
    assert result.model == SMALL
    assert result.ai_fallback is True
    assert result.calls[-1].fallback_used is True


async def test_an_invalid_answer_is_not_retried_on_the_same_model() -> None:
    """At temperature 0 the same prompt tends to repeat the same unusable answer."""
    fake = FakeProvider(
        per_model={
            BIG: [InvalidResponseError("bad"), {"action": "BUILD"}],
            SMALL: [{"action": "TEST"}],
        }
    )

    result = await run(chain_with(fake))

    assert fake.calls_to(BIG) == 1
    assert result.model == SMALL


async def test_a_rejection_is_not_retried() -> None:
    """A 401 or a rejected schema fails identically on every attempt."""
    fake = FakeProvider(
        per_model={BIG: [ProviderRejectedError("401")], SMALL: [{"action": "BUILD"}]}
    )

    await run(chain_with(fake))

    assert fake.calls_to(BIG) == 1


async def test_a_replay_miss_falls_through_to_the_rules() -> None:
    """A stale fixture set shows up as fallbacks rather than as silently wrong answers."""
    fake = FakeProvider(
        per_model={BIG: [ReplayMissError("no fixture")], SMALL: [ReplayMissError("none")]}
    )

    result = await run(chain_with(fake))

    assert result.parser == "rules"
    assert [call.outcome for call in result.calls] == ["replay_miss", "replay_miss"]


async def test_a_crashing_provider_falls_back_instead_of_raising() -> None:
    """A bug in a provider must not become an error page; it is logged with its traceback."""

    class Broken(FakeProvider):
        async def complete_json(self, **kwargs: Any) -> Any:
            raise KeyError("choices")

    result = await run(chain_with(Broken()))

    assert result.parser == "rules"
    assert {call.outcome for call in result.calls} == {"error"}


# ---------------------------------------------------------------------------
# Retries and waiting
# ---------------------------------------------------------------------------


async def test_a_short_rate_limit_is_waited_out_on_the_same_model() -> None:
    sleeper = Sleeper()
    fake = FakeProvider(
        per_model={BIG: [RateLimitedError("slow", retry_after=2.0), {"action": "BUILD"}]}
    )

    result = await run(chain_with(fake, sleeper=sleeper))

    assert result.model == BIG
    assert result.ai_fallback is False
    assert sleeper.waits == [2.0]


async def test_a_long_rate_limit_rests_the_model_instead_of_making_the_user_wait() -> None:
    """Honoring retry-after means not calling the model before then, not sitting in a request."""
    sleeper = Sleeper()
    quota = QuotaTracker()
    fake = FakeProvider(
        per_model={
            BIG: [RateLimitedError("daily", retry_after=4000.0, exhausted=True)],
            SMALL: [{"action": "BUILD"}],
        }
    )

    result = await run(chain_with(fake, sleeper=sleeper, quota=quota))

    assert sleeper.waits == []
    assert result.model == SMALL
    assert quota.check(BIG).allowed is False


async def test_a_rested_model_is_skipped_without_being_called() -> None:
    """The next request after an exhaustion must not spend a call rediscovering it."""
    quota = QuotaTracker()
    quota.block(BIG, 3600, "rate limited")
    fake = FakeProvider(per_model={SMALL: [{"action": "BUILD"}]})

    result = await run(chain_with(fake, quota=quota))

    assert fake.calls_to(BIG) == 0
    assert result.calls[0].outcome == "skipped"
    assert result.model == SMALL


async def test_retries_stop_at_two_per_model() -> None:
    """4.5.1: "at most twice per model"."""
    limited = RateLimitedError("slow", retry_after=1.0)
    fake = FakeProvider(
        per_model={
            BIG: [limited, limited, limited, {"action": "BUILD"}],
            SMALL: [{"action": "TEST"}],
        }
    )

    result = await run(chain_with(fake))

    assert fake.calls_to(BIG) == 3
    assert result.model == SMALL


async def test_an_unavailable_model_backs_off_between_retries() -> None:
    sleeper = Sleeper()
    down = ProviderUnavailableError("503")
    fake = FakeProvider(per_model={BIG: [down, {"action": "BUILD"}]})

    result = await run(chain_with(fake, sleeper=sleeper))

    assert result.model == BIG
    assert len(sleeper.waits) == 1
    assert 0 < sleeper.waits[0] < 2


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


def test_the_daily_request_limit_blocks_until_midnight() -> None:
    clock = Clock()
    quota = QuotaTracker({BIG: ModelLimits(1000, 2, 10**9, 10**9)}, clock=clock)

    quota.record(BIG, prompt_tokens=10, completion_tokens=10)
    quota.record(BIG, prompt_tokens=10, completion_tokens=10)

    verdict = quota.check(BIG)
    assert not verdict.allowed
    assert "daily request limit" in verdict.reason
    assert verdict.wait_seconds > 0


def test_the_daily_counter_resets_on_a_new_utc_day() -> None:
    clock = Clock()
    quota = QuotaTracker({BIG: ModelLimits(1000, 1, 10**9, 10**9)}, clock=clock)
    quota.record(BIG, prompt_tokens=1, completion_tokens=1)
    assert not quota.check(BIG).allowed

    clock.advance(86_400)

    assert quota.check(BIG).allowed


def test_the_per_minute_token_budget_leaves_headroom() -> None:
    """Refused before the next call would be, not after."""
    clock = Clock()
    quota = QuotaTracker({BIG: ModelLimits(1000, 1000, 8000, 10**9)}, clock=clock)
    quota.record(BIG, prompt_tokens=6000, completion_tokens=600)

    verdict = quota.check(BIG)
    assert not verdict.allowed
    assert verdict.wait_seconds <= 60

    clock.advance(61)
    assert quota.check(BIG).allowed


def test_the_server_saying_zero_remaining_overrides_the_local_count() -> None:
    """Local counters only see this process; the server sees the eval harness too."""
    clock = Clock()
    quota = QuotaTracker(clock=clock)

    quota.observe(BIG, {"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "2h"})

    verdict = quota.check(BIG)
    assert not verdict.allowed
    assert verdict.wait_seconds == pytest.approx(7200, abs=1)


def test_the_server_limits_replace_the_assumed_defaults() -> None:
    quota = QuotaTracker()

    quota.observe(
        SMALL, {"x-ratelimit-limit-requests": "14400", "x-ratelimit-limit-tokens": "6000"}
    )

    limits = quota.limits_for(SMALL)
    assert limits.requests_per_day == 14400
    assert limits.tokens_per_minute == 6000


def test_a_rest_expires_on_its_own() -> None:
    """A long-running backend must recover the next day, not fall back to rules forever."""
    clock = Clock()
    quota = QuotaTracker(clock=clock)
    quota.block(BIG, 30, "rate limited")
    assert not quota.check(BIG).allowed

    clock.advance(31)

    assert quota.check(BIG).allowed


async def test_a_successful_call_is_counted() -> None:
    quota = QuotaTracker()
    fake = FakeProvider(script=[{"action": "BUILD"}], prompt_tokens=171, completion_tokens=47)

    await run(chain_with(fake, quota=quota))

    assert quota.snapshot()[BIG]["tokens_today"] == 218
    assert quota.snapshot()[BIG]["requests_today"] == 1


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


async def test_an_identical_command_is_served_from_the_cache() -> None:
    cache = ResponseCache()
    fake = FakeProvider(script=[{"action": "BUILD"}])
    chain = chain_with(fake, cache=cache)

    first = await run(chain, key="k")
    second = await run(chain, key="k")

    assert first.cached is False
    assert second.cached is True
    assert second.data == first.data
    assert len(fake.calls) == 1
    # Still recorded: a cache hit is a call that cost nothing, which the eval has to count.
    assert second.calls[0].outcome == "cached"
    assert second.calls[0].cached is True


async def test_a_rules_fallback_is_never_cached() -> None:
    """Otherwise a brief outage would pin the weaker answer for ten minutes."""
    cache = ResponseCache()
    down = ProviderUnavailableError("down")
    chain = chain_with(FakeProvider(per_model={BIG: [down] * 3, SMALL: [down] * 3}), cache=cache)

    await run(chain, key="k")

    assert len(cache) == 0


def test_cached_entries_expire_after_ten_minutes() -> None:
    clock = Clock()
    cache = ResponseCache(clock=clock)
    cache.put("k", data={"a": 1}, provider="groq", model=BIG, ai_fallback=False)

    clock.advance(599)
    assert cache.get("k") is not None
    clock.advance(2)
    assert cache.get("k") is None


def test_the_cache_is_bounded() -> None:
    cache = ResponseCache(capacity=3)
    for index in range(10):
        cache.put(str(index), data={}, provider="groq", model=BIG, ai_fallback=False)

    assert len(cache) == 3
    assert cache.get("0") is None
    assert cache.get("9") is not None


def test_normalisation_folds_case_and_whitespace_only() -> None:
    assert normalise("  Build   PAYMENT-service\n") == "build payment-service"
    # Branch names keep their punctuation: folding it would merge distinct refs.
    assert normalise("from feature/refund") != normalise("from feature-refund")


@pytest.mark.parametrize(
    "change",
    [
        {"role": "ADMIN"},
        {"catalog_fingerprint": "different"},
        {"prompt_version": "intent_v2"},
        {"history": ["build auth-service"]},
        {"model_chain": ("other",)},
    ],
)
def test_the_cache_key_changes_with_anything_that_changes_the_answer(
    change: dict[str, Any],
) -> None:
    """The same words under a new catalog, role, prompt or history are a different question."""
    base: dict[str, Any] = {
        "text": "build payment-service",
        "role": "DEVELOPER",
        "catalog_fingerprint": "abc",
        "prompt_version": "intent_v1",
        "history": [],
        "model_chain": (BIG,),
    }

    assert cache_key(**base) != cache_key(**{**base, **change})


def test_the_cache_key_ignores_case_and_spacing() -> None:
    common: dict[str, Any] = {
        "role": "DEVELOPER",
        "catalog_fingerprint": "abc",
        "prompt_version": "v1",
    }

    assert cache_key(text="Build  payment-service", **common) == cache_key(
        text="build payment-service", **common
    )
