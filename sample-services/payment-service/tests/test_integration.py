"""Integration suite. Target runtime about 20 seconds (catalog: approx_seconds 20).

Longer than the unit suite on purpose. The scheduler's execution-time factor rewards shorter jobs,
so the workload needs jobs that genuinely differ in duration for that factor to be measurable.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STEP_SECONDS = 4.0


def test_payment_round_trip() -> None:
    time.sleep(STEP_SECONDS)
    created = client.post("/payments", params={"amount_cents": 9900}).json()
    assert created["id"].startswith("pay_")


def test_health_stays_up_under_repeated_calls() -> None:
    time.sleep(STEP_SECONDS)
    for _ in range(20):
        assert client.get("/health").status_code == 200


def test_version_is_stable_within_a_run() -> None:
    time.sleep(STEP_SECONDS)
    first = client.get("/version").json()
    second = client.get("/version").json()
    assert first == second


def test_several_payments_get_distinct_ids() -> None:
    time.sleep(STEP_SECONDS)
    ids = {client.post("/payments", params={"amount_cents": n}).json()["id"] for n in range(1, 11)}
    assert len(ids) == 10


def test_openapi_schema_is_served() -> None:
    time.sleep(STEP_SECONDS)
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert "/version" in schema["paths"]
