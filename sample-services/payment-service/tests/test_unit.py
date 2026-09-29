"""Unit suite. Target runtime about 8 seconds (catalog: approx_seconds 8).

The sleeps are deliberate and are the point of this service. The experiment needs jobs whose
durations differ predictably, because the execution-time factor T in the report's Algorithm 1 is
normalised across the queue: if every job took the same time, T would be a constant and one third
of the scoring formula would be untestable.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Spread across the tests rather than one lump, so a partial run still takes a realistic time.
STEP_SECONDS = 1.5


def test_health_reports_ok() -> None:
    time.sleep(STEP_SECONDS)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "payment-service"}


def test_version_exposes_the_commit() -> None:
    time.sleep(STEP_SECONDS)
    body = client.get("/version").json()
    assert body["service"] == "payment-service"
    # Never asserted to a fixed value: it changes every build, which is the whole point.
    assert "commit" in body


def test_payment_is_authorised() -> None:
    time.sleep(STEP_SECONDS)
    response = client.post("/payments", params={"amount_cents": 1250})
    assert response.status_code == 201
    body = response.json()
    assert body["amount_cents"] == 1250
    assert body["currency"] == "GBP"
    assert body["status"] == "authorised"


def test_currency_is_normalised() -> None:
    time.sleep(STEP_SECONDS)
    body = client.post("/payments", params={"amount_cents": 500, "currency": "usd"}).json()
    assert body["currency"] == "USD"


def test_index_lists_endpoints() -> None:
    time.sleep(STEP_SECONDS)
    body = client.get("/").json()
    assert "/health" in body["endpoints"]


@pytest.mark.parametrize("amount", [0, -1])
def test_non_positive_amount_is_rejected(amount: int) -> None:
    from app.main import create_payment

    with pytest.raises(ValueError, match="must be positive"):
        create_payment(amount)
