"""The plugin client.

The plugin may be absent -- on ``jenkins-baseline`` it deliberately is -- so the property that
matters most is that every call degrades to "unavailable" instead of raising. A queue page that
500s because the plugin is missing is worse than one that shows Jenkins' own ordering with a note.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.settings import Settings
from app.services.plugin import (
    FakePluginClient,
    HttpPluginClient,
    PluginHealth,
    Ranking,
    parse_health,
    parse_ranking,
)

# A payload in the shape 4.3.10 specifies for GET /dynamic-queue/api/json.
RANKING_BODY = {
    "configuration": {
        "optimizerEnabled": True,
        "weightUrgency": 0.5,
        "weightDependency": 0.3,
        "weightExecutionTime": 0.2,
        "agingBonusPerInterval": 0.05,
        "agingIntervalMinutes": 5,
        "agingCap": 0.15,
    },
    "items": [
        {
            "rank": 1,
            "itemId": 11,
            "jobName": "payment-service-build",
            "jobType": "FreeStyleProject",
            "level": "HIGH",
            "score": 0.667,
            "baseScore": 0.667,
            "agingBonus": 0.0,
            "urgencyFactor": 1.0,
            "dependencyFactor": 0.5,
            "executionTimeFactor": 0.335,
            "estimateSeconds": 42.0,
            "waitSeconds": 3.0,
            "groupId": "payment-service",
            "topologicalRank": 0,
            "blockedReason": None,
            "unresolvedDependencies": [],
        },
        {
            "rank": 2,
            "itemId": 12,
            "jobName": "auth-service-test",
            "jobType": "WorkflowJob",
            "level": "MEDIUM",
            "score": 0.650,
            "baseScore": 0.633,
            "agingBonus": 0.05,
            "urgencyFactor": 0.6,
            "dependencyFactor": 1.0,
            "executionTimeFactor": 0.25,
            "estimateSeconds": None,
            "waitSeconds": 310.0,
            "groupId": "auth-service",
            "topologicalRank": 1,
            "blockedReason": "waiting for payment-service-build",
            "unresolvedDependencies": ["legacy-job"],
        },
    ],
}

# Recorded verbatim from GET /dynamic-queue/health on the live jenkins-dev on 2026-10-07, with
# only the numbers changed. Written from a real response rather than from the specification's
# prose: an earlier version of this file guessed "droppedMetrics" where the plugin actually sends
# "droppedMetricCount", so the parser reported zero dropped events however many were lost.
LIVE_HEALTH_BODY = {
    "enabled": True,
    "lastSortDurationMillis": 2.4,
    "cacheHitRate": 0.82,
    "heapSize": 7,
    "metricsEnabled": True,
    "metricsPublishable": True,
    "droppedMetricCount": 3,
    "publishedMetricCount": 118,
    "failedMetricCount": 1,
    "pendingMetricCount": 2,
    "weightsSumToOne": True,
}


def client_with(handler: httpx.MockTransport, settings: Settings) -> HttpPluginClient:
    """An HttpPluginClient whose transport is a stub."""
    plugin = HttpPluginClient(settings)
    plugin._client = httpx.AsyncClient(base_url="http://jenkins-dev:8080", transport=handler)
    return plugin


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_the_ranking_payload_parses() -> None:
    ranking = parse_ranking(RANKING_BODY)

    assert ranking.available
    assert ranking.optimizer_enabled
    assert ranking.queue_length == 2
    assert ranking.weights == {"urgency": 0.5, "dependency": 0.3, "executionTime": 0.2}


def test_score_components_are_kept_separate_from_the_total() -> None:
    """4.3.10 requires the components; the analytics page explains a rank with them."""
    first = parse_ranking(RANKING_BODY).items[0]

    assert first.score == pytest.approx(0.667)
    assert first.components.urgency == pytest.approx(1.0)
    assert first.components.dependency == pytest.approx(0.5)
    assert first.components.execution_time == pytest.approx(0.335)
    assert first.components.aging_bonus == pytest.approx(0.0)


def test_the_aged_item_keeps_its_base_score_and_bonus_apart() -> None:
    """Report Appendix C prints the pre-aging score; both numbers have to survive the round trip."""
    second = parse_ranking(RANKING_BODY).items[1]

    assert second.components.base_score == pytest.approx(0.633)
    assert second.components.aging_bonus == pytest.approx(0.05)
    assert second.score == pytest.approx(0.650)


def test_blocked_reasons_and_unresolved_dependencies_survive() -> None:
    second = parse_ranking(RANKING_BODY).items[1]

    assert second.blocked_reason == "waiting for payment-service-build"
    assert second.unresolved_dependencies == ("legacy-job",)
    assert second.topological_rank == 1


def test_a_missing_estimate_stays_none_rather_than_zero() -> None:
    """Zero would read as "instant", which is the opposite of "not known yet"."""
    assert parse_ranking(RANKING_BODY).items[1].estimate_seconds is None
    assert parse_ranking(RANKING_BODY).items[0].estimate_seconds == pytest.approx(42.0)


def test_one_malformed_field_costs_only_itself() -> None:
    """The plugin and backend are versioned apart; a string where a number was does not lose all."""
    body = {
        "configuration": {"optimizerEnabled": True},
        "items": [{"rank": 1, "itemId": 1, "jobName": "j", "score": "not-a-number"}],
    }

    ranking = parse_ranking(body)

    assert ranking.queue_length == 1
    assert ranking.items[0].job_name == "j"
    assert ranking.items[0].score == 0.0


def test_items_that_are_not_objects_are_skipped() -> None:
    body = {"items": ["nonsense", None, {"rank": 1, "itemId": 1, "jobName": "real"}]}

    assert [item.job_name for item in parse_ranking(body).items] == ["real"]


def test_an_item_without_a_rank_is_numbered_by_position() -> None:
    body = {"items": [{"itemId": 5, "jobName": "a"}, {"itemId": 6, "jobName": "b"}]}

    assert [item.rank for item in parse_ranking(body).items] == [1, 2]


def test_the_live_ranking_shape_parses_including_fields_we_ignore() -> None:
    """Recorded from the live endpoint: it also sends queueLength and unscoredItems."""
    body = dict(RANKING_BODY)
    body["queueLength"] = 2
    body["unscoredItems"] = [{"itemId": 99, "jobName": "flyweight", "reason": "node block"}]

    ranking = parse_ranking(body)

    assert ranking.available
    assert ranking.queue_length == 2


def test_an_empty_queue_parses_as_available_and_empty() -> None:
    """Distinct from unavailable: "nothing queued" and "cannot tell" are different answers."""
    ranking = parse_ranking({"configuration": {"optimizerEnabled": True}, "items": []})

    assert ranking.available
    assert ranking.queue_length == 0


def test_the_live_health_payload_parses() -> None:
    """Against the field names the plugin really sends, not the ones the prose implies."""
    health = parse_health(LIVE_HEALTH_BODY)

    assert health.available
    assert health.optimizer_enabled
    assert health.last_sort_millis == pytest.approx(2.4)
    assert health.cache_hit_rate == pytest.approx(0.82)
    assert health.heap_size == 7


def test_dropped_metrics_are_not_silently_reported_as_zero() -> None:
    """A dropped event is lost experiment data, and reporting 0 hides exactly that.

    The plugin sends ``droppedMetricCount``. Reading ``droppedMetrics`` -- which nothing sends --
    made this always 0, so an experiment could lose events with the dashboard showing none lost.
    """
    health = parse_health(LIVE_HEALTH_BODY)

    assert health.dropped_metrics == 3
    assert health.failed_metrics == 1
    assert health.pending_metrics == 2
    assert health.published_metrics == 118


def test_health_still_parses_the_names_the_spec_prose_uses() -> None:
    """4.3.10 names the fields differently; accept both rather than depend on which arrives."""
    health = parse_health({"optimizerEnabled": True, "lastSortMillis": 1.5, "droppedMetrics": 9})

    assert health.optimizer_enabled
    assert health.last_sort_millis == pytest.approx(1.5)
    assert health.dropped_metrics == 9


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_a_missing_plugin_reports_unavailable_rather_than_raising(
    settings: Settings,
) -> None:
    """jenkins-baseline runs without the plugin on purpose."""
    plugin = client_with(
        httpx.MockTransport(lambda request: httpx.Response(404, text="Not Found")), settings
    )

    ranking = await plugin.ranking()
    health = await plugin.health()

    assert not ranking.available
    assert "not installed" in (ranking.unavailable_reason or "")
    assert not health.available
    await plugin.aclose()


async def test_an_unreachable_jenkins_reports_unavailable(settings: Settings) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    plugin = client_with(httpx.MockTransport(explode), settings)

    ranking = await plugin.ranking()

    assert not ranking.available
    assert "unreachable" in (ranking.unavailable_reason or "")
    await plugin.aclose()


async def test_a_refused_token_is_reported_distinctly(settings: Settings) -> None:
    """ "The plugin is missing" and "your token is wrong" need different fixes."""
    plugin = client_with(httpx.MockTransport(lambda request: httpx.Response(403)), settings)

    ranking = await plugin.ranking()

    assert not ranking.available
    assert "refused" in (ranking.unavailable_reason or "")
    await plugin.aclose()


async def test_a_body_that_is_not_json_reports_unavailable(settings: Settings) -> None:
    plugin = client_with(
        httpx.MockTransport(lambda request: httpx.Response(200, text="<html>login</html>")),
        settings,
    )

    ranking = await plugin.ranking()

    assert not ranking.available
    assert "not JSON" in (ranking.unavailable_reason or "")
    await plugin.aclose()


async def test_concurrent_failures_do_not_report_each_others_reason(settings: Settings) -> None:
    """The reason is a return value, not instance state: one client serves every request."""
    import asyncio

    def by_path(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(403)
        return httpx.Response(404)

    plugin = client_with(httpx.MockTransport(by_path), settings)

    ranking, health = await asyncio.gather(plugin.ranking(), plugin.health())

    assert "not installed" in (ranking.unavailable_reason or "")
    assert "refused" in (health.unavailable_reason or "")
    await plugin.aclose()


# ---------------------------------------------------------------------------
# Live reads
# ---------------------------------------------------------------------------


async def test_a_successful_read_goes_through(settings: Settings) -> None:
    plugin = client_with(
        httpx.MockTransport(lambda request: httpx.Response(200, json=RANKING_BODY)), settings
    )

    ranking = await plugin.ranking()

    assert ranking.available
    assert ranking.queue_length == 2
    await plugin.aclose()


async def test_the_recent_metrics_limit_is_bounded(settings: Settings) -> None:
    """An unbounded limit would let one request pull the plugin's whole ring buffer."""
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("limit", ""))
        return httpx.Response(200, json={"events": [{"kind": "QUEUE_LEFT"}]})

    plugin = client_with(httpx.MockTransport(record), settings)

    await plugin.recent_metrics(limit=10_000)
    await plugin.recent_metrics(limit=0)

    assert seen == ["500", "1"]
    await plugin.aclose()


