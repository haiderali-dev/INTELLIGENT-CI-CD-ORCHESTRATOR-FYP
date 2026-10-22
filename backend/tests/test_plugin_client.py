"""The plugin client.

The plugin may be absent -- on ``jenkins-baseline`` it deliberately is -- so the property that
matters most is that every call degrades to "unavailable" instead of raising. A queue page that
500s because the plugin is missing is worse than one that shows Jenkins' own ordering with a note.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.services.plugin import (
    FakePluginClient,
    HttpPluginClient,
    PluginHealth,
    Ranking,
    UnscoredItem,
    parse_health,
    parse_ranking,
)

PLUGIN_DATA = Path(__file__).parent / "data" / "plugin"


def recorded(name: str) -> dict[str, Any]:
    """A ranking response recorded verbatim from the live jenkins-dev (data/plugin/README.md).

    An earlier fixture here was written from 4.3.10's prose. It used flat ``urgencyFactor`` and
    ``estimateSeconds``, which the ranking endpoint never sends, and the parser passed its tests
    while reading every live factor as 0.
    """
    body: dict[str, Any] = json.loads((PLUGIN_DATA / name).read_text(encoding="utf-8"))
    return body


THREE_WAITING = "ranking-three-waiting.json"
AGED = "ranking-aged.json"
GROUP = "ranking-group.json"

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


def test_the_recorded_ranking_parses() -> None:
    ranking = parse_ranking(recorded(THREE_WAITING))

    assert ranking.available
    assert ranking.optimizer_enabled
    assert ranking.queue_length == 3
    assert ranking.weights == {"urgency": 0.5, "dependency": 0.3, "executionTime": 0.2}
    assert [item.job_name for item in ranking.items] == [
        "it-revision-freestyle",
        "it-revision-probe-freestyle",
        "it-failure-payment-service-test-unit",
    ]
    assert [item.level for item in ranking.items] == ["HIGH", "MEDIUM", "MEDIUM"]


def test_the_recorded_items_nest_their_factors_under_components() -> None:
    """The regression's cause, pinned: the live endpoint has no flat factor fields at all."""
    for item in recorded(THREE_WAITING)["items"]:
        assert set(item["components"]) == {"urgency", "dependency", "executionTime", "aging"}
        assert not {"urgencyFactor", "dependencyFactor", "executionTimeFactor", "agingBonus"} & set(
            item
        )
        assert "estimateMillis" in item
        assert "estimateSeconds" not in item


def test_factors_are_read_from_the_nested_components() -> None:
    """4.3.10 requires the components; the score bar draws them."""
    first, second, third = parse_ranking(recorded(THREE_WAITING)).items

    assert (first.components.urgency, first.components.execution_time) == (1.0, 0.855893)
    assert (second.components.urgency, second.components.execution_time) == (0.6, 0.889811)
    # The longest estimate in the queue scores 0 for execution time, and is still read as a number.
    assert (third.components.urgency, third.components.execution_time) == (0.6, 0.0)
    assert all(item.components.dependency == 0.0 for item in (first, second, third))
    assert all(item.components.aging_bonus == 0.0 for item in (first, second, third))


def test_the_estimate_is_read_from_milliseconds() -> None:
    items = parse_ranking(recorded(THREE_WAITING)).items

    assert [item.estimate_seconds for item in items] == [
        pytest.approx(3.605),
        pytest.approx(2.853),
        pytest.approx(22.581),
    ]


def test_the_score_bar_adds_up_to_the_plugins_own_score() -> None:
    """What the bar draws, weight times factor plus aging, is the score the plugin computed."""
    ranking = parse_ranking(recorded(THREE_WAITING))
    weights = ranking.weights

    for item in ranking.items:
        parts = item.components
        drawn = (
            weights["urgency"] * parts.urgency
            + weights["dependency"] * parts.dependency
            + weights["executionTime"] * parts.execution_time
        )
        assert drawn == pytest.approx(parts.base_score, abs=1e-6), item.job_name
        assert parts.own_score == pytest.approx(parts.base_score + parts.aging_bonus, abs=1e-6)
        # Nothing here belongs to a group, so nothing is inherited.
        assert item.score == pytest.approx(parts.own_score, abs=1e-6)


def test_aging_is_read_from_the_nested_components() -> None:
    """Recorded after 300.8 s in the queue: one interval, so 0.05 on top of the base."""
    (item,) = parse_ranking(recorded(AGED)).items

    assert item.wait_seconds == pytest.approx(300.755)
    assert item.components.aging_bonus == pytest.approx(0.05)
    assert item.components.base_score == pytest.approx(0.3)
    assert item.components.own_score == pytest.approx(0.35)
    assert item.score == pytest.approx(0.35)
    assert item.estimate_seconds == pytest.approx(28.418)


def test_a_group_reports_its_dependency_factor_and_order() -> None:
    first, second = parse_ranking(recorded(GROUP)).items[:2]

    assert (first.job_name, second.job_name) == ("it-revision-upstream", "it-revision-freestyle")
    assert first.group_id == second.group_id == "it-revision-upstream"
    assert (first.components.dependency, second.components.dependency) == (1.0, 1.0)
    assert (first.topological_rank, second.topological_rank) == (0, 1)


