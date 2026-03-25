"""
SSRF-safe URL validation for server-side HTTP fetches (fetch_webpage, etc.).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "0.0.0.0",
        "::",
        "metadata.google.internal",
        "metadata.goog",
    }
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved:
        return True
    if ip.version == 4:
        # AWS / cloud metadata (not always link_local in all libs)
        if ip == ipaddress.IPv4Address("169.254.169.254"):
            return True
    if ip.version == 6:
        # Unique local (fc00::/7)
        if ip in ipaddress.IPv6Network("fc00::/7"):
            return True
    return False


def url_fetch_blocked_reason(url: str) -> str | None:
    """
    Return a short error string if the URL must not be fetched, else None.
    Only http/https; host must resolve only to public addresses.
    """
    if not url or not isinstance(url, str):
        return "Empty or invalid URL"
    raw = url.strip()
    if len(raw) > 8192:
        return "URL too long"

    try:
        parsed = urlparse(raw)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return "Only http and https URLs are allowed"

    host = parsed.hostname
    if not host:
        return "Missing hostname"

    h = host.lower().strip(".")
    if h in _BLOCKED_HOSTNAMES or h.endswith(".localhost"):
        return "Hostname is not allowed"

    # Literal IP in hostname
    try:
        ip = ipaddress.ip_address(h)
        if _is_blocked_ip(ip):
            return "Address is not a public endpoint"
        return None
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(h, None, type=socket.SOCK_STREAM)
    except OSError:
        return "Could not resolve hostname"

    if not infos:
        return "Could not resolve hostname"

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return "Hostname resolves to a non-public address"

    return None
