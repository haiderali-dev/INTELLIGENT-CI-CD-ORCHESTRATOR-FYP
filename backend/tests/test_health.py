"""Health endpoint behaviour.

Phase 3's acceptance is that ``GET /api/health`` reports database, Jenkins and LLM provider. These
tests cover the shape and, more importantly, what happens when a dependency is down: a health
endpoint that only works while everything is healthy is not a health endpoint.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.health import ComponentStatus
from app.services.jenkins import FakeJenkinsClient, JenkinsError


async def test_liveness_has_no_dependencies(client: AsyncClient) -> None:
    """Liveness must not touch the database or Jenkins.

    It exists so an orchestrator does not restart a healthy backend during a brief PostgreSQL
    outage, which it would do if liveness and readiness were the same endpoint.
    """
    response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_all_three_components(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ComponentStatus.UP.value
    # The three Phase 3 acceptance names exactly.
    assert set(body["components"]) == {"database", "jenkins", "llm"}
    assert body["components"]["database"]["status"] == ComponentStatus.UP.value
    assert body["components"]["jenkins"]["status"] == ComponentStatus.UP.value


async def test_health_reports_the_jenkins_version(client: AsyncClient) -> None:
    body = (await client.get("/api/health")).json()

    assert "2.568.3" in body["components"]["jenkins"]["detail"], (
        "the pinned LTS should be visible, so a version mismatch is diagnosable from health alone"
    )


async def test_llm_is_disabled_not_down_in_fake_mode(client: AsyncClient) -> None:
    """A deliberately unused dependency must not look like a failure.

    Every test and the whole demo run in fake or replay mode. If that reported as ``down``, the
    health endpoint would be red for the system's normal operating state.
    """
    body = (await client.get("/api/health")).json()

    assert body["components"]["llm"]["status"] == ComponentStatus.DISABLED.value
    assert body["status"] == ComponentStatus.UP.value


async def test_health_does_not_call_the_model(client: AsyncClient) -> None:
    """The probe reports configuration, it does not spend quota.

    Groq's free tier allows 1,000 requests per day. A health endpoint polled every five seconds
    would exhaust that in under an hour and take the assistants down to protect a status page.
    """
    body = (await client.get("/api/health")).json()

    detail = body["components"]["llm"]["detail"]
    assert "fake provider" in detail
    assert "no network calls" in detail


async def test_jenkins_down_degrades_rather_than_failing(
    client: AsyncClient, fake_jenkins: FakeJenkinsClient
) -> None:
    """Jenkins being unreachable must not report the whole backend as down.

    Sign-in, history and analytics all keep working without Jenkins; only job creation stops. A
    blanket 503 would tell an operator to restart a backend that is fine.
    """

    async def boom() -> str:
        raise JenkinsError("connection refused")

    fake_jenkins.version = boom  # type: ignore[method-assign]

    response = await client.get("/api/health")

    assert response.status_code == 200, "degraded is not the same as unavailable"
    body = response.json()
    assert body["status"] == ComponentStatus.DEGRADED.value
    assert body["components"]["jenkins"]["status"] == ComponentStatus.DOWN.value
    assert "connection refused" in body["components"]["jenkins"]["detail"]
    assert body["components"]["database"]["status"] == ComponentStatus.UP.value


async def test_component_failure_detail_is_truncated(
    client: AsyncClient, fake_jenkins: FakeJenkinsClient
) -> None:
    """A failure detail must not become an exfiltration channel.

    This response is readable by anyone who can reach the endpoint, and an exception message can
    carry a connection string or a token.
    """

    async def boom() -> str:
        raise JenkinsError("x" * 5000)

    fake_jenkins.version = boom  # type: ignore[method-assign]

    body = (await client.get("/api/health")).json()

    assert len(body["components"]["jenkins"]["detail"]) <= 200


async def test_health_records_latency_per_component(client: AsyncClient) -> None:
    body = (await client.get("/api/health")).json()

    for name, component in body["components"].items():
        assert component["latency_ms"] is not None, f"{name} reported no latency"
        assert component["latency_ms"] >= 0


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    """Every response carries a request id so a log line can be found from a failure."""
    response = await client.get("/api/health/live")

    assert response.headers.get("X-Request-ID")


async def test_inbound_request_id_is_preserved(client: AsyncClient) -> None:
    """A trace started by the frontend must continue through the backend."""
    response = await client.get("/api/health/live", headers={"X-Request-ID": "trace-me-123"})

    assert response.headers["X-Request-ID"] == "trace-me-123"


@pytest.mark.parametrize("path", ["/api/nope", "/api/health/nope"])
async def test_unknown_route_uses_the_one_error_shape(client: AsyncClient, path: str) -> None:
    """A 404 must look like every other error, or the frontend needs two failure paths."""
    response = await client.get(path)

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
