# Backend image.
#
# Two stages so the runtime image carries no build toolchain and no uv cache. Python 3.12 to match
# pyproject.toml's requires-python and the report's Appendix E (docs/decisions.md D-010).

# --- Stage 1: dependencies ----------------------------------------------------
FROM python:3.12-slim AS deps

# uv resolves and installs from the committed lock file, so the image is reproducible: the same
# uv.lock produces the same versions regardless of when it is built.
COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the dependency manifests first, so a source-only change does not re-resolve dependencies.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- Stage 2: runtime ---------------------------------------------------------
FROM python:3.12-slim AS runtime

# curl for the container healthcheck. No build tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    # Run as a non-root user. The backend creates Jenkins jobs over HTTP and needs no host access,
    # so there is no reason for it to be root inside its own container.
    && groupadd --system --gid 1001 orchestrator \
    && useradd --system --uid 1001 --gid orchestrator --create-home orchestrator

WORKDIR /app

COPY --from=deps --chown=orchestrator:orchestrator /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Migrations travel with the image so `docker compose exec backend alembic upgrade head` works
# without a bind mount, and so the image is self-contained for a demo reset.
COPY --chown=orchestrator:orchestrator alembic.ini ./
COPY --chown=orchestrator:orchestrator alembic ./alembic
COPY --chown=orchestrator:orchestrator app ./app

USER orchestrator

EXPOSE 8000

# Hits the dependency-free liveness endpoint, not /api/health. A container is alive when the process
# is serving; it should not be restarted because PostgreSQL is briefly unreachable.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health/live || exit 1

# --factory because app/main.py deliberately has no module-level `app`: building one at import time
# would make a missing setting an import error instead of a clear startup message.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
