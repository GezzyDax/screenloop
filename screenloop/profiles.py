"""TV profile templates.

Profiles are plain TOML files instead of Python code, so adding support for an
unsupported TV never requires a backend release. Two directories are merged:

- ``screenloop/builtin_templates`` ships with the app and is read-only.
- ``config.PROFILES_DIR`` holds user-installed and community templates.

The file name (minus ``.toml``) is the profile id. Keeping the id out of the
file body makes the on-disk location authoritative and removes a class of
spoofing bugs where a declared id disagrees with where the file is stored.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

from . import config

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin_templates"

DEFAULT_PROFILE = "generic_dlna"
MAX_TEMPLATE_BYTES = 16 * 1024
ID_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")

ALLOWED_VIDEO_CODECS = {"libx264"}
ALLOWED_AUDIO_CODECS = {"aac"}

REQUIRED_FFMPEG_FIELDS = (
    "video_codec",
    "audio_codec",
    "max_width",
    "max_height",
    "fps",
    "crf",
    "maxrate",
    "bufsize",
    "audio_bitrate",
)

FFMPEG_DEFAULTS: dict[str, Any] = {
    "container": "mp4",
    "h264_profile": "high",
    "h264_level": "4.1",
    "audio_sample_rate": 48000,
    "add_silent_audio": True,
    "exact_frame": False,
}

# Mutated in place by reload_profiles(); never reassigned. Every call site does
# `from .profiles import PROFILES` and holds a reference to this exact object.
PROFILES: dict[str, dict[str, Any]] = {}


class TemplateError(ValueError):
    """Raised when a template cannot be parsed or fails validation."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _bitrate_error(field: str, value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2,6}k", value):
        return f"ffmpeg.{field} must look like '12000k'"
    return None


def _int_range_error(field: str, value: Any, low: int, high: int) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"ffmpeg.{field} must be an integer"
    if not low <= value <= high:
        return f"ffmpeg.{field} must be between {low} and {high}"
    return None


def validate_template(data: Any, template_id: str) -> list[str]:
    """Return a list of human-readable problems; empty means the template is usable."""
    errors: list[str] = []

    if not ID_PATTERN.fullmatch(template_id):
        errors.append(f"id '{template_id}' must match [a-z0-9_] and be 1-40 characters long")
    if not isinstance(data, dict):
        return errors + ["template must be a TOML table"]

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name is required and must be a non-empty string")

    match = data.get("match", [])
    if not isinstance(match, list) or any(not isinstance(token, str) or not token.strip() for token in match):
        errors.append("match must be a list of non-empty strings")

    priority = data.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        errors.append("priority must be an integer")

    for field in ("mime_type", "dlna_protocol_info"):
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{field} must be a non-empty string when present")

    probe_port = data.get("probe_port", 9197)
    if isinstance(probe_port, bool) or not isinstance(probe_port, int) or not 1 <= probe_port <= 65535:
        errors.append("probe_port must be an integer between 1 and 65535")

    ffmpeg = data.get("ffmpeg")
    if not isinstance(ffmpeg, dict):
        return errors + ["[ffmpeg] section is required"]

    for field in REQUIRED_FFMPEG_FIELDS:
        if field not in ffmpeg:
            errors.append(f"ffmpeg.{field} is required")

    if "video_codec" in ffmpeg and ffmpeg["video_codec"] not in ALLOWED_VIDEO_CODECS:
        errors.append(f"ffmpeg.video_codec must be one of {sorted(ALLOWED_VIDEO_CODECS)}")
    if "audio_codec" in ffmpeg and ffmpeg["audio_codec"] not in ALLOWED_AUDIO_CODECS:
        errors.append(f"ffmpeg.audio_codec must be one of {sorted(ALLOWED_AUDIO_CODECS)}")

    checks: tuple[tuple[str, int, int], ...] = (
        ("max_width", 320, 3840),
        ("max_height", 240, 2160),
        ("target_width", 320, 3840),
        ("target_height", 240, 2160),
        ("fps", 1, 60),
        ("crf", 0, 51),
        ("audio_sample_rate", 8000, 192000),
    )
    for field, low, high in checks:
        if field in ffmpeg:
            error = _int_range_error(field, ffmpeg[field], low, high)
            if error:
                errors.append(error)

    for field in ("maxrate", "bufsize", "audio_bitrate"):
        if field in ffmpeg:
            error = _bitrate_error(field, ffmpeg[field])
            if error:
                errors.append(error)

    for field in ("add_silent_audio", "exact_frame"):
        if field in ffmpeg and not isinstance(ffmpeg[field], bool):
            errors.append(f"ffmpeg.{field} must be true or false")

    for field in ("container", "h264_profile", "h264_level"):
        if field in ffmpeg and (not isinstance(ffmpeg[field], str) or not ffmpeg[field].strip()):
            errors.append(f"ffmpeg.{field} must be a non-empty string")

    return errors


