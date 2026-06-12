"""Query GitHub for a token's validity and expiration.

GitHub returns a ``GitHub-Authentication-Token-Expiration`` header on any
authenticated REST request. We hit ``/rate_limit`` because it works for every
token type (including app installation tokens) and does not consume rate limit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

EXPIRATION_HEADER = "GitHub-Authentication-Token-Expiration"


@dataclass
class TokenCheck:
    """Result of asking GitHub about one token."""

    valid: bool
    expires_at: Optional[datetime] = None
    error: Optional[str] = None


def check_token(token: str, api_url: str, timeout: int = 10) -> TokenCheck:
    """Validate ``token`` against ``api_url`` and read its expiration, if any."""
    url = f"{api_url.rstrip('/')}/rate_limit"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return TokenCheck(valid=False, error=f"request failed: {exc}")

    if resp.status_code == 401:
        return TokenCheck(valid=False, error="token invalid or revoked (401)")
    if resp.status_code >= 400:
        return TokenCheck(
            valid=False,
            error=f"unexpected GitHub response {resp.status_code}: {resp.reason}",
        )

    expires_at = _parse_expiration(resp.headers.get(EXPIRATION_HEADER))
    return TokenCheck(valid=True, expires_at=expires_at)


def _parse_expiration(value: Optional[str]) -> Optional[datetime]:
    """Parse the expiration header into a tz-aware UTC datetime.

    Header looks like ``2024-12-31 23:59:59 UTC`` or an ISO-8601 string,
    depending on token type. Returns ``None`` when absent or unparseable.
    """
    if not value:
        return None
    value = value.strip()

    # Common form: "2024-12-31 23:59:59 UTC"
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S UTC"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # ISO-8601 fallback (e.g. "2024-12-31T23:59:59Z").
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        log.warning("could not parse expiration header value: %r", value)
        return None
