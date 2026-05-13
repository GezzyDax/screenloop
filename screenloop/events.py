from typing import Any


def event_details(**values: Any) -> str:
    parts = []
    for key, value in values.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace(";", ",")
        parts.append(f"{key}={text}")
    return "; ".join(parts)


def parse_event_details(details: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not details:
        return parsed
    for part in str(details).split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key:
            parsed[key.strip()] = value.strip()
    return parsed


def elapsed_seconds(started_at: int | float | None, now: int | float) -> float | None:
    if not started_at:
        return None
    return round(max(0.0, float(now) - float(started_at)), 3)