def test_an_inherited_score_is_told_apart_from_its_own() -> None:
    """Report Appendix C's case, live: the MEDIUM producer inherits its HIGH consumer's score.
    The score bar marks the inherited score with a tick; it needs both numbers to do so."""
    upstream, downstream = parse_ranking(recorded(GROUP)).items[:2]

    assert upstream.components.own_score == pytest.approx(0.8)
    assert upstream.score == pytest.approx(0.979994)
    assert upstream.score > upstream.components.own_score
    assert downstream.score == pytest.approx(downstream.components.own_score)


def test_the_score_bar_adds_up_in_every_recording() -> None:
    """Weight times factor, plus aging, is the plugin's own score for every recorded item, aged,
    grouped or neither."""
    for name in (THREE_WAITING, AGED, GROUP):
        ranking = parse_ranking(recorded(name))
        weights = ranking.weights
        for item in ranking.items:
            parts = item.components
            drawn = (
                weights["urgency"] * parts.urgency
                + weights["dependency"] * parts.dependency
                + weights["executionTime"] * parts.execution_time
                + parts.aging_bonus
            )
            assert drawn == pytest.approx(parts.own_score, abs=1e-5), (name, item.job_name)
            assert item.score >= parts.own_score - 1e-6, (name, item.job_name)


def test_unscored_items_in_a_live_response_are_kept() -> None:
    ranking = parse_ranking(recorded(GROUP))

    assert ranking.queue_length == 8
    assert len(ranking.items) == 5
    assert [item.job_name for item in ranking.unscored] == [
        "it-pipeline-create-trigger-read",
        "it-revision-pipeline",
        "it-revision-probe-pipeline",
    ]
    assert {item.reason for item in ranking.unscored} == {"not scored by the optimizer"}


def test_blocked_reasons_survive() -> None:
    items = parse_ranking(recorded(THREE_WAITING)).items

    assert {item.blocked_reason for item in items} == {"Executor slot already in use"}
    assert all(item.unresolved_dependencies == () for item in items)
    assert all(item.topological_rank == 0 for item in items)


def test_a_missing_estimate_stays_none_rather_than_zero() -> None:
    """Zero would read as "instant", which is the opposite of "not known yet". The plugin sends
    ``estimateMillis: null`` with ``estimateKnown: false`` when it has no usable history."""
    body = copy.deepcopy(recorded(THREE_WAITING))
    body["items"][0]["estimateMillis"] = None
    body["items"][0]["estimateKnown"] = False

    items = parse_ranking(body).items

    assert items[0].estimate_seconds is None
    assert items[1].estimate_seconds == pytest.approx(2.853)


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


def test_unscored_items_are_kept_and_counted() -> None:
    """The plugin lists items it could not score rather than leave queued work out; so does the
    backend. Its queueLength counts them, and so does queue_length."""
    body = copy.deepcopy(recorded(THREE_WAITING))
    body["queueLength"] = 4
    body["unscoredItems"] = [
        {"itemId": 99, "jobName": "flyweight", "reason": "not scored by the optimizer"}
    ]

    ranking = parse_ranking(body)

    assert ranking.queue_length == 4
    assert ranking.unscored == (
        UnscoredItem(item_id=99, job_name="flyweight", reason="not scored by the optimizer"),
    )


def test_without_queue_length_every_item_is_counted() -> None:
    body = copy.deepcopy(recorded(THREE_WAITING))
    del body["queueLength"]
    body["unscoredItems"] = [{"itemId": 99, "jobName": "flyweight"}]

    assert parse_ranking(body).queue_length == 4


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
    """The recorded response, served over HTTP as jenkins-dev served it, read by the real client."""
    body = recorded(THREE_WAITING)
    plugin = client_with(
        httpx.MockTransport(lambda request: httpx.Response(200, json=body)), settings
    )

    ranking = await plugin.ranking()

    assert ranking.available
    assert ranking.queue_length == 3
    assert ranking.items[0].components.execution_time == pytest.approx(0.855893)
    assert ranking.items[0].estimate_seconds == pytest.approx(3.605)
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


# ---------------------------------------------------------------------------
# Held items (found in T6.6): recorded from the live jenkins-dev on 2026-10-20
# ---------------------------------------------------------------------------

HELD = "ranking-held.json"


def test_a_job_held_for_its_upstream_is_parsed_with_the_upstream() -> None:
    """The plugin lists a job the dependency gate holds under ``heldItems``. Before, such a job was
    neither ranked nor unscored, so the queue page could not say why it waited."""
    ranking = parse_ranking(recorded(HELD))

    assert ranking.items == ()
    assert len(ranking.held) == 1
    held = ranking.held[0]
    assert held.job_name == "it-held-downstream"
    assert held.level == "HIGH"
    assert held.upstream == "it-held-upstream"
    assert held.upstream_state == "building"
    assert held.reason == "Waiting for upstream job 'it-held-upstream' (building) to finish."
    assert held.wait_seconds == pytest.approx(8.169)


def test_a_ranking_from_before_held_items_parses_with_none_held() -> None:
    """An older plugin sends no ``heldItems``: nothing is held, rather than an error."""
    for name in (THREE_WAITING, AGED, GROUP):
        assert parse_ranking(recorded(name)).held == ()
