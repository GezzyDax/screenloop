import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    old_name = name.replace("SCREENLOOP_", "GEZZDLNA_", 1)
    return os.environ.get(name, os.environ.get(old_name, default))


def _path(name: str, default: str) -> Path:
    return Path(_env(name, default)).expanduser()


DATA_DIR = _path("SCREENLOOP_DATA_DIR", str(Path.home() / ".local" / "share" / "screenloop"))
DB_PATH = _path("SCREENLOOP_DB_PATH", str(DATA_DIR / "db" / "screenloop.sqlite3"))
MEDIA_DIR = _path("SCREENLOOP_MEDIA_DIR", str(DATA_DIR / "media"))
TRANSCODE_DIR = _path("SCREENLOOP_TRANSCODE_DIR", str(DATA_DIR / "transcoded"))

HTTP_HOST = _env("SCREENLOOP_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(_env("SCREENLOOP_HTTP_PORT", "8099"))
ADVERTISE_HOST = _env("SCREENLOOP_ADVERTISE_HOST", "")
ADVERTISE_HOSTS = tuple(
    host.strip()
    for host in _env("SCREENLOOP_ADVERTISE_HOSTS", ADVERTISE_HOST).split(",")
    if host.strip()
)

BASIC_AUTH_USER = _env("SCREENLOOP_USER", "admin")
BASIC_AUTH_PASSWORD = _env("SCREENLOOP_PASSWORD", "")
BOOTSTRAP_USER = _env("SCREENLOOP_BOOTSTRAP_USER", BASIC_AUTH_USER or "admin")
BOOTSTRAP_PASSWORD = _env("SCREENLOOP_BOOTSTRAP_PASSWORD", BASIC_AUTH_PASSWORD)
SECRET_KEY = _env("SCREENLOOP_SECRET_KEY", "")
ALLOW_INSECURE_AUTH = _env("SCREENLOOP_ALLOW_INSECURE_AUTH", "").lower() in {"1", "true", "yes", "on"}
MAX_UPLOAD_BYTES = int(_env("SCREENLOOP_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
SESSION_TTL_SECONDS = int(_env("SCREENLOOP_SESSION_TTL_SECONDS", str(12 * 60 * 60)))
COOKIE_SECURE = _env("SCREENLOOP_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
PUBLIC_URL = _env("SCREENLOOP_PUBLIC_URL", "")
TRUSTED_PROXY_CIDRS = tuple(
    item.strip()
    for item in _env("SCREENLOOP_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128").split(",")
    if item.strip()
)
ALLOWED_TV_CIDRS = tuple(
    item.strip()
    for item in _env("SCREENLOOP_ALLOWED_TV_CIDRS", "").split(",")
    if item.strip()
)
ACCESS_LOG = _env("SCREENLOOP_ACCESS_LOG", "true").lower() not in {"0", "false", "no", "off"}
UPDATE_CHECK = _env("SCREENLOOP_UPDATE_CHECK", "false").lower() in {"1", "true", "yes", "on"}
UPDATE_CHECK_URL = _env("SCREENLOOP_UPDATE_CHECK_URL", "https://api.github.com/repos/GezzyDax/screenloop/releases/latest")
UPDATE_CHECK_INTERVAL_SECONDS = int(_env("SCREENLOOP_UPDATE_CHECK_INTERVAL_SECONDS", str(6 * 60 * 60)))

OFFLINE_POLL = int(_env("SCREENLOOP_OFFLINE_POLL", "10"))
ONLINE_POLL = int(_env("SCREENLOOP_ONLINE_POLL", "30"))
DLNA_WARMUP = int(_env("SCREENLOOP_DLNA_WARMUP", "8"))
AUTO_ADVANCE_REPLAY_AFTER = int(_env("SCREENLOOP_AUTO_ADVANCE_REPLAY_AFTER", "8"))
AUTO_ADVANCE_UNKNOWN_DURATION_AFTER = int(_env("SCREENLOOP_AUTO_ADVANCE_UNKNOWN_DURATION_AFTER", "60"))
AUTO_ADVANCE_REPLAY_COOLDOWN = int(_env("SCREENLOOP_AUTO_ADVANCE_REPLAY_COOLDOWN", "30"))
PUSH_COOLDOWN = int(_env("SCREENLOOP_PUSH_COOLDOWN", "5"))


def validate_security_config() -> None:
    if not SECRET_KEY and not ALLOW_INSECURE_AUTH:
        raise RuntimeError(
            "SCREENLOOP_SECRET_KEY is required for signed stream URLs and CSRF protection. "
            "Set a long random value or explicitly set SCREENLOOP_ALLOW_INSECURE_AUTH=true for local testing."
        )
    if not ALLOW_INSECURE_AUTH and len(SECRET_KEY) < 16:
        raise RuntimeError(
            "Refusing to start with a short SCREENLOOP_SECRET_KEY. "
            "Use at least 16 characters or explicitly set SCREENLOOP_ALLOW_INSECURE_AUTH=true for local testing."
        )


def validate_bootstrap_password() -> None:
    weak_passwords = {"", "admin", "password", "change-me", "changeme", "1234", "screenloop"}
    if not ALLOW_INSECURE_AUTH and BOOTSTRAP_PASSWORD in weak_passwords:
        raise RuntimeError(
            "Refusing to create bootstrap admin with an empty/default password. "
            "Set SCREENLOOP_BOOTSTRAP_PASSWORD to a strong value."
        )
    if not ALLOW_INSECURE_AUTH and len(BOOTSTRAP_PASSWORD) < 12:
        raise RuntimeError(
            "Refusing to create bootstrap admin with a short password. "
            "Use at least 12 characters or explicitly set SCREENLOOP_ALLOW_INSECURE_AUTH=true for local testing."
        )


def ensure_dirs() -> None:
    for path in (DB_PATH.parent, MEDIA_DIR, TRANSCODE_DIR):
        path.mkdir(parents=True, exist_ok=True)
