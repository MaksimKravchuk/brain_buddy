"""Shared strict host and authority grammar for agent endpoint URLs."""

from __future__ import annotations

import ipaddress
import re

_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_NUMERIC_HOST_RE = re.compile(
    r"(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:\.(?:0[xX][0-9A-Fa-f]+|[0-9]+))*"
)


def validate_endpoint_authority(authority: str, host: str) -> None:
    """Reject ambiguous authorities before persistence or name resolution."""

    host_port = authority.rsplit("@", 1)[-1]
    if host_port.endswith(":"):
        raise ValueError("agent endpoint port is not valid")
    if "%" in host or not host:
        raise ValueError("agent endpoint is not a valid URL")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None:
        if str(address) != host.lower():
            raise ValueError("agent endpoint is not a valid URL")
        if isinstance(address, ipaddress.IPv6Address):
            closing_bracket = host_port.find("]")
            if not host_port.startswith("[") or closing_bracket < 0:
                raise ValueError("agent endpoint is not a valid URL")
        elif host_port.startswith("["):
            raise ValueError("agent endpoint is not a valid URL")
        return

    # Numeric and dotted-numeric alternatives have platform-dependent resolver
    # meanings (for example 127.1 and 2130706433). They are never DNS names here.
    if _NUMERIC_HOST_RE.fullmatch(host):
        raise ValueError("agent endpoint is not a valid URL")
    if len(host) > 253:
        raise ValueError("agent endpoint is not a valid URL")
    labels = host.split(".")
    if any(_DNS_LABEL_RE.fullmatch(label) is None for label in labels):
        raise ValueError("agent endpoint is not a valid URL")
