"""SSRF-oriented URL allowlist and private-IP rejection for skill fetch/browse."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def parse_allowlist(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def assert_prefix_allowed(url: str, allowlist: list[str], *, empty_message: str) -> None:
    if not allowlist:
        raise ValueError(empty_message)
    if not any(url.startswith(prefix) for prefix in allowlist):
        raise ValueError(f"URL not on allowlist: {url}")


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_host_not_private(hostname: str) -> None:
    """Resolve hostname and reject private / link-local / loopback targets."""
    host = (hostname or "").strip().strip("[]")
    if not host:
        raise ValueError("URL host is required")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise ValueError(f"blocked address: {host}")
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host}") from exc
    if not infos:
        raise ValueError(f"DNS resolution failed for {host}")
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise ValueError(f"blocked address for host {host}: {addr}")


def assert_safe_http_url(url: str, allowlist: list[str], *, empty_message: str) -> None:
    """Allowlist prefix match + https/http only + no private resolved IPs."""
    assert_prefix_allowed(url, allowlist, empty_message=empty_message)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme or 'none'}")
    if not parsed.hostname:
        raise ValueError("URL host is required")
    assert_host_not_private(parsed.hostname)
