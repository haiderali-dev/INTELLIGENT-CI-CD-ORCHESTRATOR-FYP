"""The WebSocket hub and ``WS /ws``.

Two properties carry most of the weight. First, the token never travels in the URL: a browser
cannot set headers on a WebSocket, and the usual ``?token=`` workaround writes the access token
into proxy access logs, browser history and any ``Referer`` sent onward. Second, one slow client
cannot slow anything down — the tracker publishes from inside its tick, so backpressure from a
browser would become backpressure on recording run history.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from app.core.security import hash_password
from app.core.settings import Settings, get_settings
from app.db.models import Role, User
from app.ws.hub import (
    TOPIC_FOR_EVENT,
    Event,
    EventType,
    Hub,
    Subscriber,
    Topic,
    get_hub,
    set_hub,
)

PASSWORD = "correct-horse-battery-staple"
EMAIL = "ws@example.com"


# ---------------------------------------------------------------------------
# The hub
# ---------------------------------------------------------------------------


async def subscriber_of(hub: Hub, topics: set[Topic] | None = None) -> Subscriber:
    return await hub.subscribe("s1", "user-1", topics or {Topic.RUNS})


async def test_an_event_reaches_a_subscriber_of_its_topic() -> None:
    hub = Hub()
    subscriber = await subscriber_of(hub, {Topic.RUNS})

    delivered = hub.publish(Event(type=EventType.RUN_STARTED, data={"runId": "r1"}))

    assert delivered == 1
    event = subscriber.queue.get_nowait()
    assert event is not None
    assert event.type is EventType.RUN_STARTED


async def test_an_event_does_not_reach_other_topics() -> None:
    """The Queue page should not re-render on every run event in the system."""
    hub = Hub()
    subscriber = await subscriber_of(hub, {Topic.QUEUE})

    delivered = hub.publish(Event(type=EventType.RUN_STARTED))

    assert delivered == 0
    assert subscriber.queue.empty()


async def test_publishing_with_no_subscribers_is_harmless() -> None:
    """The tracker runs whether or not anyone is watching."""
    assert Hub().publish(Event(type=EventType.RUN_FINISHED)) == 0


async def test_a_slow_subscriber_drops_its_oldest_event() -> None:
    """A live view wants the newest state; the alternative is unbounded memory."""
    hub = Hub(capacity=2)
    subscriber = await subscriber_of(hub)

    for index in range(5):
        hub.publish(Event(type=EventType.RUN_UPDATED, data={"n": index}))

    assert subscriber.queue.qsize() == 2
    assert subscriber.dropped == 3
    kept = [subscriber.queue.get_nowait(), subscriber.queue.get_nowait()]
    assert [event.data["n"] for event in kept if event is not None] == [3, 4]


async def test_publishing_never_blocks_on_a_full_subscriber() -> None:
    """``publish`` is called from inside the tracker's tick and must stay synchronous.

    If it could block, this test would hang rather than fail, which is itself the signal.
    """
    hub = Hub(capacity=1)
    await subscriber_of(hub)

    for _ in range(100):
        hub.publish(Event(type=EventType.RUN_UPDATED))

    assert hub.stats["dropped"] == 99


async def test_unsubscribing_wakes_the_sender() -> None:
    """Otherwise a disconnected client's task waits forever on a queue nobody will fill."""
    hub = Hub()
    subscriber = await subscriber_of(hub)

    await hub.unsubscribe("s1")

    assert subscriber.queue.get_nowait() is None
    assert hub.subscriber_count == 0


async def test_unsubscribing_twice_is_not_an_error() -> None:
    """Both the sender and the endpoint's finally block may unsubscribe one connection."""
    hub = Hub()
    await subscriber_of(hub)

    await hub.unsubscribe("s1")
    await hub.unsubscribe("s1")

    assert hub.subscriber_count == 0


async def test_closing_the_hub_signals_every_subscriber() -> None:
    hub = Hub()
    first = await hub.subscribe("a", "u", {Topic.RUNS})
    second = await hub.subscribe("b", "u", {Topic.QUEUE})

    await hub.close()

    assert first.queue.get_nowait() is None
    assert second.queue.get_nowait() is None
    assert hub.subscriber_count == 0


