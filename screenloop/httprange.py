"""HTTP Range helpers shared by the controller and the node agent."""

from pathlib import Path


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    range_value = range_header.replace("bytes=", "", 1)
    start_text, _, end_text = range_value.partition("-")
    if not start_text:
        return None
    try:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return None
    if start > end or start >= file_size:
        return None
    return start, min(end, file_size - 1)


def range_response_parts(path: Path, range_header: str | None) -> tuple[int, dict[str, str], int, int]:
    """Return (status_code, headers, start, length) for a ranged video response."""
    file_size = path.stat().st_size
    start = 0
    end = file_size - 1
    status_code = 200

    if range_header and range_header.startswith("bytes="):
        byte_range = parse_range_header(range_header, file_size)
        if not byte_range:
            return 416, {"Content-Range": f"bytes */{file_size}"}, 0, 0
        status_code = 206
        start, end = byte_range

    length = end - start + 1
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
        "transferMode.dlna.org": "Streaming",
        "contentFeatures.dlna.org": "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return status_code, headers, start, length


def iter_file_range(path: Path, start: int, length: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
