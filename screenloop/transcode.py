import hashlib
import json
import mimetypes
import subprocess
from pathlib import Path

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


def output_path(src: Path, profile_key: str, silent: bool = False) -> Path:
    profile_key = profile_or_default(profile_key)
    profile = PROFILES[profile_key]["ffmpeg"]
    digest = media_digest(src)
    profile_digest = hashlib.sha1(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:8]
    suffix = ".silent" if silent else ""
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
    result = subprocess.run(cmd, capture_output=True, text=True)
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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "{}")
        duration = float(data.get("format", {}).get("duration") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return int(duration) if duration > 0 else None


def transcode(src: Path, profile_key: str, silent: bool = False) -> Path:
    profile = PROFILES[profile_or_default(profile_key)]["ffmpeg"]
    out = output_path(src, profile_key, silent=silent)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return out

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
        "high",
        "-level:v",
        "4.1",
        "-preset",
        "veryfast",
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
        str(out),
        ]
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "ffmpeg transcode failed")
    return out
