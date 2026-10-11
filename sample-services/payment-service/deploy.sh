#!/bin/sh
# Deploy payment-service to an environment.
#
# BUILD_PROMPT 4.2.4: builds the image, stops any existing container, starts it on the
# environment's port and waits for /health. Staging port 9001.
#
# Usage: ./deploy.sh staging
set -eu

ENVIRONMENT="${1:-}"
SERVICE="payment-service"
cd "$(dirname "$0")"

# Production is refused here as well as in the backend's policy layer. The scope is staging only
# (BUILD_PROMPT rule 1.5), and a deploy script that *could* reach production is one command away
# from doing so by accident.
case "$ENVIRONMENT" in
    staging) PORT=9001 ;;
    production)
        echo "[deploy] refused: this project is scoped to staging environments only." >&2
        exit 3
        ;;
    "")
        echo "[deploy] usage: ./deploy.sh staging" >&2
        exit 2
        ;;
    *)
        echo "[deploy] unknown environment '$ENVIRONMENT'; only 'staging' is allowed." >&2
        exit 2
        ;;
esac

COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
CONTAINER="${SERVICE}-${ENVIRONMENT}"
IMAGE="${SERVICE}:${ENVIRONMENT}"

echo "[deploy] building $IMAGE at commit $COMMIT"
docker build --quiet --build-arg "GIT_COMMIT=${COMMIT}" -t "$IMAGE" .

# Idempotent: a redeploy must replace the running container, not fail because the name is taken.
if [ -n "$(docker ps -aq -f "name=^${CONTAINER}$")" ]; then
    echo "[deploy] stopping existing $CONTAINER"
    docker rm -f "$CONTAINER" >/dev/null
fi

echo "[deploy] starting $CONTAINER on port $PORT"
docker run -d \
    --name "$CONTAINER" \
    --restart unless-stopped \
    -p "${PORT}:8080" \
    -e "DEPLOY_ENV=${ENVIRONMENT}" \
    -e "GIT_COMMIT=${COMMIT}" \
    "$IMAGE" >/dev/null

echo "[deploy] waiting for /health on port $PORT"
i=0
while [ "$i" -lt 30 ]; do
    if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
        echo "[deploy] healthy"
        curl -fsS "http://localhost:${PORT}/version" || true
        echo
        echo "[deploy] $SERVICE is live on $ENVIRONMENT at http://localhost:${PORT}"
        exit 0
    fi
    i=$((i + 1))
    sleep 2
done

# A deploy that never became healthy is a failed deploy. Exiting non-zero is what makes the
# freestyle chain stop here instead of reporting success.
echo "[deploy] failed: /health did not answer within 60s" >&2
docker logs --tail 40 "$CONTAINER" >&2 || true
exit 1
