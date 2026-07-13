import hashlib
import json
import mimetypes
import subprocess
from pathlib import Path

from . import config
from .config import TRANSCODE_DIR
from .profiles import PROFILES, profile_or_default

VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm", ".wmv"}


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def media_digest(path: Path) -> str:
    stat = path.stat()
    key = f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def compressed_profile(profile: dict, compressed: bool = False) -> dict:
    if not compressed:
        return dict(profile)
    tuned = dict(profile)
    tuned["crf"] = max(int(tuned.get("crf", 22)) + 8, 30)
    tuned["max_width"] = min(int(tuned.get("max_width", 1920)), 1280)
    tuned["max_height"] = min(int(tuned.get("max_height", 1080)), 720)
    tuned["target_width"] = min(int(tuned.get("target_width") or tuned["max_width"]), 1280)
    tuned["target_height"] = min(int(tuned.get("target_height") or tuned["max_height"]), 720)
    tuned["maxrate"] = cap_bitrate(halve_bitrate(str(tuned.get("maxrate", "12000k"))), 3000)
    tuned["bufsize"] = cap_bitrate(halve_bitrate(str(tuned.get("bufsize", "24000k"))), 6000)
    tuned["audio_bitrate"] = lower_audio_bitrate(str(tuned.get("audio_bitrate", "160k")))
    tuned["preset"] = "medium"
    return tuned


def halve_bitrate(value: str) -> str:
    if not value.endswith("k"):
        return value
    try:
        return f"{max(1200, int(value[:-1]) // 2)}k"
    except ValueError:
        return value


def lower_audio_bitrate(value: str) -> str:
    if not value.endswith("k"):
        return value
    try:
        return f"{max(64, min(int(value[:-1]), 96))}k"
    except ValueError:
        return value


def cap_bitrate(value: str, max_kbit: int) -> str:
    if not value.endswith("k"):
        return value
    try:
        return f"{min(int(value[:-1]), max_kbit)}k"
    except ValueError:
        return value


def output_path(src: Path, profile_key: str, silent: bool = False, compressed: bool = False) -> Path:
    profile_key = profile_or_default(profile_key)
    profile = compressed_profile(PROFILES[profile_key]["ffmpeg"], compressed=compressed)
    digest = media_digest(src)
    profile_digest = hashlib.sha1(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:8]
    suffix = "".join((".silent" if silent else "", ".compressed" if compressed else ""))
    return TRANSCODE_DIR / profile_key / f"{src.stem}.{digest}.{profile_digest}{suffix}.safe.mp4"


def video_filter(profile: dict) -> str:
    if profile.get("exact_frame"):
        width = int(profile.get("target_width") or profile["max_width"])
        height = int(profile.get("target_height") or profile["max_height"])
        return (
            f"fps={profile['fps']},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,format=yuv420p"
        )
    return (
        f"fps={profile['fps']},"
        f"scale=w='min({profile['max_width']},iw)':"
        f"h='min({profile['max_height']},ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        "setsar=1,format=yuv420p"
    )


def has_audio_stream(src: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        str(src),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=config.FFPROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(data.get("streams"))


def probe_duration_seconds(src: Path) -> int | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(src),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=config.FFPROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "{}")
        duration = float(data.get("format", {}).get("duration") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return int(duration) if duration > 0 else None


def transcode(src: Path, profile_key: str, silent: bool = False, compressed: bool = False) -> Path:
    profile = compressed_profile(PROFILES[profile_or_default(profile_key)]["ffmpeg"], compressed=compressed)
    out = output_path(src, profile_key, silent=silent, compressed=compressed)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_name(out.name + ".tmp")

    vf = video_filter(profile)
    use_silent_audio = silent or not has_audio_stream(src)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
    ]
    if use_silent_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={profile.get('audio_sample_rate', 48000)}",
            ]
        )

    cmd.extend(
        [
        "-map",
        "0:v:0",
        "-map",
        "1:a:0" if use_silent_audio else "0:a:0?",
        "-vf",
        vf,
        "-c:v",
        profile["video_codec"],
        "-profile:v",
        profile.get("h264_profile", "high"),
        "-level:v",
        profile.get("h264_level", "4.1"),
        "-preset",
        profile.get("preset", "veryfast"),
        "-crf",
        str(profile["crf"]),
        "-maxrate",
        profile["maxrate"],
        "-bufsize",
        profile["bufsize"],
        "-c:a",
        profile["audio_codec"],
        "-ac",
        "2",
        "-ar",
        str(profile.get("audio_sample_rate", 48000)),
        "-b:a",
        profile["audio_bitrate"],
        "-shortest",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(tmp),
        ]
    )
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=config.TRANSCODE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg timed out after {config.TRANSCODE_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(result.stderr[-2000:] or "ffmpeg transcode failed")
    tmp.replace(out)
    return out