def test_an_event_serialises_with_a_type_and_a_timestamp() -> None:
    """The frontend switches on one field, so a new event type needs no new parser."""
    payload = json.loads(Event(type=EventType.RUN_FINISHED, data={"runId": "r1"}).to_json())

    assert payload["type"] == "run.finished"
    assert payload["data"] == {"runId": "r1"}
    assert payload["sentAt"]


def test_every_event_type_has_a_topic() -> None:
    """An unmapped event would fall into SYSTEM and quietly reach the wrong page."""
    assert set(TOPIC_FOR_EVENT) == set(EventType)


# ---------------------------------------------------------------------------
# WS /ws
# ---------------------------------------------------------------------------
#
# These tests are synchronous, because Starlette's WebSocket test support is, and ``TestClient``
# runs its own event loop. They therefore use a *file-backed* SQLite database in ``tmp_path``
# rather than the suite's shared in-memory one: an in-memory SQLite lives on a single pooled
# connection bound to the loop that opened it, so seeding from one loop and reading from
# TestClient's would fail on the loop boundary rather than on anything these tests are about.


@pytest.fixture
def ws_app(tmp_path: Path) -> Generator[FastAPI]:
    """An app on a file-backed database, usable from TestClient's own loop."""
    from app.core.settings import Environment, LlmMode
    from app.db import session as db_session
    from app.db.base import Base
    from app.main import create_app
    from app.services.dependencies import get_jenkins_client, get_settings_dep
    from app.services.jenkins import FakeJenkinsClient

    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/ws.db"
    settings = Settings(
        environment=Environment.TEST,
        database_url=url,
        llm_mode=LlmMode.FAKE,
        jenkins_url="http://jenkins-dev:8080",
        jenkins_user="orchestrator-bot",
        jenkins_token="test-token",
    )

    async def prepare() -> None:
        engine = create_async_engine(url, connect_args={"check_same_thread": False})
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            session.add(
                User(
                    email=EMAIL,
                    password_hash=hash_password(PASSWORD),
                    role=Role.DEVELOPER.value,
                    active=True,
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(prepare())

    db_session.configure(create_async_engine(url, connect_args={"check_same_thread": False}))
    get_settings.cache_clear()
    application = create_app(settings)
    application.dependency_overrides[get_settings_dep] = lambda: settings
    application.dependency_overrides[get_jenkins_client] = lambda: FakeJenkinsClient()

    yield application

    application.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def ws_client(ws_app: FastAPI) -> Generator[TestClient]:
    with TestClient(ws_app) as client:
        yield client


@pytest.fixture
def ws_hub() -> Generator[Hub]:
    """A hub of this test's own, so published events cannot leak between tests."""
    hub = Hub()
    set_hub(hub)
    yield hub
    set_hub(None)


def sign_in(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def test_the_socket_refuses_a_first_frame_that_is_not_auth(ws_client: TestClient) -> None:
    """Nothing is delivered before the token arrives."""
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "subscribe", "topics": ["runs"]}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_a_bad_token_is_closed_with_a_policy_code(ws_client: TestClient) -> None:
    """1008 tells the client to sign in again rather than retry forever."""
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": "not-a-real-token"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_the_close_reason_does_not_say_why_the_token_failed(ws_client: TestClient) -> None:
    """Expired and forged are the same instruction to the client: sign in again.

    Distinguishing them over an unauthenticated socket would say which tokens are real.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": "not-a-real-token"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.reason == "not authenticated"


def test_a_frame_that_is_not_json_is_refused(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text("<html>")
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_an_oversized_auth_frame_is_refused(ws_client: TestClient) -> None:
    """A token is long; twenty kilobytes is not an auth attempt."""
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": "x" * 20_000}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_an_auth_frame_without_a_token_is_refused(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_a_token_in_the_query_string_is_not_accepted(ws_client: TestClient) -> None:
    """The deliberate design choice, asserted so the reason cannot be quietly forgotten.

    A query string reaches proxy access logs, browser history and any Referer sent onward. If this
    test ever starts failing, the token has been moved into the URL.
    """
    with ws_client.websocket_connect("/ws?token=anything") as socket:
        socket.send_text(json.dumps({"type": "ping"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


def test_a_valid_token_gets_a_hello_then_its_events(ws_client: TestClient, ws_hub: Hub) -> None:
    """The full handshake, then a published event arrives."""
    token = sign_in(ws_client)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token, "topics": ["runs"]}))
        hello = json.loads(socket.receive_text())
        assert hello["type"] == "hello"
        assert hello["data"]["topics"] == ["runs"]
        assert hello["data"]["heartbeatSeconds"] > 0

        ws_hub.publish(Event(type=EventType.RUN_STARTED, data={"runId": "r9"}))
        event = json.loads(socket.receive_text())

    assert event["type"] == "run.started"
    assert event["data"]["runId"] == "r9"


def test_a_client_only_receives_the_topics_it_asked_for(ws_client: TestClient, ws_hub: Hub) -> None:
    token = sign_in(ws_client)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token, "topics": ["queue"]}))
        socket.receive_text()  # hello

        ws_hub.publish(Event(type=EventType.RUN_STARTED, data={"runId": "ignored"}))
        ws_hub.publish(Event(type=EventType.QUEUE_CHANGED, data={"resolved": 1}))
        event = json.loads(socket.receive_text())

    assert event["type"] == "queue.changed"


def test_unknown_topics_are_ignored_rather_than_refused(ws_client: TestClient) -> None:
    """A frontend newer than the backend should get the events that do exist."""
    token = sign_in(ws_client)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(
            json.dumps({"type": "auth", "token": token, "topics": ["runs", "telepathy"]})
        )
        hello = json.loads(socket.receive_text())

    assert hello["data"]["topics"] == ["runs"]


def test_no_topics_means_every_topic(ws_client: TestClient) -> None:
    token = sign_in(ws_client)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token}))
        hello = json.loads(socket.receive_text())

    assert set(hello["data"]["topics"]) == {str(topic) for topic in Topic}


def test_a_disconnect_removes_the_subscriber(ws_client: TestClient, ws_hub: Hub) -> None:
    """Browsers close sockets on navigation, sleep and tab discard, constantly."""
    token = sign_in(ws_client)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token}))
        socket.receive_text()
        assert ws_hub.subscriber_count == 1

    for _ in range(100):
        if ws_hub.subscriber_count == 0:
            break
        time.sleep(0.02)

    assert ws_hub.subscriber_count == 0


def test_a_deactivated_user_cannot_open_a_socket(ws_client: TestClient) -> None:
    """An access token stays valid for fifteen minutes; deactivation must end the live feed too."""
    token = sign_in(ws_client)

    response = ws_client.patch(
        "/api/_test/deactivate", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    # No admin router yet (T3.8), so deactivate through the app's own engine instead.
    assert response.status_code in (404, 405)

    from sqlalchemy import update

    from app.db import session as db_session

    async def deactivate() -> None:
        factory = db_session.get_session_factory()
        async with factory() as session:
            await session.execute(update(User).where(User.email == EMAIL).values(active=False))
            await session.commit()

    ws_client.portal.call(deactivate)

    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token}))
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_text()

    assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Topic parsing
# ---------------------------------------------------------------------------


def test_topic_parsing_accepts_known_names() -> None:
    from app.ws.routes import _parse_topics

    assert _parse_topics(["runs", "queue"]) == {Topic.RUNS, Topic.QUEUE}


def test_topic_parsing_falls_back_to_everything() -> None:
    """Anything unusable means "send me what you have", never "send me nothing"."""
    from app.ws.routes import _parse_topics

    assert _parse_topics(None) == set(Topic)
    assert _parse_topics("runs") == set(Topic)
    assert _parse_topics([]) == set(Topic)
    assert _parse_topics(["nonsense"]) == set(Topic)


# ---------------------------------------------------------------------------
# The default hub provider
# ---------------------------------------------------------------------------


def test_the_hub_provider_returns_one_instance() -> None:
    assert get_hub() is get_hub()


def test_setting_the_hub_to_none_restores_a_fresh_one() -> None:
    replacement = Hub()
    set_hub(replacement)
    assert get_hub() is replacement

    set_hub(None)

    assert get_hub() is not replacement
