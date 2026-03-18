"""
Network guardrails for browser-style retrieval.

Provides SSRF protection aligned with the Browser Agent guide:
  - block private/link-local/loopback ranges
  - restrict to HTTP(S) schemes
  - optional host allow-list for controlled egress
"""

from __future__ import annotations

import ipaddress
from typing import Iterable
from urllib.parse import urlparse


class NetworkGuardError(ValueError):
    """Raised when an outbound URL violates egress policy."""


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]

_BLOCKED_SCHEMES = {"", "file", "ftp", "gopher", "sftp", "ssh"}


def _is_ip_blocked(hostname: str) -> bool:
    try:
        ip_addr = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return any(ip_addr in net for net in _BLOCKED_NETWORKS) or ip_addr.is_loopback or ip_addr.is_link_local


def validate_outbound_url(url: str, allow_hosts: Iterable[str] | None = None) -> str:
    """
    Validate an outbound URL for SSRF safety.

    Returns the normalized URL if allowed; raises NetworkGuardError otherwise.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise NetworkGuardError(f"Blocked scheme: {parsed.scheme}")

    host = parsed.hostname or ""
    if not host:
        raise NetworkGuardError("URL missing host")

    if _is_ip_blocked(host):
        raise NetworkGuardError(f"Blocked private or loopback address: {host}")

    if allow_hosts is not None and host not in allow_hosts:
        raise NetworkGuardError(f"Host not allow-listed: {host}")

    return parsed.geturl()