def build_profile(data: dict[str, Any], template_id: str, source: str) -> dict[str, Any]:
    """Turn validated template data into the runtime profile dict."""
    ffmpeg = {**FFMPEG_DEFAULTS, **data["ffmpeg"]}
    ffmpeg.setdefault("target_width", ffmpeg["max_width"])
    ffmpeg.setdefault("target_height", ffmpeg["max_height"])

    profile: dict[str, Any] = {
        "name": str(data["name"]).strip(),
        "ffmpeg": ffmpeg,
        "mime_type": data.get("mime_type") or "video/mp4",
        "probe_port": int(data.get("probe_port", 9197)),
        "match": [str(token).strip().lower() for token in data.get("match", [])],
        "priority": int(data.get("priority", 0)),
        "source": source,
        "id": template_id,
    }
    if data.get("dlna_protocol_info"):
        profile["dlna_protocol_info"] = data["dlna_protocol_info"]
    meta = data.get("meta")
    if isinstance(meta, dict):
        profile["meta"] = {str(key): str(value) for key, value in meta.items()}
    return profile


def parse_template(raw: bytes, template_id: str) -> dict[str, Any]:
    """Parse and validate raw TOML bytes, raising TemplateError on any problem."""
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise TemplateError([f"template is larger than {MAX_TEMPLATE_BYTES} bytes"])
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise TemplateError(["template must be UTF-8 encoded"]) from None
    except tomllib.TOMLDecodeError as exc:
        raise TemplateError([f"invalid TOML: {exc}"]) from None

    errors = validate_template(data, template_id)
    if errors:
        raise TemplateError(errors)
    return data


def builtin_ids() -> set[str]:
    return {path.stem for path in BUILTIN_DIR.glob("*.toml")}


def _load_dir(directory: Path, source: str, into: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not directory.is_dir():
        return errors
    for path in sorted(directory.glob("*.toml")):
        template_id = path.stem
        if source == "custom" and template_id in into:
            errors.append(f"{path.name}: id collides with the built-in template '{template_id}'")
            continue
        try:
            data = parse_template(path.read_bytes(), template_id)
        except TemplateError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        into[template_id] = build_profile(data, template_id, source)
    return errors


def load_profiles() -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read both template directories and return the merged profiles plus any errors."""
    merged: dict[str, dict[str, Any]] = {}
    errors = _load_dir(BUILTIN_DIR, "builtin", merged)
    errors += _load_dir(config.PROFILES_DIR, "custom", merged)
    return merged, errors


def reload_profiles() -> list[str]:
    """Refresh PROFILES in place. Returns problems found in individual templates."""
    merged, errors = load_profiles()
    if DEFAULT_PROFILE not in merged:
        raise RuntimeError(f"built-in template '{DEFAULT_PROFILE}' is missing or invalid: {'; '.join(errors)}")
    PROFILES.clear()
    PROFILES.update(merged)
    return errors


def detect_profile(*values: str | None) -> str:
    haystack = " ".join(v or "" for v in values).lower()
    if "samsung" in haystack and "tizen" not in haystack and "samsung_legacy" in PROFILES:
        return "samsung_legacy"
    ordered = sorted(PROFILES.items(), key=lambda item: (-int(item[1].get("priority", 0)), item[0]))
    for key, profile in ordered:
        if key == DEFAULT_PROFILE:
            continue
        if any(token in haystack for token in profile["match"]):
            return key
    return DEFAULT_PROFILE


def profile_or_default(profile: str | None) -> str:
    return profile if profile in PROFILES else DEFAULT_PROFILE


reload_profiles()
