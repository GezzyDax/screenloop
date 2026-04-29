#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${SCREENLOOP_REPO_OWNER:-GezzyDax}"
REPO_NAME="${SCREENLOOP_REPO_NAME:-screenloop}"
BRANCH="${SCREENLOOP_UPDATE_BRANCH:-main}"
INSTALL_DIR="${SCREENLOOP_INSTALL_DIR:-$(pwd)}"
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

echo "Pulling Screenloop image"
docker compose pull

echo "Restarting Screenloop"
docker compose up -d

echo "Current containers"
docker compose ps
