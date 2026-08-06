#!/usr/bin/env bash
# End-to-end smoke test: boots the real container images and exercises the API
# the way a browser would. Catches what unit tests cannot -- broken images,
# schema upgrades that only fail against a real database file, and nginx
# template errors in the UI container.
#
#   ./scripts/smoke.sh start   # build-free boot of the stack
#   ./scripts/smoke.sh check   # assertions against the running stack
#   ./scripts/smoke.sh logs    # dump container logs
#   ./scripts/smoke.sh stop    # tear down, including the data volume
#
# Images default to the local tags produced by CI; override with
# SCREENLOOP_IMAGE / SCREENLOOP_UI_IMAGE to smoke test a published build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env.smoke"
PROJECT="screenloop-smoke"
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/docker-compose.ghcr.yml" --env-file "$ENV_FILE")

# Deliberately not 8099/8098: the stack runs on the host network, so those
# defaults would collide with a Screenloop the developer already has running.
HTTP_PORT="${SCREENLOOP_HTTP_PORT:-18099}"
UI_PORT="${SCREENLOOP_UI_PORT:-18098}"
API="http://127.0.0.1:${HTTP_PORT}"
UI="http://127.0.0.1:${UI_PORT}"

# Global, not a local in cmd_check: the EXIT trap runs after that function has
# returned, and under `set -u` a dead local would abort the script at exit.
JAR=""
trap 'rm -f "$JAR"' EXIT

fail() {
  echo "::error::smoke: $*" >&2
  exit 1
}

ok() {
  echo "  ok  $*"
}

write_env() {
  cat >"$ENV_FILE" <<EOF
SCREENLOOP_IMAGE=${SCREENLOOP_IMAGE:-screenloop:smoke}
SCREENLOOP_UI_IMAGE=${SCREENLOOP_UI_IMAGE:-screenloop-ui:smoke}
SCREENLOOP_SECRET_KEY=$(openssl rand -hex 32)
SCREENLOOP_BOOTSTRAP_USER=smoke-admin
SCREENLOOP_BOOTSTRAP_PASSWORD=smoke-$(openssl rand -hex 12)
SCREENLOOP_HTTP_PORT=${HTTP_PORT}
SCREENLOOP_UI_PORT=${UI_PORT}
SCREENLOOP_ACCESS_LOG=false
SCREENLOOP_UPDATE_CHECK=false
SCREENLOOP_EXPECTED_VERSION=${SCREENLOOP_EXPECTED_VERSION:-}
EOF
}

load_env() {
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing -- run 'smoke.sh start' first"
  # shellcheck disable=SC1090
  set -a && . "$ENV_FILE" && set +a
}

wait_for_health() {
  local label="$1" deadline=$((SECONDS + 90))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 3 "$API/api/health" >/dev/null 2>&1; then
      ok "$label"
      return 0
    fi
    sleep 2
  done
  fail "backend did not become healthy within 90s ($label)"
}

cmd_start() {
  write_env
  "${COMPOSE[@]}" up -d --wait --wait-timeout 120 || {
    cmd_logs
    fail "the stack did not start"
  }
  ok "stack is up"
}

cmd_check() {
  load_env
  JAR="$(mktemp)"

  wait_for_health "backend health endpoint answers"

  # Unauthenticated access to real data must be rejected, not merely empty.
  local anon
  anon="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/api/v1/status")"
  [ "$anon" = "401" ] || fail "/api/v1/status returned $anon for an anonymous client, expected 401"
  ok "status endpoint rejects anonymous clients"

  local login
  login="$(curl -fsS --max-time 10 -c "$JAR" -X POST "$API/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${SCREENLOOP_BOOTSTRAP_USER}\",\"password\":\"${SCREENLOOP_BOOTSTRAP_PASSWORD}\"}")" \
    || fail "login with the bootstrap credentials failed"
  echo "$login" | grep -q '"csrf_token"' || fail "login response carried no csrf_token"
  ok "bootstrap admin can log in"

  curl -fsS --max-time 10 -b "$JAR" "$API/api/v1/status" | grep -q '"tvs"' \
    || fail "/api/v1/status did not return a dashboard payload"
  ok "authenticated status payload returned"

  # The version the image reports must be the one CI built into it, otherwise
  # the build-arg wiring in the Dockerfile has silently broken.
  local version
  version="$(curl -fsS --max-time 10 -b "$JAR" "$API/api/v1/version")" \
    || fail "/api/v1/version did not return a version"
  if [ -n "${SCREENLOOP_EXPECTED_VERSION:-}" ]; then
    echo "$version" | grep -Fq "\"version\":\"${SCREENLOOP_EXPECTED_VERSION}\"" \
      || fail "/api/v1/version did not return ${SCREENLOOP_EXPECTED_VERSION}"
  else
    echo "$version" | grep -q '"version"' || fail "/api/v1/version did not return a version"
  fi
  ok "version endpoint reports the image build version"

  # Profiles are read from TOML templates baked into the image, so this also
  # proves the template files actually shipped.
  curl -fsS --max-time 10 -b "$JAR" "$API/api/v1/profiles" | grep -q '"generic' \
    || fail "/api/v1/profiles did not return the bundled TV templates"
  ok "TV templates loaded inside the image"

  curl -fsS --max-time 10 "$UI/" | grep -qi '<div id="app"' \
    || fail "the UI container did not serve the Vue shell"
  ok "UI serves the application shell"

  curl -fsS --max-time 10 "$UI/api/health" >/dev/null \
    || fail "the UI container did not proxy /api/health to the backend"
  ok "UI proxies the API"

  # Restarting against the database that was just created is the cheapest real
  # check that schema initialisation is idempotent on an existing data volume --
  # the failure mode that only shows up on an upgraded production install.
  "${COMPOSE[@]}" restart screenloop >/dev/null
  wait_for_health "backend restarts cleanly on an existing database"

  curl -fsS --max-time 10 -b "$JAR" "$API/api/v1/status" >/dev/null \
    || fail "the session did not survive a backend restart"
  ok "session survives a restart"

  echo "smoke: all checks passed"
}

cmd_logs() {
  [ -f "$ENV_FILE" ] || return 0
  "${COMPOSE[@]}" ps || true
  "${COMPOSE[@]}" logs --no-color --tail 200 || true
}

cmd_stop() {
  [ -f "$ENV_FILE" ] || return 0
  "${COMPOSE[@]}" down -v --remove-orphans || true
  rm -f "$ENV_FILE"
}

case "${1:-}" in
  start) cmd_start ;;
  check) cmd_check ;;
  logs) cmd_logs ;;
  stop) cmd_stop ;;
  all)
    cmd_start
    cmd_check
    cmd_stop
    ;;
  *)
    echo "usage: $0 {start|check|logs|stop|all}" >&2
    exit 2
    ;;
esac
