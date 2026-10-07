"""Client for the plugin's own endpoints.

BUILD_PROMPT 4.3.10 gives the plugin three endpoints under ``/dynamic-queue``, all requiring
``Jenkins.READ``. This client reads them with the bot token, exactly as ``JenkinsClient`` does.

The ranking endpoint is the only place the backend can see *why* the queue is ordered the way it
is: the score components, the group id, the topological rank and the blocked reason are computed in
the plugin and are not derivable from Jenkins' own queue API. The analytics and queue pages are
built on it.

Degradation is the design point. The plugin may be absent -- on ``jenkins-baseline`` it deliberately
is -- so every call here returns an "unavailable" result rather than raising, and the queue page
renders Jenkins' own ordering with a note. A 404 from the plugin is a fact about the environment,
not an error in the request that asked.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)

TIMEOUT_SECONDS: Final = 5.0

# Shorter than JenkinsClient's ten seconds, and not retried. This is decoration on a page that has
# already loaded; a slow answer must not hold the request open while a user waits.
BASE_PATH: Final = "dynamic-queue"

MAX_RECENT: Final = 500


@dataclass(frozen=True)
class ScoreComponents:
    """Algorithm 1 broken out, as 4.3.10 requires the endpoint to report it."""

    urgency: float = 0.0
    dependency: float = 0.0
    execution_time: float = 0.0
    aging_bonus: float = 0.0
    base_score: float = 0.0


@dataclass(frozen=True)
class RankedItem:
    """One buildable queue item, as the plugin ranks it."""

    rank: int
    item_id: int
    job_name: str
    job_type: str = "unknown"
    level: str = "MEDIUM"
    score: float = 0.0
    components: ScoreComponents = field(default_factory=ScoreComponents)
    estimate_seconds: float | None = None
    wait_seconds: float = 0.0
    group_id: str | None = None
    topological_rank: int | None = None
    blocked_reason: str | None = None
    unresolved_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ranking:
    """The plugin's view of the queue, or a note saying it could not be read.

    ``available`` is false when the plugin is absent or unreachable. Callers render the items they
    have and say so; they must not treat an empty ranking as an empty queue.
    """

    available: bool
    items: tuple[RankedItem, ...] = ()
    weights: dict[str, float] = field(default_factory=dict)
    optimizer_enabled: bool = False
    unavailable_reason: str | None = None

    @property
    def queue_length(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class PluginHealth:
    """``GET /dynamic-queue/health``: 4.3.10's four fields, plus the publisher's counters.

    The counters are not in 4.3.10's list but the live endpoint reports them, and they answer the
    one question an experiment needs answered while it is running: is the metrics pipeline
    actually delivering? A dropped event is lost experiment data, and it is unrecoverable
    afterwards.
    """

    available: bool
    optimizer_enabled: bool = False
    last_sort_millis: float | None = None
    cache_hit_rate: float | None = None
    dropped_metrics: int = 0
    published_metrics: int = 0
    failed_metrics: int = 0
    pending_metrics: int = 0
    heap_size: int = 0
    unavailable_reason: str | None = None


class PluginClient(ABC):
    """What the backend reads from the plugin."""

    @abstractmethod
    async def ranking(self) -> Ranking:
        """The current queue ranking. Never raises; reports unavailability instead."""

    @abstractmethod
    async def health(self) -> PluginHealth:
        """The plugin's health. Never raises."""

    @abstractmethod
    async def recent_metrics(self, limit: int = 50) -> tuple[dict[str, Any], ...]:
        """The last N events the plugin recorded. Empty when unavailable."""

    async def aclose(self) -> None:
        return None


