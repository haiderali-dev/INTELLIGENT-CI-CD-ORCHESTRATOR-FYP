"""The WebSocket hub.

BUILD_PROMPT 4.4.4 lists ``WS /ws``, and 4.4.5 says ``RunTracker`` "publishes WebSocket events".
This module is the fan-out between them: the tracker calls ``publish`` and never learns who is
listening or how slowly.

Two properties shape the design.

**Publishing must never block.** The tracker runs on a three-second tick and also writes to the
database; if a browser on a bad connection could apply backpressure to it, one slow client would
stall tracking for everyone. Each connection therefore has its own bounded queue, and a queue that
is full drops its oldest event rather than waiting. A client that cannot keep up loses
intermediate states, which is the right trade for a live view: the next event carries the current
state anyway.

**A disconnect is normal, not an error.** Browsers close sockets on navigation, sleep and tab
discard, constantly. Nothing here logs a closed connection above debug, and no publish path can
raise because a client went away mid-send.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from app.core.logging import get_logger

logger = get_logger(__name__)

# Per-connection buffer. Deep enough to absorb a burst -- a queue of thirty jobs draining produces
# a few hundred events in a second -- and shallow enough that a dead client is noticed quickly.
QUEUE_CAPACITY: Final = 256

# How long a connection has to authenticate before it is closed.
AUTH_TIMEOUT_SECONDS: Final = 10.0

# Sent to idle connections so that a proxy or load balancer does not reap a quiet socket, and so
# the client can tell "nothing is happening" from "the connection is gone".
HEARTBEAT_SECONDS: Final = 25.0


class Topic(StrEnum):
    """What a client can subscribe to.

    Topics rather than one firehose: the Queue page needs queue events and the Runs page needs run
    events, and sending each page everything would mean every browser re-rendering on every event
    in the system.
    """

    RUNS = "runs"
    QUEUE = "queue"
    NOTIFICATIONS = "notifications"
    SYSTEM = "system"


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    RUN_UPDATED = "run.updated"
    RUN_FINISHED = "run.finished"
    RUN_QUEUED = "run.queued"
    QUEUE_CHANGED = "queue.changed"
    NOTIFICATION = "notification"
    HELLO = "hello"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


TOPIC_FOR_EVENT: Final[dict[EventType, Topic]] = {
    EventType.RUN_STARTED: Topic.RUNS,
    EventType.RUN_UPDATED: Topic.RUNS,
    EventType.RUN_FINISHED: Topic.RUNS,
    EventType.RUN_QUEUED: Topic.RUNS,
    EventType.QUEUE_CHANGED: Topic.QUEUE,
    EventType.NOTIFICATION: Topic.NOTIFICATIONS,
    EventType.HELLO: Topic.SYSTEM,
    EventType.HEARTBEAT: Topic.SYSTEM,
    EventType.ERROR: Topic.SYSTEM,
}


@dataclass(frozen=True)
class Event:
    """One message to the browser.

    ``type`` and ``data`` rather than a bare payload, so the frontend switches on one field and a
    new event type does not need a new socket or a new parser.
    """

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def topic(self) -> Topic:
        return TOPIC_FOR_EVENT.get(self.type, Topic.SYSTEM)

    def to_json(self) -> str:
        return json.dumps(
            {"type": str(self.type), "sentAt": self.sent_at.isoformat(), "data": self.data},
            default=str,
        )


@dataclass
class Subscriber:
    """One connected client.

    ``user_id`` is held so a future per-user topic can filter without a second lookup, and so a
    disconnect can be logged against a person rather than an anonymous socket.
    """

    id: str
    user_id: str
    topics: set[Topic]
    queue: asyncio.Queue[Event | None]
    dropped: int = 0

    def wants(self, event: Event) -> bool:
        return event.topic in self.topics


class Hub:
    """Fan-out to the connected clients.

    Deliberately in-process, like the rate limiter (D-020) and the revocation list (D-021). With
    more than one backend instance a client would only see events produced by the instance it
    happens to be connected to; the project runs one.
    """

    def __init__(self, *, capacity: int = QUEUE_CAPACITY) -> None:
        self._subscribers: dict[str, Subscriber] = {}
        self._capacity = capacity
        self._lock = asyncio.Lock()
        self._published = 0
        self._dropped = 0

    async def subscribe(self, subscriber_id: str, user_id: str, topics: set[Topic]) -> Subscriber:
        subscriber = Subscriber(
            id=subscriber_id,
            user_id=user_id,
            topics=topics or {Topic.RUNS, Topic.QUEUE, Topic.NOTIFICATIONS, Topic.SYSTEM},
            queue=asyncio.Queue(maxsize=self._capacity),
        )
        async with self._lock:
            self._subscribers[subscriber_id] = subscriber
        logger.info(
            "ws_subscribed",
            subscriber=subscriber_id,
            user_id=user_id,
            topics=sorted(str(topic) for topic in subscriber.topics),
            total=len(self._subscribers),
        )
        return subscriber

    async def unsubscribe(self, subscriber_id: str) -> None:
        async with self._lock:
            subscriber = self._subscribers.pop(subscriber_id, None)
        if subscriber is None:
            return
        # Wake the sender so it can exit rather than waiting on a queue nobody will fill.
        with contextlib.suppress(asyncio.QueueFull):
            subscriber.queue.put_nowait(None)
        logger.info(
            "ws_unsubscribed",
            subscriber=subscriber_id,
            dropped=subscriber.dropped,
            total=len(self._subscribers),
        )

    def publish(self, event: Event) -> int:
        """Queue an event for every interested subscriber. Returns how many received it.

        Synchronous and non-blocking on purpose: the tracker calls this from inside its tick, and
        an ``await`` that could suspend on a slow client would make tracking as slow as the
        slowest browser. No lock either -- a dict snapshot is enough, and taking the lock here
        would reintroduce exactly the contention this avoids.
        """
        delivered = 0
        for subscriber in list(self._subscribers.values()):
            if not subscriber.wants(event):
                continue
            try:
                subscriber.queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Drop the oldest and take the newest: for a live view the latest state is worth
                # more than a complete history, and the alternative is unbounded memory.
                with contextlib.suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    subscriber.queue.put_nowait(event)
                subscriber.dropped += 1
                self._dropped += 1
                if subscriber.dropped in (1, 10, 100) or subscriber.dropped % 1000 == 0:
                    logger.warning(
                        "ws_subscriber_slow",
                        subscriber=subscriber.id,
                        dropped=subscriber.dropped,
                    )
        self._published += 1
        return delivered

    async def close(self) -> None:
        """Signal every sender to finish. Used on shutdown."""
        async with self._lock:
            subscribers = list(self._subscribers.values())
            self._subscribers.clear()
        for subscriber in subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(None)

    # --- Introspection, for /api/health and tests -------------------------

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "subscribers": len(self._subscribers),
            "published": self._published,
            "dropped": self._dropped,
        }


_hub = Hub()


def get_hub() -> Hub:
    """The process-wide hub, as a provider so tests can substitute one."""
    return _hub


def set_hub(hub: Hub | None) -> None:
    """Install a hub, or restore the default. Used by tests."""
    global _hub
    _hub = hub if hub is not None else Hub()