async def test_recent_metrics_accepts_a_bare_list(settings: Settings) -> None:
    """The endpoint may return a list or an object wrapping one; both are the same answer."""
    plugin = client_with(
        httpx.MockTransport(lambda request: httpx.Response(200, json=[{"kind": "QUEUE_LEFT"}])),
        settings,
    )

    assert len(await plugin.recent_metrics()) == 1
    await plugin.aclose()


async def test_recent_metrics_is_empty_when_unavailable(settings: Settings) -> None:
    plugin = client_with(httpx.MockTransport(lambda request: httpx.Response(404)), settings)

    assert await plugin.recent_metrics() == ()
    await plugin.aclose()


# ---------------------------------------------------------------------------
# The fake
# ---------------------------------------------------------------------------


async def test_the_fake_can_be_made_unavailable() -> None:
    """So a route can be tested for how it renders a controller without the plugin."""
    fake = FakePluginClient()
    assert (await fake.ranking()).available

    fake.set_unavailable()

    assert not (await fake.ranking()).available
    assert not (await fake.health()).available


async def test_the_fake_starts_available_and_enabled() -> None:
    fake = FakePluginClient()

    assert await fake.ranking() == Ranking(available=True, optimizer_enabled=True)
    assert await fake.health() == PluginHealth(available=True, optimizer_enabled=True)
