# Frontend image (Phase 6; D-018 left the Compose service behind a profile until it existed).
#
# Two stages: Node builds the app, then unprivileged nginx serves it and proxies /api and /ws to
# the backend. The app therefore talks to its own origin only, which keeps the Content-Security-
# Policy's connect-src at 'self' (vite.config.ts) and needs no CORS. Versions are exact tags checked
# against Docker Hub (docs/versions.md).

# --- Stage 1: build -----------------------------------------------------------
FROM node:24.21.0-alpine AS build

WORKDIR /app

# The manifests first, so a source-only change does not reinstall dependencies.
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# --- Stage 2: serve -----------------------------------------------------------
# nginx-unprivileged runs as a non-root user and may listen on 5173 without privileges.
FROM nginxinc/nginx-unprivileged:1.30.4-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:5173/ || exit 1
