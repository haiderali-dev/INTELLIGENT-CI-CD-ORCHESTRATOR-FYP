"""``WS /ws``.

BUILD_PROMPT 4.4.4 lists the endpoint; how it authenticates is not specified, and the choice
matters because **a browser cannot set headers on a WebSocket**. The usual workaround is
``/ws?token=...``, which this deliberately does not do: a query string reaches proxy access logs,
browser history and any ``Referer`` sent onward, so the access token would end up written down in
several places nobody audits.

Instead the socket is accepted and then has ``AUTH_TIMEOUT_SECONDS`` to send one frame:

    {"type": "auth", "token": "<access token>", "topics": ["runs", "queue"]}

Nothing is delivered before that frame arrives. An unauthenticated socket can therefore do exactly
one thing -- authenticate -- and it is closed if it does anything else or waits too long. The cost
is one extra ``send`` in the frontend hook; the benefit is that the token stays in the message body
where it belongs.

Close codes are chosen so the client can tell a retry from a dead end: 1008 (policy violation) for
a bad or missing token, which means stop and sign in again, and 1011 for an internal fault, which
means retry with backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.errors import ApiError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.session import get_session_factory
from app.services.auth import load_user_from_access_token
from app.services.dependencies import get_settings_dep
from app.ws.hub import (
    AUTH_TIMEOUT_SECONDS,
    HEARTBEAT_SECONDS,
    Event,
    EventType,
    Subscriber,
    Topic,
    get_hub,
)

logger = get_logger(__name__)
router = APIRouter()

CLOSE_POLICY: Final = 1008
CLOSE_INTERNAL: Final = 1011

# A token is long; a frame far bigger than that is not an auth attempt.
MAX_AUTH_FRAME_BYTES: Final = 8192


def _parse_topics(raw: Any) -> set[Topic]:
    """Read the requested topics, ignoring ones this server does not have.

    An unknown topic is dropped rather than refused: a frontend newer than the backend should get
    the events that do exist instead of no connection at all.
    """
    if not isinstance(raw, list):
        return set(Topic)
    wanted = {str(name) for name in raw}
    known = {topic for topic in Topic if str(topic) in wanted}
    return known or set(Topic)


async def _authenticate(websocket: WebSocket, settings: Settings) -> tuple[str, set[Topic]] | None:
    """Wait for the auth frame. Returns ``(user_id, topics)``, or None after closing the socket."""
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await _close(websocket, CLOSE_POLICY, "no auth frame")
        return None
    except (WebSocketDisconnect, RuntimeError):
        return None

    if len(raw) > MAX_AUTH_FRAME_BYTES:
        await _close(websocket, CLOSE_POLICY, "auth frame too large")
        return None

    try:
        frame = json.loads(raw)
    except ValueError:
        await _close(websocket, CLOSE_POLICY, "auth frame is not JSON")
        return None

    if not isinstance(frame, dict) or frame.get("type") != "auth":
        await _close(websocket, CLOSE_POLICY, "first frame must be an auth frame")
        return None

    token = frame.get("token")
    if not isinstance(token, str) or not token:
        await _close(websocket, CLOSE_POLICY, "no token")
        return None

    # A fresh session: the socket outlives any request, so it must not borrow a request's session.
    factory = get_session_factory()
    try:
        async with factory() as session:
            user = await load_user_from_access_token(session, settings, token)
    except ApiError as exc:
        # The specific reason is logged, not sent. "Your token expired" and "no such user" are the
        # same instruction to the client -- sign in again -- and distinguishing them over an
        # unauthenticated socket tells an attacker which tokens are real.
        logger.info("ws_auth_refused", code=str(exc.code))
        await _close(websocket, CLOSE_POLICY, "not authenticated")
        return None
    except Exception:
        logger.exception("ws_auth_failed")
        await _close(websocket, CLOSE_INTERNAL, "internal error")
        return None

    return user.id, _parse_topics(frame.get("topics"))


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    """Close once, tolerating a socket the client already dropped."""
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=code, reason=reason)


async def _drain_incoming(websocket: WebSocket) -> None:
    """Read and discard client frames until it disconnects.

    The protocol is server-to-client after authentication, but the socket still has to be read:
    without a reader, a client's close frame is never noticed and the connection leaks until the
    heartbeat happens to fail.
    """
    while True:
        await websocket.receive_text()


async def _send_events(websocket: WebSocket, subscriber: Subscriber) -> None:
    """Forward queued events, with a heartbeat while idle."""
    while True:
        try:
            event = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            await websocket.send_text(Event(type=EventType.HEARTBEAT).to_json())
            continue
        if event is None:  # the hub is shutting this subscriber down
            return
        await websocket.send_text(event.to_json())


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> None:
    """Live events for the signed-in user.

    The connection is accepted before authentication so that a refusal can be reported as a close
    code the browser can read. Rejecting the handshake outright gives the client only an opaque
    failure, indistinguishable from the server being down.

    Settings arrive through ``Depends`` rather than by calling the provider here: FastAPI supports
    dependencies on WebSocket routes, and calling the provider directly would bypass
    ``dependency_overrides`` -- which it did, falling back to a bare ``Settings()`` that fails
    validation outside a configured environment.
    """
    await websocket.accept()
    hub = get_hub()

    authenticated = await _authenticate(websocket, settings)
    if authenticated is None:
        return
    user_id, topics = authenticated

    subscriber_id = uuid.uuid4().hex
    subscriber = await hub.subscribe(subscriber_id, user_id, topics)

    try:
        await websocket.send_text(
            Event(
                type=EventType.HELLO,
                data={
                    "subscriberId": subscriber_id,
                    "topics": sorted(str(topic) for topic in topics),
                    "heartbeatSeconds": HEARTBEAT_SECONDS,
                },
            ).to_json()
        )

        # Whichever finishes first ends the connection: the reader returns when the client goes
        # away, the sender when the hub shuts the subscriber down or the socket breaks.
        reader = asyncio.create_task(_drain_incoming(websocket))
        sender = asyncio.create_task(_send_events(websocket, subscriber))
        done, pending = await asyncio.wait({reader, sender}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            # Surface a genuine fault; a disconnect is not one.
            with contextlib.suppress(WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                task.result()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_connection_failed", subscriber=subscriber_id)
        await _close(websocket, CLOSE_INTERNAL, "internal error")
    finally:
        await hub.unsubscribe(subscriber_id)
