"""
AiSocialFeed — URL Safety Validator
Blocks SSRF attacks: prevents users from submitting internal Docker hostnames
or private IP addresses as feed URLs.
"""
from __future__ import annotations
import ipaddress
from urllib.parse import urlparse


# Docker-internal service names
_BLOCKED_HOSTS = frozenset({
    "redis", "db", "stf_redis", "stf_db", "stf_rsshub",
    "stf_worker", "stf_bot", "stf_admin", "stf_backup",
    "localhost", "localtest.me",
})

# Private IP ranges per RFC 1918 + RFC 4193 + link-local
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::1/128"),
]


def is_safe_url(url: str) -> bool:
    """
    Return True if the URL is safe to fetch.
    Blocks internal Docker services and private IP ranges.
    Only called for RSS feed URLs, not for platform-specific routes.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""

        if not host:
            return False

        # Block Docker-internal service names
        if host.lower() in _BLOCKED_HOSTS:
            return False

        # Block numeric IP addresses in private ranges
        try:
            addr = ipaddress.ip_address(host)
            for net in _PRIVATE_NETS:
                if addr in net:
                    return False
        except ValueError:
            pass  # Not an IP address — hostname is fine

        return True

    except Exception:
        return False  # Malformed URL — reject
