"""Pure URL checks shared by official news extraction and media selection."""

import ipaddress
from urllib.parse import urlsplit


def approved_url(url: str, hosts: tuple[str, ...] | list[str]) -> bool:
    """Accept only absolute HTTPS references on explicitly trusted public hosts."""
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 443}
            or any(c.isspace() or ord(c) < 32 for c in url)
            or "\\" in url
        ):
            return False
        host = parts.hostname.lower()
        try:
            ipaddress.ip_address(host)
            return False  # Official sources/CDNs are configured by DNS name only.
        except ValueError:
            pass
        return (
            host in hosts
            and "." in host
            and not host.endswith((".local", ".localhost"))
        )
    except ValueError:
        return False
