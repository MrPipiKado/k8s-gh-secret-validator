"""Identify a token's type from its prefix.

See GitHub's token format docs: tokens carry a type-specific prefix so they can
be detected by secret scanners. We use the same prefixes for display and to tell
GitHub tokens apart from unrelated registry credentials.
"""

from __future__ import annotations

# Prefix -> friendly label. Order does not matter; we match the longest first.
_PREFIXES = {
    "github_pat_": "fine-grained PAT",
    "ghp_": "classic PAT",
    "gho_": "OAuth token",
    "ghu_": "user-to-server token",
    "ghs_": "app installation token",
    "ghr_": "refresh token",
}

UNKNOWN = "unknown"


def detect_type(token: str) -> str:
    """Return a friendly label for the token's type, or ``"unknown"``."""
    # Longest prefix first so ``github_pat_`` wins over any shorter overlap.
    for prefix in sorted(_PREFIXES, key=len, reverse=True):
        if token.startswith(prefix):
            return _PREFIXES[prefix]
    return UNKNOWN


def is_github_token(token: str) -> bool:
    """True if the token carries a recognized GitHub prefix."""
    return detect_type(token) != UNKNOWN
