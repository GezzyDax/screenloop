#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${SCREENLOOP_REPO_OWNER:-GezzyDax}"
REPO_NAME="${SCREENLOOP_REPO_NAME:-screenloop}"
BRANCH="${SCREENLOOP_INSTALL_BRANCH:-main}"
INSTALL_DIR="${SCREENLOOP_INSTALL_DIR:-/opt/screenloop}"
IMAGE="${SCREENLOOP_IMAGE:-ghcr.io/gezzydax/screenloop:latest}"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing dependency: $1" >&2
    return 1
  fi
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64
    echo
  fi
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local value
  read -r -p "${prompt} [${default}]: " value
  echo "${value:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local value
  while true; do
    read -r -s -p "${prompt}: " value
    echo >&2
    if [ "${#value}" -ge 12 ]; then
      echo "$value"
      return 0
    fi
    echo "Value must be at least 12 characters." >&2
  done
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

if ! need_cmd docker; then
  echo "Install Docker first: https://docs.docker.com/engine/install/" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Missing dependency: Docker Compose plugin." >&2
  echo "Install it first: https://docs.docker.com/compose/install/linux/" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ ! -w "$(dirname "$INSTALL_DIR")" ]; then
  echo "Install directory requires elevated permissions: $INSTALL_DIR" >&2
  echo "Run with sudo or set SCREENLOOP_INSTALL_DIR to a writable path." >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "Downloading Screenloop deployment files to $INSTALL_DIR"
download "${RAW_BASE}/docker-compose.ghcr.yml" docker-compose.yml
download "${RAW_BASE}/.env.example" .env.example

if [ -f .env ]; then
  read -r -p ".env already exists. Overwrite it? [y/N]: " overwrite
  if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
    echo "Keeping existing .env"
  else
    rm -f .env
  fi
fi

if [ ! -f .env ]; then
  echo "Create Screenloop configuration"
  http_port="$(prompt_default "HTTP port" "8099")"
  user="$(prompt_default "Web username" "admin")"
  password="$(prompt_secret "Web password, minimum 12 characters")"
  advertise_host="$(prompt_default "Advertise host/IP for TVs, empty for auto-detect" "")"
  advertise_hosts="$(prompt_default "Advertise hosts for multiple subnets, comma-separated, empty for auto-detect" "$advertise_host")"
  secret_key="$(random_secret)"

  cat >.env <<EOF
SCREENLOOP_HTTP_PORT=$(dotenv_quote "$http_port")
SCREENLOOP_USER=$(dotenv_quote "$user")
SCREENLOOP_PASSWORD=$(dotenv_quote "$password")
SCREENLOOP_SECRET_KEY=$(dotenv_quote "$secret_key")
SCREENLOOP_ADVERTISE_HOST=$(dotenv_quote "$advertise_host")
SCREENLOOP_ADVERTISE_HOSTS=$(dotenv_quote "$advertise_hosts")
SCREENLOOP_MAX_UPLOAD_BYTES=2147483648
SCREENLOOP_IMAGE=$(dotenv_quote "$IMAGE")
EOF
  chmod 600 .env
fi

echo "Starting Screenloop"
docker compose pull
docker compose up -d

port="$(grep '^SCREENLOOP_HTTP_PORT=' .env | cut -d= -f2-)"
echo "Screenloop is starting at http://localhost:${port:-8099}"
echo "If this host is remote, open http://<host-ip>:${port:-8099}"
