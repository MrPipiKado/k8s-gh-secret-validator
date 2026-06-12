"""Core data structures shared across the app."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


class Status(enum.Enum):
    """Outcome of validating a single token."""

    OK = "OK"               # valid, not expiring within the warn window
    WARN = "WARN"           # valid, but expires within warn_days
    EXPIRED = "EXPIRED"     # expiration date is in the past
    INVALID = "INVALID"     # GitHub rejected the token (401)
    NO_EXPIRY = "NO_EXPIRY"  # valid, but GitHub reports no expiration
    SKIPPED = "SKIPPED"     # not a GitHub token (e.g. Docker Hub cred)
    ERROR = "ERROR"         # could not check (missing secret/key, network, etc.)

    def is_actionable(self) -> bool:
        """Statuses worth alerting a human about."""
        return self in (Status.EXPIRED, Status.WARN, Status.INVALID)


@dataclass
class SecretRef:
    """A secret + the keys within it that hold tokens, from the config."""

    namespace: str
    name: str
    keys: List[str] = field(default_factory=list)


@dataclass
class ExtractedToken:
    """A token value pulled out of a secret key, with a human-readable source.

    ``source`` is the plain key name for Opaque secrets, or the registry host
    (e.g. ``ghcr.io``) for a ``.dockerconfigjson`` secret.
    """

    token: str
    source: str


@dataclass
class TokenResult:
    """The validation result for one token, ready to be reported."""

    namespace: str
    name: str
    key: str
    source: str
    token_type: str
    status: Status
    expires_at: Optional[datetime] = None
    days_left: Optional[int] = None
    message: str = ""
