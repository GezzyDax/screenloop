import html
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import APP_NAME


USER_AGENT = f"{APP_NAME}/3.0 UPnP/1.0 DLNADOC/1.50"
AVTRANSPORT_SERVICE = "urn:schemas-upnp-org:service:AVTransport:1"
RESTART_STATES = {"STOPPED", "NO_MEDIA_PRESENT"}


def get_local_ip_for(tv_ip: str) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((tv_ip, 1900))
        return sock.getsockname()[0]
    finally:
        sock.close()


def parse_ssdp_response(data: bytes) -> dict[str, str]:
    text = data.decode("utf-8", errors="ignore")
    headers = {}
    for line in text.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers


def ssdp_discover(tv_ip: str, bind_ip: str, timeout: float = 5.0) -> list[str]:
    targets = [
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "urn:schemas-upnp-org:service:AVTransport:1",
        "ssdp:all",
    ]
    locations: list[str] = []

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
                if location and (addr[0] == tv_ip or tv_ip in location) and location not in locations:
                    locations.append(location)
        finally:
            sock.close()

    return locations


def discover_renderers(bind_ip: str, timeout: float = 4.0) -> list[dict[str, str | None]]:
    msg = "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 2",
            "ST: urn:schemas-upnp-org:device:MediaRenderer:1",
            f"USER-AGENT: {USER_AGENT}",
            "",
            "",
        ]
    ).encode()
    locations: dict[str, str] = {}

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
            if location:
                locations[location] = addr[0]
    finally:
        sock.close()

    devices: list[dict[str, str | None]] = []
    seen_control_urls: set[str] = set()
    for location, ip in locations.items():
        try:
            info = inspect_device(location)
        except Exception:
            continue
        control_url = info.get("control_url")
        if not control_url or control_url in seen_control_urls:
            continue
        seen_control_urls.add(control_url)
        info["ip"] = ip
        info["location"] = location
        devices.append(info)
    return devices


def discover_renderers_multi(bind_ips: list[str], timeout: float = 4.0) -> list[dict[str, str | None]]:
    devices: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for bind_ip in bind_ips:
        try:
            found = discover_renderers(bind_ip, timeout)
        except Exception:
            continue
        for device in found:
            key = str(device.get("control_url") or device.get("location") or device.get("ip"))
            if key in seen:
                continue
            seen.add(key)
            device["bind_ip"] = bind_ip
            devices.append(device)
    return devices


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find_text(parent: ET.Element, child_name: str) -> str:
    for child in parent:
        if local_name(child.tag) == child_name:
            return child.text or ""
    return ""


def fetch_url(url: str, timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Connection": "close"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def inspect_device(location: str) -> dict[str, str | None]:
    xml_data = fetch_url(location)
    root = ET.fromstring(xml_data)
    info = {"manufacturer": None, "model_name": None, "friendly_name": None, "control_url": None}

    url_base = None
    for elem in root.iter():
        name = local_name(elem.tag)
        if name == "URLBase" and elem.text:
            url_base = elem.text.strip()
        elif name == "manufacturer" and elem.text:
            info["manufacturer"] = elem.text.strip()
        elif name == "modelName" and elem.text:
            info["model_name"] = elem.text.strip()
        elif name == "friendlyName" and elem.text:
            info["friendly_name"] = elem.text.strip()

    if not url_base:
        parsed = urllib.parse.urlparse(location)
        url_base = f"{parsed.scheme}://{parsed.netloc}/"

    for service in root.iter():
        if local_name(service.tag) != "service":
            continue
        service_type = find_text(service, "serviceType")
        control_url = find_text(service, "controlURL")
        if "AVTransport" in service_type and control_url:
            info["control_url"] = urllib.parse.urljoin(url_base, control_url)
            break

    return info


def soap_request(control_url: str, action: str, inner_xml: str, quiet: bool = False) -> bytes:
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
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read()


def test_control_url(control_url: str) -> bool:
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


_FALLBACK_PORTS = [1925, 52235, 55000, 49200, 8080]
_FALLBACK_PATHS = ["/rootDesc.xml", "/upnp/IGD.xml", "/description.xml", "/DeviceDescription.xml"]


def _probe_direct(tv_ip: str) -> list[str]:
    """Try well-known UPnP ports/paths when SSDP multicast returns nothing."""
    found = []
    for port in _FALLBACK_PORTS:
        for path in _FALLBACK_PATHS:
            url = f"http://{tv_ip}:{port}{path}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Connection": "close"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        found.append(url)
                        break
            except Exception:
                continue
    return found


def discover_device(tv_ip: str, bind_ip: str) -> dict[str, str | None]:
    locations = ssdp_discover(tv_ip, bind_ip)
    if not locations:
        locations = _probe_direct(tv_ip)
    for location in locations:
        try:
            info = inspect_device(location)
            if info.get("control_url"):
                info["location"] = location
                return info
        except Exception:
            continue
    raise RuntimeError("AVTransport controlURL not found")


def tv_is_reachable(tv_ip: str, probe_port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((tv_ip, probe_port), timeout=timeout):
            return True
    except OSError:
        return False


def host_ping_reachable(tv_ip: str, timeout: int = 1) -> bool:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), tv_ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def make_didl(media_url: str, title: str, mime_type: str) -> str:
    escaped_url = html.escape(media_url, quote=True)
    escaped_title = html.escape(title, quote=True)
    return f"""<DIDL-Lite
 xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <item id="1" parentID="0" restricted="1">
    <dc:title>{escaped_title}</dc:title>
    <upnp:class>object.item.videoItem</upnp:class>
    <res protocolInfo="http-get:*:{mime_type}:*">{escaped_url}</res>
  </item>
</DIDL-Lite>"""


def stop(control_url: str) -> None:
    inner = f"""
<u:Stop xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
</u:Stop>
"""
    try:
        soap_request(control_url, "Stop", inner)
    except Exception:
        pass


def stop_strict(control_url: str) -> None:
    inner = f"""
<u:Stop xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
</u:Stop>
"""
    soap_request(control_url, "Stop", inner)


def set_uri(control_url: str, media_url: str, title: str, mime_type: str) -> None:
    didl = make_didl(media_url, title, mime_type)
    inner = f"""
<u:SetAVTransportURI xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
  <CurrentURI>{html.escape(media_url, quote=True)}</CurrentURI>
  <CurrentURIMetaData>{html.escape(didl, quote=True)}</CurrentURIMetaData>
</u:SetAVTransportURI>
"""
    soap_request(control_url, "SetAVTransportURI", inner)


def play(control_url: str) -> None:
    inner = f"""
<u:Play xmlns:u="{AVTRANSPORT_SERVICE}">
  <InstanceID>0</InstanceID>
  <Speed>1</Speed>
</u:Play>
"""
    soap_request(control_url, "Play", inner)


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


def push_video(control_url: str, media_url: str, file_name: str, mime_type: str, no_stop: bool = False) -> None:
    if not no_stop:
        stop(control_url)
    set_uri(control_url, media_url, file_name, mime_type)
    play(control_url)
