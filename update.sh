#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${SCREENLOOP_REPO_OWNER:-GezzyDax}"
REPO_NAME="${SCREENLOOP_REPO_NAME:-screenloop}"
BRANCH="${SCREENLOOP_UPDATE_BRANCH:-main}"
INSTALL_DIR="${SCREENLOOP_INSTALL_DIR:-$(pwd)}"
IMAGE="${SCREENLOOP_IMAGE_OVERRIDE:-}"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}"

usage() {
  cat <<EOF
Usage: ./update.sh [options]

Options:
  -dev, --dev           Update from dev branch and use ghcr.io/gezzydax/screenloop:dev
  --main                Update from main branch and use ghcr.io/gezzydax/screenloop:latest
  --branch <branch>     Update deployment files from a custom branch
  --image <image>       Override SCREENLOOP_IMAGE in .env
  -h, --help            Show this help
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -dev|--dev)
      BRANCH="dev"
      IMAGE="ghcr.io/gezzydax/screenloop:dev"
      shift
      ;;
    --main)
      BRANCH="main"
      IMAGE="ghcr.io/gezzydax/screenloop:latest"
      shift
      ;;
    --branch)
      BRANCH="${2:?Missing branch value}"
      shift 2
      ;;
    --image)
      IMAGE="${2:?Missing image value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}"

download() {
  local url="$1"
  local output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$output"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$output"
  else
    echo "Missing dependency: curl or wget" >&2
    exit 1
  fi
}

dotenv_quote() {
  local value="$1"
  if [[ "$value" == *"'"* ]]; then
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//\$/\\\$}"
    printf '"%s"' "$value"
  else
    printf "'%s'" "$value"
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local quoted
  quoted="$(dotenv_quote "$value")"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${quoted}|" .env
  else
    printf '%s=%s\n' "$key" "$quoted" >>.env
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Missing dependency: docker" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Missing dependency: Docker Compose plugin" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ ! -f .env ]; then
  echo "Missing .env in $INSTALL_DIR. Run install.sh first." >&2
  exit 1
fi

echo "Updating Screenloop deployment files from ${REPO_OWNER}/${REPO_NAME}:${BRANCH}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

download "${RAW_BASE}/docker-compose.ghcr.yml" "$tmpdir/docker-compose.yml"
download "${RAW_BASE}/.env.example" "$tmpdir/.env.example"
download "${RAW_BASE}/update.sh" "$tmpdir/update.sh"

cp "$tmpdir/docker-compose.yml" docker-compose.yml
cp "$tmpdir/.env.example" .env.example
cp "$tmpdir/update.sh" update.sh
chmod +x update.sh

if [ -n "$IMAGE" ]; then
  echo "Setting SCREENLOOP_IMAGE=${IMAGE}"
  set_env_value "SCREENLOOP_IMAGE" "$IMAGE"
fi

if ! grep -q "^SCREENLOOP_BOOTSTRAP_PASSWORD=" .env && grep -q "^SCREENLOOP_PASSWORD=" .env; then
  echo "Migrating legacy SCREENLOOP_PASSWORD to SCREENLOOP_BOOTSTRAP_PASSWORD"
  legacy_password="$(grep "^SCREENLOOP_PASSWORD=" .env | tail -n 1 | cut -d= -f2-)"
  printf 'SCREENLOOP_BOOTSTRAP_PASSWORD=%s\n' "$legacy_password" >>.env
fi

if ! grep -q "^SCREENLOOP_BOOTSTRAP_USER=" .env; then
  if grep -q "^SCREENLOOP_USER=" .env; then
    legacy_user="$(grep "^SCREENLOOP_USER=" .env | tail -n 1 | cut -d= -f2-)"
    printf 'SCREENLOOP_BOOTSTRAP_USER=%s\n' "$legacy_user" >>.env
  else
    set_env_value "SCREENLOOP_BOOTSTRAP_USER" "admin"
  fi
fi

echo "Pulling Screenloop image"
docker compose pull

echo "Restarting Screenloop"
docker compose up -d

echo "Current containers"
docker compose ps
