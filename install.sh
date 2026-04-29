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

list_ipv4_interfaces() {
  if ! command -v ip >/dev/null 2>&1; then
    return 0
  fi
  ip -o -4 addr show scope global up | while read -r _ ifname _ cidr _; do
    ip_addr="${cidr%%/*}"
    printf '%s\t%s\n' "$ip_addr" "$ifname"
  done
}

join_by_comma() {
  local IFS=,
  echo "$*"
}

select_advertise_hosts() {
  local rows=()
  local ips=()
  local labels=()
  local selected=()
  local line ip_addr ifname

  while IFS=$'\t' read -r ip_addr ifname; do
    [ -n "$ip_addr" ] || continue
    ips+=("$ip_addr")
    labels+=("${ifname} ${ip_addr}")
  done < <(list_ipv4_interfaces)

  if [ "${#ips[@]}" -eq 0 ]; then
    prompt_default "Advertise hosts for multiple subnets, comma-separated, empty for auto-detect" ""
    return 0
  fi

  if command -v whiptail >/dev/null 2>&1; then
    for i in "${!ips[@]}"; do
      rows+=("${ips[$i]}" "${labels[$i]}" "on")
    done
    if choice="$(whiptail --title "Screenloop network interfaces" \
      --checklist "Select server IPs that TVs can reach. Use Space to toggle, Enter to apply." \
      20 78 10 "${rows[@]}" 3>&1 1>&2 2>&3)"; then
      # whiptail returns quoted tokens.
      # shellcheck disable=SC2086
      selected=($choice)
      for i in "${!selected[@]}"; do
        selected[$i]="${selected[$i]//\"/}"
      done
      join_by_comma "${selected[@]}"
      return 0
    fi
  elif command -v dialog >/dev/null 2>&1; then
    for i in "${!ips[@]}"; do
      rows+=("${ips[$i]}" "${labels[$i]}" "on")
    done
    tmpfile="$(mktemp)"
    if dialog --title "Screenloop network interfaces" \
      --checklist "Select server IPs that TVs can reach. Use Space to toggle, Enter to apply." \
      20 78 10 "${rows[@]}" 2>"$tmpfile"; then
      # shellcheck disable=SC2207
      selected=($(tr -d '"' <"$tmpfile"))
      rm -f "$tmpfile"
      join_by_comma "${selected[@]}"
      return 0
    fi
    rm -f "$tmpfile"
  fi

  echo "Detected server IPv4 addresses:" >&2
  for i in "${!ips[@]}"; do
    printf '  %s) %s\n' "$((i + 1))" "${labels[$i]}" >&2
  done
  echo "Enter numbers to enable, comma-separated. Press Enter to use all detected addresses." >&2
  read -r -p "Advertise interfaces [all]: " line
  if [ -z "$line" ]; then
    join_by_comma "${ips[@]}"
    return 0
  fi
  IFS=, read -r -a selected_numbers <<<"$line"
  selected=()
  for number in "${selected_numbers[@]}"; do
    number="${number// /}"
    if [[ "$number" =~ ^[0-9]+$ ]] && [ "$number" -ge 1 ] && [ "$number" -le "${#ips[@]}" ]; then
      selected+=("${ips[$((number - 1))]}")
    fi
  done
  join_by_comma "${selected[@]}"
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
download "${RAW_BASE}/update.sh" update.sh
chmod +x update.sh

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
  user="$(prompt_default "Bootstrap admin username" "admin")"
  password="$(prompt_secret "Bootstrap admin password, minimum 12 characters")"
  advertise_hosts="$(select_advertise_hosts)"
  advertise_host="${advertise_hosts%%,*}"
  secret_key="$(random_secret)"

  cat >.env <<EOF
SCREENLOOP_HTTP_PORT=$(dotenv_quote "$http_port")
SCREENLOOP_BOOTSTRAP_USER=$(dotenv_quote "$user")
SCREENLOOP_BOOTSTRAP_PASSWORD=$(dotenv_quote "$password")
SCREENLOOP_SECRET_KEY=$(dotenv_quote "$secret_key")
SCREENLOOP_ADVERTISE_HOST=$(dotenv_quote "$advertise_host")
SCREENLOOP_ADVERTISE_HOSTS=$(dotenv_quote "$advertise_hosts")
SCREENLOOP_MAX_UPLOAD_BYTES=2147483648
SCREENLOOP_ACCESS_LOG=true
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
echo "To update later, run: cd $INSTALL_DIR && ./update.sh"
