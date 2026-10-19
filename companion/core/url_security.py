"""Transport checks for URLs that receive the API key."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_loopback_host(host: str | None) -> bool:
    """Whether host is localhost, in 127.0.0.0/8, or ::1 (no DNS lookup)."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_plaintext_remote_url(url: str) -> bool:
    """Whether url is plain http to a host other than loopback.

    The API key is sent as a Bearer header, so such a URL would expose it in
    transit. Local model servers (Ollama, LM Studio) listen on loopback over
    http and stay allowed. Raises ValueError for a malformed host.
    """
    parts = urlsplit(url)
    return parts.scheme.lower() == "http" and not is_loopback_host(parts.hostname)
