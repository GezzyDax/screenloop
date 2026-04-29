PROFILES = {
    "lg_netcast": {
        "name": "LG NetCast (pre-webOS)",
        "ffmpeg": {
            "container": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "add_silent_audio": True,
            "max_width": 1920,
            "max_height": 1080,
            "target_width": 1920,
            "target_height": 1080,
            "exact_frame": True,
            "fps": 30,
            "crf": 22,
            "maxrate": "12000k",
            "bufsize": "24000k",
            "audio_bitrate": "160k",
        },
        "probe_port": 1925,
        "match": ["netcast"],
    },
    "generic_dlna": {
        "name": "Generic DLNA",
        "ffmpeg": {
            "container": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "add_silent_audio": True,
            "max_width": 1920,
            "max_height": 1080,
            "target_width": 1920,
            "target_height": 1080,
            "exact_frame": True,
            "fps": 30,
            "crf": 22,
            "maxrate": "12000k",
            "bufsize": "24000k",
            "audio_bitrate": "160k",
        },
        "probe_port": 9197,
        "match": [],
    },
    "lg_webos": {
        "name": "LG webOS",
        "ffmpeg": {
            "container": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "add_silent_audio": True,
            "max_width": 1920,
            "max_height": 1080,
            "target_width": 1920,
            "target_height": 1080,
            "exact_frame": True,
            "fps": 30,
            "crf": 22,
            "maxrate": "12000k",
            "bufsize": "24000k",
            "audio_bitrate": "160k",
        },
        "probe_port": 9197,
        "match": ["lg", "webos"],
    },
    "samsung_tizen": {
        "name": "Samsung Tizen",
        "ffmpeg": {
            "container": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "add_silent_audio": True,
            "max_width": 1920,
            "max_height": 1080,
            "target_width": 1920,
            "target_height": 1080,
            "exact_frame": True,
            "fps": 30,
            "crf": 22,
            "maxrate": "14000k",
            "bufsize": "28000k",
            "audio_bitrate": "160k",
        },
        "probe_port": 8001,
        "match": ["samsung", "tizen"],
    },
    "samsung_legacy": {
        "name": "Samsung Legacy Smart TV",
        "ffmpeg": {
            "container": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "add_silent_audio": True,
            "max_width": 1920,
            "max_height": 1080,
            "target_width": 1920,
            "target_height": 1080,
            "exact_frame": True,
            "fps": 30,
            "crf": 22,
            "maxrate": "12000k",
            "bufsize": "24000k",
            "audio_bitrate": "160k",
        },
        "probe_port": 7676,
        "match": ["samsung"],
    },
}


def detect_profile(*values: str | None) -> str:
    haystack = " ".join(v or "" for v in values).lower()
    if "samsung" in haystack and "tizen" not in haystack:
        return "samsung_legacy"
    for key, profile in PROFILES.items():
        if key == "generic_dlna":
            continue
        if any(token in haystack for token in profile["match"]):
            return key
    return "generic_dlna"


def profile_or_default(profile: str | None) -> str:
    return profile if profile in PROFILES else "generic_dlna"
