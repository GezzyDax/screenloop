# TV templates

**English** | [Русский](tv-templates.ru.md)

A TV profile in Screenloop is a plain `.toml` file, not code. Adding support for your model needs no Python change and no waiting for a release: drop the file in and it works.

There are hundreds of DLNA renderers, each with its own ceilings for bitrate, resolution, and H.264 profile. The maintainers cannot test them all — the only person with your TV is you. So working out the settings for a specific model is up to its owner, and the format is designed so that takes no programming.

## Where templates come from

| Directory | Contents | Writable |
|---|---|---|
| `screenloop/builtin_templates/` | The five built-in templates, shipped with the app | no |
| `<data_dir>/profiles/` | Your own and community-installed templates | yes |

Both directories are read at startup and merged into one list. The file name minus `.toml` is the template id (`sony_bravia.toml` → `sony_bravia`). The id comes from the file name rather than a field inside the file, so the on-disk location is always authoritative.

A custom template cannot shadow a built-in one: a file with a colliding name is rejected with an error in the log.

## Adding a template

**From the panel** (Templates → Add a template) — upload a `.toml` or import it by URL. It becomes usable immediately, no restart.

**By hand** — drop the file into `<data_dir>/profiles/` and restart the service. In Docker that is `/data/profiles` inside the `screenloop-data` volume:

```bash
docker cp sony_bravia.toml screenloop:/data/profiles/
docker restart screenloop
```

**From the community catalog** — set `SCREENLOOP_COMMUNITY_CATALOG_CHECK=true` and the panel lists templates contributed by other users. Off by default: without the flag Screenloop makes no outbound request at all. Import by URL and file upload do not depend on this flag.

## Format

```toml
name = "Sony Bravia X-series"
match = ["sony", "bravia"]
priority = 0
mime_type = "video/mp4"
dlna_protocol_info = "http-get:*:video/mp4:DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"
probe_port = 52323

[ffmpeg]
video_codec = "libx264"
h264_profile = "high"
h264_level = "4.1"
audio_codec = "aac"
audio_sample_rate = 48000
add_silent_audio = true
max_width = 1920
max_height = 1080
target_width = 1920
target_height = 1080
exact_frame = true
fps = 30
crf = 22
maxrate = "12000k"
bufsize = "24000k"
audio_bitrate = "160k"

[meta]
author = "your-github-handle"
tested_on = "Sony Bravia XR-55A80L, firmware PKG6.7370"
notes = "Stutters without a strict 30 fps"
```

### Top level

| Field | Required | Default | What it means |
|---|---|---|---|
| `name` | yes | — | Human-readable name shown in the panel. |
| `match` | no | `[]` | Tokens used to pick this template automatically. Matched as lowercase substrings against the manufacturer, model, and friendly name from the DLNA response. |
| `priority` | no | `0` | Which template is checked first when several match. Higher goes first. |
| `mime_type` | no | `video/mp4` | MIME type advertised to the TV. |
| `dlna_protocol_info` | no | filled in automatically | The `protocolInfo` string in the DIDL payload. Older TVs need an explicit `DLNA.ORG_PN`. |
| `probe_port` | no | `9197` | TCP port used for a quick "is the TV alive" check. |

About `probe_port`: it is used **only** as a pre-flight reachability check before polling. Neither SSDP discovery nor the command path depends on it. Get it wrong and at worst the TV shows offline for one cycle before Screenloop finds it again through normal SSDP. That is why the field is optional — you do not need to guess it exactly.

### The `[ffmpeg]` section

| Field | Required | Default | What it means |
|---|---|---|---|
| `video_codec` | yes | — | `libx264` only. |
| `audio_codec` | yes | — | `aac` only. |
| `max_width` | yes | — | Maximum width, 320–3840. |
| `max_height` | yes | — | Maximum height, 240–2160. |
| `fps` | yes | — | Frame rate, 1–60. |
| `crf` | yes | — | Quality, 0–51. Lower is better and heavier. 22 is a sane starting point. |
| `maxrate` | yes | — | Bitrate ceiling, for example `"12000k"`. |
| `bufsize` | yes | — | Buffer size, usually twice `maxrate`. |
| `audio_bitrate` | yes | — | Audio bitrate, for example `"160k"`. |
| `h264_profile` | no | `high` | `baseline`, `main`, or `high`. Older TVs choke on `high`. |
| `h264_level` | no | `4.1` | H.264 level. |
| `audio_sample_rate` | no | `48000` | Audio sample rate. |
| `container` | no | `mp4` | Output container. |
| `add_silent_audio` | no | `true` | Add a silent track to clips with no audio. Many TVs refuse to play video with no audio stream at all. |
| `target_width` | no | `max_width` | Exact frame width when `exact_frame` is on. |
| `target_height` | no | `max_height` | Exact frame height when `exact_frame` is on. |
| `exact_frame` | no | `false` | Pad every clip to one frame size with black bars. Helps TVs that stumble when the resolution changes between playlist items. |

### The `[meta]` section

Optional and purely descriptive — it never affects playback. Record the model and firmware you tested on: that is the single most useful thing for anyone else with the same TV.

## Working out the settings for your TV

1. Copy `generic_dlna` as a starting point and rename the file after your model.
2. Fill in `name` and `match` with the vendor and product line. The **TVs** page shows what the TV reports about itself after a scan.
3. Try it as is. If it plays, you are done.
4. If it does not, relax one constraint at a time:
   - Audio but no picture → `h264_profile = "main"`, then `"baseline"`, `h264_level = "4.0"`.
   - Stuttering and stalling → lower `maxrate` and `bufsize` (for example `8000k` / `16000k`).
   - 1080p is too much → `max_width = 1280`, `max_height = 720`.
   - First clip plays, second does not → `exact_frame = true`.
   - Silent clips will not start → `add_silent_audio = true`.
5. After each change re-upload the template and rebuild the clip's transcode on the **Transcode** page: the ffmpeg settings are part of the cache filename, so an old copy will not refresh on its own.

## Validation

Templates are validated at load and on import. Errors come back as a list naming the specific field — `ffmpeg.crf must be between 0 and 51` rather than an opaque failure. A broken template never reaches playback: at startup it is skipped with a log line, on import it is rejected and nothing is written.

Limits worth knowing up front:

- The id (file name) allows lowercase letters, digits, and `_`, up to 40 characters.
- Files are capped at 16 KB.
- `video_codec` and `audio_codec` are allow-listed. The ffmpeg command is built as an argument list with no shell, so nothing can be injected there; the allow-list exists so a broken template fails loudly instead of producing a silently wrong encode.

## Sharing a template

If you worked out settings for a TV that is not on the list, send the template to the community repository [screenloop-templates](https://github.com/GezzyDax/screenloop-templates) as a pull request. Fill in `[meta]`: model, firmware, and what you had to change relative to `generic_dlna`. Nobody else has your model — this is the most useful contribution to the project.
