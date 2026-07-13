#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${SCREENLOOP_REPO_OWNER:-GezzyDax}"
REPO_NAME="${SCREENLOOP_REPO_NAME:-screenloop}"
BRANCH="${SCREENLOOP_UPDATE_BRANCH:-main}"
INSTALL_DIR="${SCREENLOOP_INSTALL_DIR:-$(pwd)}"
IMAGE="${SCREENLOOP_IMAGE_OVERRIDE:-}"
UI_IMAGE="${SCREENLOOP_UI_IMAGE_OVERRIDE:-}"

usage() {
  cat <<EOF
Usage: ./update.sh [options]

Options:
  -dev, --dev           Update from dev branch and use ghcr.io/gezzydax/screenloop:dev
  --main, --stable      Update from main branch and use ghcr.io/gezzydax/screenloop:latest
  --branch <branch>     Update deployment files from a custom branch
  --image <image>       Override SCREENLOOP_IMAGE in .env
  --ui-image <image>    Override SCREENLOOP_UI_IMAGE in .env
  --rollback <version>  Pin both images to a released version (e.g. 1.5.0) and restart
  --dir <path>          Update a custom install directory
  -h, --help            Show this help
EOF
}

ROLLBACK_VERSION=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    -dev|--dev)
      BRANCH="dev"
      IMAGE="ghcr.io/gezzydax/screenloop:dev"
      UI_IMAGE="ghcr.io/gezzydax/screenloop-ui:dev"
      shift
      ;;
    --main|--stable)
      BRANCH="main"
      IMAGE="ghcr.io/gezzydax/screenloop:latest"
      UI_IMAGE="ghcr.io/gezzydax/screenloop-ui:latest"
      shift
      ;;
    --branch)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --branch" >&2
        exit 2
      fi
      BRANCH="$2"
      shift 2
      ;;
    --branch=*)
      BRANCH="${1#*=}"
      shift
      ;;
    --image)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --image" >&2
        exit 2
      fi
      IMAGE="$2"
      shift 2
      ;;
    --image=*)
      IMAGE="${1#*=}"
      shift
      ;;
    --ui-image)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --ui-image" >&2
        exit 2
      fi
      UI_IMAGE="$2"
      shift 2
      ;;
    --ui-image=*)
      UI_IMAGE="${1#*=}"
      shift
      ;;
    --rollback)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --rollback" >&2
        exit 2
      fi
      ROLLBACK_VERSION="$2"
      shift 2
      ;;
    --rollback=*)
      ROLLBACK_VERSION="${1#*=}"
      shift
      ;;
    --dir)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --dir" >&2
        exit 2
      fi
      INSTALL_DIR="$2"
      shift 2
      ;;
    --dir=*)
      INSTALL_DIR="${1#*=}"
      shift
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

needs_update_elevation() {
  [ "$(id -u)" -ne 0 ] && { [ ! -d "$INSTALL_DIR" ] || [ ! -w "$INSTALL_DIR" ]; }
}

maybe_reexec_with_sudo() {
  if ! needs_update_elevation; then
    return 0
  fi

  if ! command -v sudo >/dev/null 2>&1; then
    echo "Install directory requires elevated permissions: $INSTALL_DIR" >&2
    echo "Run as root, install sudo, or pass --dir with a writable path." >&2
    exit 1
  fi

  local script_path="${BASH_SOURCE[0]:-$0}"
  if [ -r "$script_path" ] && [ "$script_path" != "bash" ] && [ "$script_path" != "sh" ]; then
    echo "Install directory requires elevated permissions: $INSTALL_DIR"
    echo "Re-running updater with sudo. Enter your sudo password if prompted."
    exec sudo env \
      SCREENLOOP_REPO_OWNER="$REPO_OWNER" \
      SCREENLOOP_REPO_NAME="$REPO_NAME" \
      SCREENLOOP_UPDATE_BRANCH="$BRANCH" \
      SCREENLOOP_INSTALL_DIR="$INSTALL_DIR" \
      SCREENLOOP_IMAGE_OVERRIDE="$IMAGE" \
      SCREENLOOP_UI_IMAGE_OVERRIDE="$UI_IMAGE" \
      bash "$script_path" "$@"
  fi

  echo "Install directory requires elevated permissions: $INSTALL_DIR" >&2
  echo "Save update.sh to a temporary file first, then run it so sudo can re-run the script." >&2
  exit 1
}

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    if ! command -v sudo >/dev/null 2>&1; then
      echo "Missing sudo. Run as root or install sudo first." >&2
      exit 1
    fi
    sudo "$@"
  fi
}

docker_can_access_daemon() {
  docker info >/dev/null 2>&1
}

run_docker() {
  if docker_can_access_daemon; then
    docker "$@"
  else
    run_privileged docker "$@"
  fi
}

