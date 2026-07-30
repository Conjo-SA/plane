# =====================================================================
#  Plane Community — All-In-One image for CapRover (fork build)
# ---------------------------------------------------------------------
#  This variant BUILDS the `web` and `space` frontends from THIS
#  repository's source, so the fork's customizations ship in the image:
#    - the intake portal admin tab (apps/web) and public page (apps/space)
#    - PT-BR i18n default and the editor/markdown changes (packages/*)
#  The backend Python package is overlaid from source as well.
#
#  `admin`, `live` and `proxy` still come from the official pre-built
#  images pinned to PLANE_VERSION (no fork changes there). Build admin
#  from source too if you later need PT-BR in the god-mode panel.
#
#  IMPORTANT: the build context MUST be the repository ROOT (see
#  /captain-definition). The frontend build is heavier than the old
#  assembly image — give the build host enough RAM (>= 4 GB) or it can
#  OOM, and expect the first build to take several minutes.
#
#  PLANE_VERSION pins the official images used for the unchanged
#  services and the backend base. Keep it aligned with package.json
#  (1.4.0 -> v1.4.0-rc2). Use "preview" to track the preview branch.
# =====================================================================
ARG PLANE_VERSION=v1.4.0-rc2

# **************************************************
#  STAGE 0: Node toolchain (also provides the runtime node binaries)
# **************************************************
FROM node:22-alpine AS node

# **************************************************
#  STAGE 1: Build `web` and `space` from the fork source
# **************************************************
FROM node:22-alpine AS fe-builder

# NOTE: NODE_ENV is intentionally NOT set to "production" here — that would make
# pnpm skip devDependencies (turbo, vite, typescript), which are required to
# build. Vite/react-router already emit a production build regardless.
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PNPM_HOME/bin:$PATH"
ENV CI=1
ENV NEXT_TELEMETRY_DISABLED=1
ENV TURBO_TELEMETRY_DISABLED=1

# Public build-time envs. Keep identical to the official AIO single-domain
# layout so relative paths resolve behind the Caddy proxy (see Caddyfile:
# /api -> api, /spaces -> space, /live -> live, /god-mode -> admin).
ENV VITE_API_BASE_URL=""
ENV VITE_API_BASE_PATH="/api"
ENV VITE_ADMIN_BASE_PATH="/god-mode"
ENV VITE_LIVE_BASE_PATH="/live"
ENV VITE_SPACE_BASE_PATH="/spaces"
ENV VITE_WEB_BASE_PATH=""

RUN apk add --no-cache libc6-compat
RUN corepack enable && corepack enable pnpm

WORKDIR /app

# `.dockerignore` excludes node_modules/build/.turbo, so this copies only
# source. Install the whole workspace once; --prod=false forces dev deps
# (build tooling) to be installed even if NODE_ENV leaks in as production.
COPY . .
RUN CI=true pnpm install --frozen-lockfile --prod=false

# Build both frontends (turbo also builds their workspace package deps).
RUN pnpm turbo run build --filter=web --filter=space

# Build outputs:
#   web   -> /app/apps/web/build/client            (static, served by Caddy)
#   space -> /app/apps/space/build                 (react-router server bundle)
#            /app/apps/space/node_modules          (app deps)
#            /app/node_modules                      (hoisted root deps)

# **************************************************
#  STAGE 2: Official images for the unchanged services + backend base
# **************************************************
FROM makeplane/plane-backend:${PLANE_VERSION} AS backend-img
FROM makeplane/plane-admin:${PLANE_VERSION} AS admin-img
FROM makeplane/plane-live:${PLANE_VERSION} AS live-img
FROM makeplane/plane-proxy:${PLANE_VERSION} AS proxy-img

# **************************************************
#  STAGE 3: Runner
# **************************************************
FROM python:3.12.10-alpine AS runner

WORKDIR /app

RUN apk add --no-cache \
    "libpq" \
    "libxslt" \
    "xmlsec"

# Node runtime (the space service is a react-router SSR server on node)
COPY --from=node /usr/lib /usr/lib
COPY --from=node /usr/local/lib /usr/local/lib
COPY --from=node /usr/local/include /usr/local/include
COPY --from=node /usr/local/bin /usr/local/bin

# --- Frontend built from THIS repo ---
# web: static client served by Caddy at /*
COPY --from=fe-builder /app/apps/web/build/client /app/web
# space: react-router server + node_modules, replicating the official layout so
# that `directory=/app/space/apps/space` + relative pnpm symlinks resolve
# (apps/space/node_modules -> ../../node_modules == /app/space/node_modules).
COPY --from=fe-builder /app/apps/space/build        /app/space/apps/space/build
COPY --from=fe-builder /app/apps/space/node_modules /app/space/apps/space/node_modules
COPY --from=fe-builder /app/node_modules            /app/space/node_modules

# admin (god-mode) and live come from the official images (no fork changes)
COPY --from=admin-img /usr/share/nginx/html/god-mode /app/admin
COPY --from=live-img /app /app/live

COPY --from=proxy-img /usr/bin/caddy /usr/bin/caddy

# --- Backend: official image + overlay the fork's plane package ---
# The whole `plane` package is copied so new modules (intake portal models/
# views/urls) and migrations are never silently left out of the image.
COPY --from=backend-img /code /app/backend
COPY --from=backend-img /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=backend-img /usr/local/bin/ /usr/local/bin/
COPY apps/api/plane /app/backend/plane

# Entrypoint scripts are patched too (worker flags for RabbitMQ 4.x compatibility).
COPY apps/api/bin /app/backend/bin
RUN chmod +x /app/backend/bin/*.sh

# Python dependencies added by this fork on top of the official backend image
# (site-packages above comes from backend-img, so new requirements must be
# installed explicitly or the API fails to boot on import).
RUN pip install --no-cache-dir mistune==3.0.2

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
