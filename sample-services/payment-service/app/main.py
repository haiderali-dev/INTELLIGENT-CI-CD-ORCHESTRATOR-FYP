"""payment-service: a small FastAPI service used as a realistic CI/CD target.

BUILD_PROMPT 4.2.4 fixes what a sample service must provide: a ``/health`` endpoint, a ``/version``
endpoint returning the commit SHA, a lint command, test suites, a Dockerfile, and a ``deploy.sh``
that starts it on the environment's port and waits for health.

It is deliberately small. Its job is to give the scheduler real builds to order and real durations
to estimate, not to be an interesting application.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

SERVICE_NAME = "payment-service"

app = FastAPI(
    title=SERVICE_NAME,
    description="Sample service for the Intelligent CI/CD Orchestrator. Staging only.",
    version="1.0.0",
)


class Health(BaseModel):
    status: str
    service: str


class Version(BaseModel):
    service: str
    version: str
    commit: str
    environment: str


class Payment(BaseModel):
    id: str
    amount_cents: int
    currency: str
    status: str


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Liveness. deploy.sh polls this until it answers before declaring a deploy successful."""
    return Health(status="ok", service=SERVICE_NAME)


@app.get("/version", response_model=Version, tags=["ops"])
def version() -> Version:
    """Which build is running.

    The commit SHA is baked in at image build time as GIT_COMMIT. Without it a deploy cannot be
    told apart from the one before it, which makes "did my change actually go out?" unanswerable.
    """
    return Version(
        service=SERVICE_NAME,
        version=app.version,
        commit=os.environ.get("GIT_COMMIT", "unknown"),
        environment=os.environ.get("DEPLOY_ENV", "local"),
    )


@app.post("/payments", response_model=Payment, status_code=201, tags=["payments"])
def create_payment(amount_cents: int, currency: str = "GBP") -> Payment:
    """Accept a payment. In-memory and deliberately trivial."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    return Payment(
        id=f"pay_{amount_cents:08d}",
        amount_cents=amount_cents,
        currency=currency.upper(),
        status="authorised",
    )


@app.get("/", tags=["ops"])
def index() -> dict[str, Any]:
    return {"service": SERVICE_NAME, "endpoints": ["/health", "/version", "/payments"]}
