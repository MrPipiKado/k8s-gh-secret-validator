"""Orchestration: secret refs -> token values -> validation results."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from . import detect, github, k8s
from .config import Config
from .extract import extract_tokens
from .models import SecretRef, Status, TokenResult

log = logging.getLogger(__name__)

# Injectable seams so the orchestration is unit-testable without a cluster or
# network. Production code uses the real implementations.
CheckerFn = Callable[[str, str], github.TokenCheck]


def validate(
    config: Config,
    api=None,
    checker: Optional[CheckerFn] = None,
    now: Optional[datetime] = None,
) -> List[TokenResult]:
    """Validate every token referenced by ``config`` and return results.

    A failure on one secret/key never aborts the batch.
    """
    if api is None:
        api = k8s.load_client()
    if checker is None:
        checker = lambda tok, url: github.check_token(tok, url)  # noqa: E731
    now = now or datetime.now(timezone.utc)

    results: List[TokenResult] = []
    for ref in config.secrets:
        results.extend(_validate_ref(ref, config, api, checker, now))
    return results


def _validate_ref(ref: SecretRef, config: Config, api, checker, now) -> List[TokenResult]:
    try:
        secret = k8s.read_secret(api, ref.namespace, ref.name)
    except k8s.K8sError as exc:
        # One error row per requested key so the gap is visible in the report.
        return [_error(ref, key, source=key, message=str(exc)) for key in ref.keys]

    results: List[TokenResult] = []
    for key in ref.keys:
        raw = k8s.decode_secret_value(secret, key)
        if raw is None:
            results.append(_error(ref, key, source=key,
                                  message=f"key '{key}' not found in secret"))
            continue

        tokens = extract_tokens(key, raw)
        if not tokens:
            results.append(_error(ref, key, source=key,
                                  message=f"no token found in key '{key}'"))
            continue

        for extracted in tokens:
            results.append(_validate_token(ref, key, extracted, config, checker, now))
    return results


def _validate_token(ref, key, extracted, config, checker, now) -> TokenResult:
    token_type = detect.detect_type(extracted.token)

    if not detect.is_github_token(extracted.token):
        return TokenResult(
            namespace=ref.namespace, name=ref.name, key=key, source=extracted.source,
            token_type=token_type, status=Status.SKIPPED,
            message="not a GitHub token; skipped",
        )

    check = checker(extracted.token, config.github_api_url)

    if check.error and not check.valid and check.expires_at is None and "401" not in check.error:
        # Network / unexpected error (distinct from an explicit 401 rejection).
        return TokenResult(
            namespace=ref.namespace, name=ref.name, key=key, source=extracted.source,
            token_type=token_type, status=Status.ERROR, message=check.error,
        )

    if not check.valid:
        return TokenResult(
            namespace=ref.namespace, name=ref.name, key=key, source=extracted.source,
            token_type=token_type, status=Status.INVALID,
            message=check.error or "token invalid",
        )

    if check.expires_at is None:
        return TokenResult(
            namespace=ref.namespace, name=ref.name, key=key, source=extracted.source,
            token_type=token_type, status=Status.NO_EXPIRY,
            message="valid; no expiration reported",
        )

    days_left = (check.expires_at - now).days
    status = _status_for_expiry(check.expires_at, now, config.warn_days)
    return TokenResult(
        namespace=ref.namespace, name=ref.name, key=key, source=extracted.source,
        token_type=token_type, status=status,
        expires_at=check.expires_at, days_left=days_left,
    )


def _status_for_expiry(expires_at: datetime, now: datetime, warn_days: int) -> Status:
    # Inclusive, exact-time boundary: warn the moment the token expires within
    # warn_days from now (a token expiring in exactly warn_days warns).
    if expires_at <= now:
        return Status.EXPIRED
    if expires_at <= now + timedelta(days=warn_days):
        return Status.WARN
    return Status.OK


def _error(ref: SecretRef, key: str, source: str, message: str) -> TokenResult:
    return TokenResult(
        namespace=ref.namespace, name=ref.name, key=key, source=source,
        token_type="-", status=Status.ERROR, message=message,
    )
