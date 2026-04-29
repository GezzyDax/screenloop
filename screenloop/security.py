import hashlib
import hmac
import secrets
import time

from . import config


def secret_key() -> str:
    return config.SECRET_KEY or "screenloop-insecure-development-secret"


def _sign(value: str) -> str:
    return hmac.new(secret_key().encode(), value.encode(), hashlib.sha256).hexdigest()


def create_csrf_token(max_age_seconds: int = 12 * 60 * 60) -> str:
    expires_at = int(time.time()) + max_age_seconds
    nonce = secrets.token_urlsafe(16)
    payload = f"{expires_at}:{nonce}"
    return f"{payload}:{_sign(payload)}"


def verify_csrf_token(token: str | None) -> bool:
    if not token:
        return False
    parts = token.split(":", 2)
    if len(parts) != 3:
        return False
    expires_at, nonce, signature = parts
    payload = f"{expires_at}:{nonce}"
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
