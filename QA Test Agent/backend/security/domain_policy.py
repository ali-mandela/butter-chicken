"""URL / domain safety policy applied before any browser navigation."""
from __future__ import annotations

from urllib.parse import urlparse

from config.settings import get_settings

DESTRUCTIVE_KEYWORDS = (
    "delete-account",
    "close-account",
    "purge",
    "wipe",
)


class DomainPolicyError(ValueError):
    pass


def validate_application_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise DomainPolicyError("Only http/https URLs are allowed")
    if not parsed.netloc:
        raise DomainPolicyError("URL must include a host")

    settings = get_settings()
    host = parsed.hostname or ""

    blocked = [d.strip() for d in settings.blocked_domains.split(",") if d.strip()]
    if any(host == b or host.endswith(f".{b}") for b in blocked):
        raise DomainPolicyError(f"Domain '{host}' is not allowed for testing")

    allowed = [d.strip() for d in settings.allowed_domains.split(",") if d.strip()]
    if allowed and not any(host == a or host.endswith(f".{a}") for a in allowed):
        raise DomainPolicyError(f"Domain '{host}' is not in the allowed-domain list")

    return url


def is_destructive_action(description: str) -> bool:
    lowered = description.lower()
    return any(k in lowered for k in DESTRUCTIVE_KEYWORDS)
