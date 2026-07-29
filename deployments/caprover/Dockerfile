# =====================================================================
#  Plane Community — All-In-One image for CapRover
# ---------------------------------------------------------------------
#  Self-contained variant of deployments/aio/community/Dockerfile that
#  does NOT depend on build.sh generating a ./dist folder. The build
#  context is the REPOSITORY ROOT (see /captain-definition), so support
#  files are copied directly from their source locations in the repo.
#
#  This image ASSEMBLES the official pre-built service images pinned to
#  PLANE_VERSION — it does not compile the local working tree. The tag
#  MUST match this source's layout (nginx-static web/admin). v1.4.0-rc2
#  matches package.json (1.4.0). Use "preview" to track the preview
#  branch. Older tags like v0.27.1 use the old Next.js layout and will
#  fail with: COPY failed: stat usr/share/nginx/html: file does not exist
# =====================================================================
ARG PLANE_VERSION=v1.4.0-rc2

# **************************************************
#  STAGE 0: Image Loading
# **************************************************
FROM node:22-alpine AS node

FROM makeplane/plane-frontend:${PLANE_VERSION} AS web-img
FROM makeplane/plane-backend:${PLANE_VERSION} AS backend-img
FROM makeplane/plane-space:${PLANE_VERSION} AS space-img
FROM makeplane/plane-admin:${PLANE_VERSION} AS admin-img
FROM makeplane/plane-live:${PLANE_VERSION} AS live-img
FROM makeplane/plane-proxy:${PLANE_VERSION} AS proxy-img

# **************************************************
#  STAGE 1: Runner
# **************************************************
FROM python:3.12.10-alpine AS runner

WORKDIR /app

RUN apk add --no-cache \
    "libpq" \
    "libxslt" \
    "xmlsec"

COPY --from=node /usr/lib /usr/lib
COPY --from=node /usr/local/lib /usr/local/lib
COPY --from=node /usr/local/include /usr/local/include
COPY --from=node /usr/local/bin /usr/local/bin

COPY --from=web-img /usr/share/nginx/html /app/web
COPY --from=space-img /app /app/space
COPY --from=admin-img /usr/share/nginx/html/god-mode /app/admin
COPY --from=live-img /app /app/live

RUN rm -rf /app/space/apps/space/.next/cache

COPY --from=proxy-img /usr/bin/caddy /usr/bin/caddy

COPY --from=backend-img /code /app/backend
COPY --from=backend-img /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=backend-img /usr/local/bin/ /usr/local/bin/

RUN apk add --no-cache nss-tools bash curl uuidgen ncdu vim

RUN pip install supervisor
RUN mkdir -p /etc/supervisor/conf.d

# --- Support files copied straight from the repo (no build.sh / dist) ---
COPY apps/proxy/Caddyfile.aio.ce            /app/proxy/Caddyfile
COPY deployments/aio/community/variables.env /app/plane.env
COPY deployments/aio/community/start.sh      /app/start.sh
COPY deployments/aio/community/supervisor.conf /etc/supervisor/conf.d/supervisor.conf

RUN mkdir -p /app/logs/access && \
    mkdir -p /app/logs/error && \
    mkdir -p /app/data && \
    chmod +x /app/start.sh

VOLUME ["/app/data", "/app/logs"]

# CapRover terminates TLS at its own nginx and proxies plain HTTP to the
# container's port 80 (Caddy listens on SITE_ADDRESS=:80).
EXPOSE 80

CMD ["/app/start.sh"]