class HttpPluginClient(PluginClient):
    """Reads the live plugin over HTTP with the bot token."""

    def __init__(self, settings: Settings) -> None:
        self._base = str(settings.jenkins_url).rstrip("/")
        self._auth = (settings.jenkins_user, settings.jenkins_token)
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base, auth=self._auth, timeout=TIMEOUT_SECONDS
            )
        return self._client

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[Any | None, str | None]:
        """GET and parse JSON. Returns ``(body, None)`` or ``(None, reason)``.

        The reason is returned rather than stored on the instance. One client serves every
        request, so a shared attribute would let two concurrent calls report each other's failure.

        Every failure mode collapses to a reason string on purpose: a missing plugin, an
        unreachable Jenkins and a malformed body are all "the ranking cannot be read right now",
        and the caller's response to each is the same.
        """
        try:
            response = await self._http().get(path, params=params)
        except httpx.HTTPError as exc:
            logger.info("plugin_unreachable", path=path, error=type(exc).__name__)
            return None, f"jenkins unreachable: {type(exc).__name__}"

        if response.status_code == 404:
            return None, "the plugin is not installed on this controller"
        if response.status_code in (401, 403):
            logger.warning("plugin_auth_refused", path=path, status=response.status_code)
            return None, f"the bot token was refused ({response.status_code})"
        if response.status_code >= 400:
            logger.warning("plugin_error_status", path=path, status=response.status_code)
            return None, f"the plugin returned {response.status_code}"

        try:
            return response.json(), None
        except ValueError:
            logger.warning("plugin_bad_body", path=path)
            return None, "the plugin returned a body that is not JSON"

    async def ranking(self) -> Ranking:
        body, reason = await self._get(f"/{BASE_PATH}/api/json")
        if not isinstance(body, dict):
            return Ranking(available=False, unavailable_reason=reason)
        return parse_ranking(body)

    async def health(self) -> PluginHealth:
        body, reason = await self._get(f"/{BASE_PATH}/health")
        if not isinstance(body, dict):
            return PluginHealth(available=False, unavailable_reason=reason)
        return parse_health(body)

    async def recent_metrics(self, limit: int = 50) -> tuple[dict[str, Any], ...]:
        bounded = max(1, min(limit, MAX_RECENT))
        body, _ = await self._get(f"/{BASE_PATH}/metrics/recent", {"limit": bounded})
        events = body.get("events") if isinstance(body, dict) else body
        if not isinstance(events, list):
            return ()
        return tuple(event for event in events if isinstance(event, dict))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _number(value: Any, default: float = 0.0) -> float:
    """Coerce leniently.

    The plugin and the backend are versioned separately, so a field that arrives as a string, or
    not at all, must not lose the whole ranking. One bad field costs its own value, nothing more.
    """
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_number(value: Any) -> float | None:
    return None if value is None else _number(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_ranking(body: dict[str, Any]) -> Ranking:
    """Build a ``Ranking`` from the endpoint's body.

    Separate from the client so the parser can be tested against recorded payloads, and so a
    payload captured from the live plugin can be replayed in a unit test.
    """
    raw_items = body.get("items")
    items: list[RankedItem] = []
    for index, entry in enumerate(raw_items if isinstance(raw_items, list) else []):
        if not isinstance(entry, dict):
            continue
        dependencies = entry.get("unresolvedDependencies") or entry.get("unresolved") or []
        items.append(
            RankedItem(
                rank=_optional_int(entry.get("rank")) or index + 1,
                item_id=_optional_int(entry.get("itemId")) or 0,
                job_name=str(entry.get("jobName", "")),
                job_type=str(entry.get("jobType", "unknown")),
                level=str(entry.get("level", "MEDIUM")),
                score=_number(entry.get("score")),
                components=ScoreComponents(
                    urgency=_number(entry.get("urgencyFactor")),
                    dependency=_number(entry.get("dependencyFactor")),
                    execution_time=_number(entry.get("executionTimeFactor")),
                    aging_bonus=_number(entry.get("agingBonus")),
                    base_score=_number(entry.get("baseScore")),
                ),
                estimate_seconds=_optional_number(entry.get("estimateSeconds")),
                wait_seconds=_number(entry.get("waitSeconds")),
                group_id=entry.get("groupId") or None,
                topological_rank=_optional_int(entry.get("topologicalRank")),
                blocked_reason=entry.get("blockedReason") or None,
                unresolved_dependencies=tuple(str(name) for name in dependencies),
            )
        )

    configuration = body.get("configuration")
    configuration = configuration if isinstance(configuration, dict) else body
    weights = {
        "urgency": _number(configuration.get("weightUrgency")),
        "dependency": _number(configuration.get("weightDependency")),
        "executionTime": _number(configuration.get("weightExecutionTime")),
    }

    return Ranking(
        available=True,
        items=tuple(items),
        weights=weights,
        optimizer_enabled=bool(configuration.get("optimizerEnabled", False)),
    )


def _first(body: dict[str, Any], *names: str) -> Any:
    """The first of several field names that is present.

    The plugin's own names are listed first and come from a recorded live response, not from the
    specification's prose. Earlier guesses here read ``droppedMetrics`` where the endpoint sends
    ``droppedMetricCount``, so the backend reported zero dropped events however many were lost --
    the one number whose whole purpose is to say that data went missing.
    """
    for name in names:
        if name in body:
            return body[name]
    return None


def parse_health(body: dict[str, Any]) -> PluginHealth:
    return PluginHealth(
        available=True,
        optimizer_enabled=bool(_first(body, "enabled", "optimizerEnabled") or False),
        last_sort_millis=_optional_number(_first(body, "lastSortDurationMillis", "lastSortMillis")),
        cache_hit_rate=_optional_number(body.get("cacheHitRate")),
        dropped_metrics=_optional_int(_first(body, "droppedMetricCount", "droppedMetrics")) or 0,
        published_metrics=_optional_int(_first(body, "publishedMetricCount")) or 0,
        failed_metrics=_optional_int(_first(body, "failedMetricCount")) or 0,
        pending_metrics=_optional_int(_first(body, "pendingMetricCount")) or 0,
        heap_size=_optional_int(_first(body, "heapSize")) or 0,
    )


class FakePluginClient(PluginClient):
    """An in-memory plugin. The default in tests."""

    def __init__(self) -> None:
        self.ranking_result = Ranking(available=True, optimizer_enabled=True)
        self.health_result = PluginHealth(available=True, optimizer_enabled=True)
        self.events: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def set_unavailable(self, reason: str = "the plugin is not installed") -> None:
        """Make every call report unavailability, as on ``jenkins-baseline``."""
        self.ranking_result = Ranking(available=False, unavailable_reason=reason)
        self.health_result = PluginHealth(available=False, unavailable_reason=reason)

    async def ranking(self) -> Ranking:
        self.calls.append("ranking")
        return self.ranking_result

    async def health(self) -> PluginHealth:
        self.calls.append("health")
        return self.health_result

    async def recent_metrics(self, limit: int = 50) -> tuple[dict[str, Any], ...]:
        self.calls.append("recent_metrics")
        return tuple(self.events[-limit:])
