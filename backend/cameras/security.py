from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def sanitize_source_uri(source_uri: str) -> str:
    parsed = urlsplit(source_uri)
    if not parsed.scheme or "@" not in parsed.netloc:
        return source_uri

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    redacted_netloc = f"***:***@{host}{port}"
    return urlunsplit(
        (parsed.scheme, redacted_netloc, parsed.path, parsed.query, parsed.fragment)
    )
