import hashlib
import hmac
import secrets
import time

from . import config

try:
    import bcrypt
except Exception:  # pragma: no cover - fallback keeps local tooling usable without optional wheels.
    bcrypt = None


def secret_key() -> str:
    return config.SECRET_KEY or "screenloop-insecure-development-secret"


def _sign(value: str) -> str:
    return hmac.new(secret_key().encode(), value.encode(), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    if bcrypt:
        return "bcrypt$" + bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    if password_hash.startswith("bcrypt$") and bcrypt:
        return bcrypt.checkpw(password.encode(), password_hash.removeprefix("bcrypt$").encode())
    if password_hash.startswith("pbkdf2_sha256$"):
        _, salt, digest = password_hash.split("$", 2)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250_000).hex()
        return hmac.compare_digest(candidate, digest)
    return False


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def create_csrf_token(session_token: str = "", max_age_seconds: int = 12 * 60 * 60) -> str:
    expires_at = int(time.time()) + max_age_seconds
    nonce = secrets.token_urlsafe(16)
    payload = f"{expires_at}:{nonce}:{token_hash(session_token) if session_token else ''}"
    return f"{payload}:{_sign(payload)}"


def verify_csrf_token(token: str | None, session_token: str = "") -> bool:
    if not token:
        return False
    parts = token.split(":", 3)
    if len(parts) != 4:
        return False
    expires_at, nonce, session_hash, signature = parts
    expected_session_hash = token_hash(session_token) if session_token else ""
    if not hmac.compare_digest(session_hash, expected_session_hash):
        return False
    payload = f"{expires_at}:{nonce}:{session_hash}"
    try:
        if int(expires_at) < time.time():
            return False
    except ValueError:
        return False
    return hmac.compare_digest(signature, _sign(payload))


def create_stream_token(media_id: int, profile: str, max_age_seconds: int = 24 * 60 * 60) -> str:
    expires_at = int(time.time()) + max_age_seconds
    payload = f"{media_id}:{profile}:{expires_at}"
    return f"{expires_at}:{_sign(payload)}"


def verify_stream_token(media_id: int, profile: str, token: str | None) -> bool:
    if not token:
        return False
    parts = token.split(":", 1)
    if len(parts) != 2:
        return False
    expires_at, signature = parts
    try:
        if int(expires_at) < time.time():
            return False
    except ValueError:
        return False
    payload = f"{media_id}:{profile}:{expires_at}"
    return hmac.compare_digest(signature, _sign(payload))


def stream_query(media_id: int, profile: str) -> str:
    token = create_stream_token(media_id, profile)
    return f"profile={profile}&token={token}"
