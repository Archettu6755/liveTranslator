from __future__ import annotations

from collections.abc import Collection
from ipaddress import ip_address
from urllib.parse import SplitResult, urlsplit


def require_loopback_url(value: str, *, schemes: Collection[str], field_name: str) -> None:
    parsed = _parse_url(value, schemes=schemes, field_name=field_name)
    host = parsed.hostname
    if host is None or not _is_loopback_host(host):
        allowed = ", ".join(sorted(schemes))
        raise ValueError(f"{field_name} must use {allowed} with a loopback host")


def require_https_or_loopback_http(value: str, *, field_name: str) -> None:
    parsed = _parse_url(value, schemes={"http", "https"}, field_name=field_name)
    if parsed.scheme == "https":
        return
    host = parsed.hostname
    if host is None or not _is_loopback_host(host):
        raise ValueError(f"{field_name} must use HTTPS unless its host is loopback")


def _parse_url(value: str, *, schemes: Collection[str], field_name: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid URL") from exc
    if parsed.scheme not in schemes or not parsed.netloc or parsed.hostname is None:
        allowed = ", ".join(sorted(schemes))
        raise ValueError(f"{field_name} must be an absolute {allowed} URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.fragment:
        raise ValueError(f"{field_name} must not contain a fragment")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError(f"{field_name} contains an invalid port")
    return parsed


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