download() {
  local url="$1"
  local output="$2"
  local attempts="${SCREENLOOP_DOWNLOAD_RETRIES:-5}"
  local attempt=1
  local delay=2
  local curl_ip_args=()

  if [ "${SCREENLOOP_CURL_IPV4:-false}" = "true" ]; then
    curl_ip_args=(--ipv4)
  fi

  while [ "$attempt" -le "$attempts" ]; do
    if command -v curl >/dev/null 2>&1; then
      if curl "${curl_ip_args[@]}" \
        --fail --show-error --silent --location \
        --connect-timeout 20 \
        --retry 3 \
        --retry-delay 2 \
        --retry-all-errors \
        "$url" -o "$output"; then
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q --tries=3 --timeout=30 "$url" -O "$output"; then
        return 0
      fi
    else
      echo "Missing dependency: curl or wget" >&2
      exit 1
    fi

    if [ "$attempt" -lt "$attempts" ]; then
      echo "Download failed (${attempt}/${attempts}): $url" >&2
      echo "Retrying in ${delay}s..." >&2
      sleep "$delay"
      delay=$((delay * 2))
    fi
    attempt=$((attempt + 1))
  done

  echo "Failed to download after ${attempts} attempts: $url" >&2
  echo "If GitHub Raw TLS keeps failing, retry with SCREENLOOP_CURL_IPV4=true or check DNS/proxy/firewall." >&2
  exit 35
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

dotenv_unquote() {
  local value="$1"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

get_env_value() {
  local key="$1"
  local value
  value="$(grep "^${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
  dotenv_unquote "$value"
}

clean_url_value() {
  local value="$1"
  value="${value//\'/}"
  value="${value//\"/}"
  printf '%s' "$value"
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

maybe_reexec_with_sudo "$@"

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

if [ -n "$ROLLBACK_VERSION" ]; then
  rollback_version="${ROLLBACK_VERSION#v}"
  echo "Rolling back to version ${rollback_version}"
  set_env_value "SCREENLOOP_IMAGE" "ghcr.io/gezzydax/screenloop:${rollback_version}"
  set_env_value "SCREENLOOP_UI_IMAGE" "ghcr.io/gezzydax/screenloop-ui:${rollback_version}"
  chmod 600 .env
  run_docker compose pull
  run_docker compose up -d
  echo "Rollback to ${rollback_version} complete. Data in the screenloop-data volume is untouched."
  exit 0
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

if [ "${SCREENLOOP_UPDATE_REEXECED:-0}" != "1" ]; then
  echo "Re-running updated updater"
  exec env \
    SCREENLOOP_REPO_OWNER="$REPO_OWNER" \
    SCREENLOOP_REPO_NAME="$REPO_NAME" \
    SCREENLOOP_UPDATE_BRANCH="$BRANCH" \
    SCREENLOOP_INSTALL_DIR="$INSTALL_DIR" \
    SCREENLOOP_IMAGE_OVERRIDE="$IMAGE" \
    SCREENLOOP_UI_IMAGE_OVERRIDE="$UI_IMAGE" \
    SCREENLOOP_UPDATE_REEXECED=1 \
    bash update.sh
fi

if [ -n "$IMAGE" ]; then
  echo "Setting SCREENLOOP_IMAGE=${IMAGE}"
  set_env_value "SCREENLOOP_IMAGE" "$IMAGE"
fi

if [ -n "$UI_IMAGE" ]; then
  echo "Setting SCREENLOOP_UI_IMAGE=${UI_IMAGE}"
  set_env_value "SCREENLOOP_UI_IMAGE" "$UI_IMAGE"
fi

if ! grep -q "^SCREENLOOP_UI_PORT=" .env; then
  echo "Adding SCREENLOOP_UI_PORT=8098"
  set_env_value "SCREENLOOP_UI_PORT" "8098"
fi

if ! grep -q "^SCREENLOOP_PUBLIC_URL=" .env; then
  ui_port="$(get_env_value "SCREENLOOP_UI_PORT")"
  advertise_hosts="$(get_env_value "SCREENLOOP_ADVERTISE_HOSTS")"
  advertise_host="${advertise_hosts%%,*}"
  if [ -z "$advertise_host" ]; then
    advertise_host="$(get_env_value "SCREENLOOP_ADVERTISE_HOST")"
  fi
  advertise_host="$(clean_url_value "$advertise_host")"
  ui_port="$(clean_url_value "$ui_port")"
  if [ -n "$advertise_host" ]; then
    echo "Adding SCREENLOOP_PUBLIC_URL=http://${advertise_host}:${ui_port:-8098}"
    set_env_value "SCREENLOOP_PUBLIC_URL" "http://${advertise_host}:${ui_port:-8098}"
  fi
else
  public_url="$(get_env_value "SCREENLOOP_PUBLIC_URL")"
  clean_public_url="$(clean_url_value "$public_url")"
  if [ -n "$public_url" ] && [ "$clean_public_url" != "$public_url" ]; then
    echo "Repairing SCREENLOOP_PUBLIC_URL=${clean_public_url}"
    set_env_value "SCREENLOOP_PUBLIC_URL" "$clean_public_url"
  fi
fi

if ! grep -q "^SCREENLOOP_BOOTSTRAP_PASSWORD=" .env && grep -q "^SCREENLOOP_PASSWORD=" .env; then
  echo "Migrating legacy SCREENLOOP_PASSWORD to SCREENLOOP_BOOTSTRAP_PASSWORD"
  legacy_password="$(get_env_value "SCREENLOOP_PASSWORD")"
  set_env_value "SCREENLOOP_BOOTSTRAP_PASSWORD" "$legacy_password"
fi

if ! grep -q "^SCREENLOOP_BOOTSTRAP_USER=" .env; then
  if grep -q "^SCREENLOOP_USER=" .env; then
    legacy_user="$(get_env_value "SCREENLOOP_USER")"
    set_env_value "SCREENLOOP_BOOTSTRAP_USER" "$legacy_user"
  else
    set_env_value "SCREENLOOP_BOOTSTRAP_USER" "admin"
  fi
fi

chmod 600 .env

echo "Pulling Screenloop image"
run_docker compose pull

echo "Restarting Screenloop"
if ! run_docker compose up -d; then
  echo "Docker Compose failed to start Screenloop." >&2
  echo "If the error mentions TTRPC, shim, containerd, or unsupported protocol, restart Docker/containerd and retry:" >&2
  echo "  sudo systemctl restart containerd docker" >&2
  echo "  cd $INSTALL_DIR && sudo ./update.sh ${BRANCH:+--branch $BRANCH}" >&2
  echo "Recent container state:" >&2
  run_docker compose ps || true
  exit 1
fi

echo "Current containers"
run_docker compose ps
