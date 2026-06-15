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
    """A Kubernetes secret + the keys within it that hold tokens."""

    namespace: str
    name: str
    keys: List[str] = field(default_factory=list)


@dataclass
class AwsSecretRef:
    """An AWS Secrets Manager secret + the JSON keys that hold tokens.

    ``keys`` is optional: when empty, the entire ``SecretString`` is treated as a
    single token (or a dockerconfigjson document). When provided, the secret is
    parsed as a JSON object and each named key is validated.
    """

    region: str
    secret_id: str
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
    """The validation result for one token, ready to be reported.

    Provider-agnostic: ``provider`` is the backend (``k8s``/``aws``) and
    ``location`` is the namespace (k8s) or region (aws).
    """

    provider: str
    location: str
    name: str
    key: str
    source: str
    token_type: str
    status: Status
    expires_at: Optional[datetime] = None
    days_left: Optional[int] = None
    message: str = ""
