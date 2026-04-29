#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_NAME = "Screenloop Legacy CLI"
USER_AGENT = "Screenloop/2.0 UPnP/1.0 DLNADOC/1.50"
AVTRANSPORT_SERVICE = "urn:schemas-upnp-org:service:AVTransport:1"
CACHE_DIR = Path.home() / ".cache" / "screenloop"
CONTROL_CACHE = CACHE_DIR / "control_urls.json"
TRANSCODE_DIR = CACHE_DIR / "transcoded"
CHUNK_SIZE = 1024 * 1024

OFFLINE_POLL = 10   # seconds between checks when TV is unreachable
ONLINE_POLL = 30    # seconds between playback state checks when TV is online
DLNA_WARMUP = 8     # seconds to wait after TCP comes up before DLNA services are ready
DEFAULT_PROBE_PORT = 9197  # LG WebOS; derived from control URL once discovered

RESTART_STATES = {"STOPPED", "NO_MEDIA_PRESENT"}


def log(msg: str):
    print(msg, flush=True)


def ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCODE_DIR.mkdir(parents=True, exist_ok=True)


def load_control_cache():
    if not CONTROL_CACHE.exists():
        return {}
    try:
        return json.loads(CONTROL_CACHE.read_text())
    except Exception:
        return {}


def save_control_cache(data):
    ensure_dirs()
    CONTROL_CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_local_ip_for(tv_ip: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((tv_ip, 1900))
        return s.getsockname()[0]
    finally:
        s.close()


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime

    ext = path.suffix.lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".avi":
        return "video/x-msvideo"
    if ext == ".ts":
        return "video/mp2t"

    return "application/octet-stream"


def safe_output_path(src: Path) -> Path:
    st = src.stat()
    key = f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return TRANSCODE_DIR / f"{src.stem}.{digest}.safe.mp4"


def transcode_safe(src: Path) -> Path:
    ensure_dirs()
    out = safe_output_path(src)

    if out.exists() and out.stat().st_size > 0:
        log(f"[+] Safe transcode exists: {out}")
        return out

    log("[+] Transcoding to TV-safe MP4: H.264 1080p30 AAC")
    log(f"[+] Output: {out}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-vf",
        "fps=30,scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-preset", "veryfast",
        "-crf", "22",
        "-maxrate", "12000k",
        "-bufsize", "24000k",
        "-c:a", "aac",
        "-ac", "2",
        "-b:a", "160k",
        "-movflags", "+faststart",
        str(out),
    ]

    p = subprocess.run(cmd)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg transcode failed")

    return out


class SingleFileHandler(BaseHTTPRequestHandler):
    file_path: Path = None
    public_name: str = None
    mime_type: str = None

    server_version = "ScreenloopHTTP/2.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        log("[HTTP] " + fmt % args)

    def do_HEAD(self):
        self.serve_file(send_body=False)

    def do_GET(self):
        self.serve_file(send_body=True)

    def do_POST(self):
        self.send_error(405, "Method Not Allowed")

    def serve_file(self, send_body: bool):
        parsed = urllib.parse.urlparse(self.path)
        requested = urllib.parse.unquote(parsed.path).lstrip("/")

        if requested != self.public_name:
            self.send_error(404, "Not Found")
            return

        file_size = self.file_path.stat().st_size
        range_header = self.headers.get("Range")

        start = 0
        end = file_size - 1
        status = 200

        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                status = 206
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))

                if start > end or start >= file_size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return

        length = end - start + 1

        self.send_response(status)
        self.send_header("Content-Type", self.mime_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Connection", "close")
        self.send_header("Server", "Screenloop/2.0")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("transferMode.dlna.org", "Streaming")

        if self.mime_type == "video/mp4":
            self.send_header(
                "contentFeatures.dlna.org",
                "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            )

        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")

        self.end_headers()

        if not send_body:
            return

        try:
            with self.file_path.open("rb") as f:
                f.seek(start)
                remaining = length

                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        except (BrokenPipeError, ConnectionResetError, OSError):
            log("[HTTP] TV closed connection")


def start_http_server(file_path: Path, bind_ip: str, port: int):
    public_name = file_path.name
    mime_type = guess_mime(file_path)

    handler = type(
        "VideoHandler",
        (SingleFileHandler,),
        {
            "file_path": file_path,
            "public_name": public_name,
            "mime_type": mime_type,
        },
    )

    server = ThreadingHTTPServer((bind_ip, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    encoded = urllib.parse.quote(public_name)
    url = f"http://{bind_ip}:{port}/{encoded}"

    log(f"[+] HTTP server: {url}")
    log(f"[+] MIME: {mime_type}")

    return server, url, mime_type


def parse_ssdp_response(data: bytes):
    text = data.decode("utf-8", errors="ignore")
    headers = {}

    for line in text.splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    return headers


def ssdp_discover(tv_ip: str, bind_ip: str, timeout: float = 5.0):
    targets = [
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "urn:schemas-upnp-org:service:AVTransport:1",
        "ssdp:all",
    ]

    locations = []

    for st in targets:
        msg = "\r\n".join(
            [
                "M-SEARCH * HTTP/1.1",
                "HOST: 239.255.255.250:1900",
                'MAN: "ssdp:discover"',
                "MX: 2",
                f"ST: {st}",
                f"USER-AGENT: {USER_AGENT}",
                "",
                "",
            ]
        ).encode()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(1.0)

        try:
            sock.bind((bind_ip, 0))
            sock.sendto(msg, ("239.255.255.250", 1900))

            started = time.time()
            while time.time() - started < timeout:
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                headers = parse_ssdp_response(data)
                location = headers.get("location")

                if not location:
                    continue

                if addr[0] == tv_ip or tv_ip in location:
                    if location not in locations:
                        locations.append(location)

        finally:
            sock.close()

    return locations


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find_text(parent, child_name: str):
    for child in parent:
        if local_name(child.tag) == child_name:
            return child.text or ""
    return ""


def fetch_url(url: str, timeout: int = 8):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_avtransport_control_url(location: str):
    log(f"[+] Fetch device description: {location}")

    xml_data = fetch_url(location)
    root = ET.fromstring(xml_data)

    url_base = None
    for elem in root.iter():
        if local_name(elem.tag) == "URLBase" and elem.text:
            url_base = elem.text.strip()
            break

    if not url_base:
        parsed = urllib.parse.urlparse(location)
        url_base = f"{parsed.scheme}://{parsed.netloc}/"

    for service in root.iter():
        if local_name(service.tag) != "service":
            continue

        service_type = find_text(service, "serviceType")
        control_url = find_text(service, "controlURL")

        if "AVTransport" in service_type and control_url:
            return urllib.parse.urljoin(url_base, control_url)

    return None


def test_control_url(control_url: str):
    inner = f"""
<u:GetTransportInfo xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
</u:GetTransportInfo>
"""
    try:
        soap_request(control_url, "GetTransportInfo", inner, quiet=True)
        return True
    except Exception:
        return False


def discover_control_url(tv_ip: str, bind_ip: str, ignore_cache: bool = False):
    cache = load_control_cache()
    cache_key = f"{tv_ip}|{bind_ip}"

    if not ignore_cache and cache_key in cache:
        cached = cache[cache_key]
        log(f"[+] Cached AVTransport controlURL: {cached}")
        if test_control_url(cached):
            return cached
        log("[!] Cached controlURL is dead, rediscovering")

    locations = ssdp_discover(tv_ip, bind_ip)

    if not locations:
        raise RuntimeError("SSDP не нашёл DLNA/UPnP MediaRenderer")

    log("[+] SSDP locations:")
    for loc in locations:
        log(f"    {loc}")

    for location in locations:
        for attempt in range(1, 4):
            try:
                control_url = get_avtransport_control_url(location)
                if control_url:
                    cache[cache_key] = control_url
                    save_control_cache(cache)
                    return control_url
            except Exception as e:
                log(f"[!] Failed {location}, attempt {attempt}/3: {e}")
                time.sleep(0.5)

    raise RuntimeError("Не найден AVTransport controlURL")


def soap_request(control_url: str, action: str, inner_xml: str, quiet: bool = False):
    envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope
  xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
  s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    {inner_xml}
  </s:Body>
</s:Envelope>
"""

    data = envelope.encode()

    req = urllib.request.Request(
        control_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{AVTRANSPORT_SERVICE}#{action}"',
            "User-Agent": USER_AGENT,
            "Content-Length": str(len(data)),
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            if not quiet:
                log(f"[+] SOAP {action}: HTTP {r.status}")
            return body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"SOAP {action} failed: HTTP {e.code}\n{body}") from e


def make_didl(media_url: str, title: str, mime_type: str):
    escaped_url = html.escape(media_url, quote=True)
    escaped_title = html.escape(title, quote=True)

    protocol_info = f"http-get:*:{mime_type}:*"

    return f"""<DIDL-Lite
 xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <item id="1" parentID="0" restricted="1">
    <dc:title>{escaped_title}</dc:title>
    <upnp:class>object.item.videoItem</upnp:class>
    <res protocolInfo="{protocol_info}">{escaped_url}</res>
  </item>
</DIDL-Lite>"""


def stop(control_url: str):
    inner = f"""
<u:Stop xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
</u:Stop>
"""
    try:
        soap_request(control_url, "Stop", inner)
    except Exception as e:
        log(f"[!] Stop ignored: {e}")


def set_uri(control_url: str, media_url: str, title: str, mime_type: str):
    didl = make_didl(media_url, title, mime_type)

    inner = f"""
<u:SetAVTransportURI xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
  <CurrentURI>{html.escape(media_url, quote=True)}</CurrentURI>
  <CurrentURIMetaData>{html.escape(didl, quote=True)}</CurrentURIMetaData>
</u:SetAVTransportURI>
"""
    soap_request(control_url, "SetAVTransportURI", inner)


def play(control_url: str):
    inner = f"""
<u:Play xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
  <Speed>1</Speed>
</u:Play>
"""
    soap_request(control_url, "Play", inner)


def probe_port_for(control_url: str) -> int:
    parsed = urllib.parse.urlparse(control_url)
    return parsed.port or DEFAULT_PROBE_PORT


def tv_is_reachable(tv_ip: str, probe_port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((tv_ip, probe_port), timeout=timeout):
            return True
    except OSError:
        return False


def get_transport_state(control_url: str) -> str:
    inner = f"""
<u:GetTransportInfo xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
</u:GetTransportInfo>
"""
    body = soap_request(control_url, "GetTransportInfo", inner, quiet=True)
    root = ET.fromstring(body)
    for elem in root.iter():
        if local_name(elem.tag) == "CurrentTransportState":
            return elem.text or "UNKNOWN"
    return "UNKNOWN"


def push_video(control_url: str, media_url: str, file_name: str, mime_type: str, no_stop: bool):
    if not no_stop:
        stop(control_url)
    set_uri(control_url, media_url, file_name, mime_type)
    play(control_url)
    log("[+] Play command sent")


def watch_and_push(
    tv_ip: str,
    file_path: Path,
    bind_ip: str,
    port: int,
    safe: bool,
    ignore_cache: bool,
    no_stop: bool,
):
    if safe:
        file_path = transcode_safe(file_path)

    server, media_url, mime_type = start_http_server(file_path, bind_ip, port)

    tv_online = False
    control_url = None

    cache = load_control_cache()
    cached_url = cache.get(f"{tv_ip}|{bind_ip}")
    probe_port = probe_port_for(cached_url) if cached_url else DEFAULT_PROBE_PORT

    log(f"[+] Watch mode active — polling {tv_ip} (offline every {OFFLINE_POLL}s, online every {ONLINE_POLL}s)")

    try:
        while True:
            reachable = tv_is_reachable(tv_ip, probe_port)

            if not reachable:
                if tv_online:
                    log(f"[!] TV {tv_ip} went offline")
                    tv_online = False
                time.sleep(OFFLINE_POLL)
                continue

            if not tv_online:
                log(f"[+] TV {tv_ip} is reachable, waiting {DLNA_WARMUP}s for DLNA services to start...")
                time.sleep(DLNA_WARMUP)
                try:
                    control_url = discover_control_url(tv_ip, bind_ip, ignore_cache=True)
                    probe_port = probe_port_for(control_url)
                    log(f"[+] AVTransport: {control_url}")
                    push_video(control_url, media_url, file_path.name, mime_type, no_stop)
                    tv_online = True
                except Exception as e:
                    log(f"[!] Push failed: {e} — retrying in {OFFLINE_POLL}s")
                    time.sleep(OFFLINE_POLL)
                    continue
            else:
                try:
                    state = get_transport_state(control_url)
                    if state in RESTART_STATES:
                        log(f"[+] Playback state is {state}, restarting")
                        push_video(control_url, media_url, file_path.name, mime_type, no_stop)
                except Exception as e:
                    log(f"[!] Transport check failed: {e} — will re-discover next cycle")
                    tv_online = False
                    continue

            time.sleep(ONLINE_POLL)

    except KeyboardInterrupt:
        log("\n[+] Stopped")
    finally:
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Push local video to LG/Samsung TV via DLNA/UPnP")
    parser.add_argument("--tv", required=True, help="TV IP, example: 192.168.236.161")
    parser.add_argument("--file", required=True, help="Video file path")
    parser.add_argument("--bind-ip", help="Local IP visible to TV")
    parser.add_argument("--port", type=int, default=8099, help="Local HTTP port")
    parser.add_argument("--safe", action="store_true", help="Transcode to TV-safe H.264 1080p30 AAC MP4")
    parser.add_argument("--control-url", help="Manual AVTransport controlURL")
    parser.add_argument("--ignore-cache", action="store_true", help="Ignore cached AVTransport URL")
    parser.add_argument("--no-stop", action="store_true", help="Do not send Stop before SetAVTransportURI")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode: keep running and re-push video whenever TV comes online or playback stops",
    )
    args = parser.parse_args()

    ensure_dirs()

    file_path = Path(args.file).expanduser().resolve()

    if not file_path.exists():
        raise SystemExit(f"[-] File not found: {file_path}")

    bind_ip = args.bind_ip or get_local_ip_for(args.tv)

    log(f"[+] App: {APP_NAME}")
    log(f"[+] TV IP: {args.tv}")
    log(f"[+] Local IP: {bind_ip}")
    log(f"[+] File: {file_path}")

    if args.watch:
        watch_and_push(
            tv_ip=args.tv,
            file_path=file_path,
            bind_ip=bind_ip,
            port=args.port,
            safe=args.safe,
            ignore_cache=args.ignore_cache,
            no_stop=args.no_stop,
        )
        return

    if args.safe:
        file_path = transcode_safe(file_path)

    server, media_url, mime_type = start_http_server(file_path, bind_ip, args.port)

    try:
        control_url = args.control_url or discover_control_url(
            args.tv,
            bind_ip,
            ignore_cache=args.ignore_cache,
        )

        log(f"[+] AVTransport controlURL: {control_url}")

        if not args.no_stop:
            stop(control_url)

        set_uri(control_url, media_url, file_path.name, mime_type)
        play(control_url)

        log("[+] Play command sent")
        log("[+] Keep this script running while TV plays the file")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        log("\n[+] Stopped")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
