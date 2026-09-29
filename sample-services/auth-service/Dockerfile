# auth-service runtime image.
FROM node:24-slim

# The commit being deployed, surfaced by /version, so a running container traces back to a commit.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT} \
    NODE_ENV=production \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY package.json ./
COPY src ./src

# node:24-slim already ships a non-root `node` user.
USER node
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["node", "src/server.js"]
