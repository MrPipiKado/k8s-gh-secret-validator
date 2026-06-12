"""Pull token value(s) out of a single secret key.

A plain key yields one token. A ``.dockerconfigjson`` key is a JSON document of
registry credentials and can yield several tokens (one per registry), which is
why this returns a list.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import List

from .models import ExtractedToken

DOCKERCONFIG_KEYS = (".dockerconfigjson", ".dockercfg")


def extract_tokens(key: str, raw_value: str) -> List[ExtractedToken]:
    """Turn one decoded secret value into zero or more candidate tokens."""
    if key in DOCKERCONFIG_KEYS or _looks_like_dockerconfig(raw_value):
        return _extract_from_dockerconfig(raw_value)

    value = raw_value.strip()
    if not value:
        return []
    return [ExtractedToken(token=value, source=key)]


def _looks_like_dockerconfig(value: str) -> bool:
    """Heuristic: a JSON object carrying an ``auths`` map."""
    stripped = value.lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and "auths" in parsed


def _extract_from_dockerconfig(raw_value: str) -> List[ExtractedToken]:
    try:
        doc = json.loads(raw_value)
    except (json.JSONDecodeError, ValueError):
        return []

    auths = doc.get("auths")
    if not isinstance(auths, dict):
        return []

    tokens: List[ExtractedToken] = []
    for registry, entry in auths.items():
        if not isinstance(entry, dict):
            continue
        token = _token_from_auth_entry(entry)
        if token:
            tokens.append(ExtractedToken(token=token, source=str(registry)))
    return tokens


def _token_from_auth_entry(entry: dict) -> str:
    """Prefer the explicit password; fall back to decoding ``auth`` (user:token)."""
    password = entry.get("password")
    if password:
        return str(password).strip()

    auth = entry.get("auth")
    if not auth:
        return ""
    try:
        decoded = base64.b64decode(str(auth), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return ""
    # Format is "username:token"; split on the first colon only.
    _, sep, token = decoded.partition(":")
    return token.strip() if sep else ""
