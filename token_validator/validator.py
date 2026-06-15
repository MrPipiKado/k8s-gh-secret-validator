"""Orchestration: secret refs -> token values -> validation results.

Two sources are supported: Kubernetes secrets and AWS Secrets Manager. Both feed
the same token-extraction and GitHub-validation pipeline and produce
provider-tagged :class:`TokenResult` rows.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from . import aws, detect, github, k8s
from .config import Config
from .extract import extract_tokens
from .models import AwsSecretRef, SecretRef, Status, TokenResult

log = logging.getLogger(__name__)

# Injectable seams so the orchestration is unit-testable without a cluster,
# AWS, or network. Production code uses the real implementations.
CheckerFn = Callable[[str, str], github.TokenCheck]

# Key/source label used when an AWS secret is validated as a whole (no keys).
WHOLE_VALUE = "value"


def validate(
    config: Config,
    api=None,
    checker: Optional[CheckerFn] = None,
    now: Optional[datetime] = None,
    aws_client_factory: Optional[aws.ClientFactory] = None,
) -> List[TokenResult]:
    """Validate every token referenced by ``config`` and return results.

    A failure on one secret/key never aborts the batch.
    """
    if checker is None:
        checker = lambda tok, url: github.check_token(tok, url)  # noqa: E731
    now = now or datetime.now(timezone.utc)

    results: List[TokenResult] = []

    if config.secrets:
        if api is None:
            api = k8s.load_client()
        for ref in config.secrets:
            results.extend(_validate_k8s_ref(ref, config, api, checker, now))

    if config.aws_secrets:
        if aws_client_factory is None:
            aws_client_factory = aws.client_factory()
        for ref in config.aws_secrets:
            results.extend(_validate_aws_ref(ref, config, aws_client_factory, checker, now))

    return results


# --- Kubernetes -------------------------------------------------------------

def _validate_k8s_ref(ref: SecretRef, config, api, checker, now) -> List[TokenResult]:
    try:
        secret = k8s.read_secret(api, ref.namespace, ref.name)
    except k8s.K8sError as exc:
        # One error row per requested key so the gap is visible in the report.
        return [_error("k8s", ref.namespace, ref.name, key, key, str(exc))
                for key in ref.keys]

    results: List[TokenResult] = []
    for key in ref.keys:
        raw = k8s.decode_secret_value(secret, key)
        if raw is None:
            results.append(_error("k8s", ref.namespace, ref.name, key, key,
                                  f"key '{key}' not found in secret"))
            continue
        results.extend(_validate_value("k8s", ref.namespace, ref.name, key, raw,
                                       config, checker, now))
    return results


# --- AWS Secrets Manager ----------------------------------------------------

def _validate_aws_ref(ref: AwsSecretRef, config, client_factory, checker, now) -> List[TokenResult]:
    keys_for_errors = ref.keys or [WHOLE_VALUE]
    try:
        client = client_factory(ref.region)
        raw = aws.get_secret_string(client, ref.secret_id)
    except aws.AwsError as exc:
        return [_error("aws", ref.region, ref.secret_id, key, key, str(exc))
                for key in keys_for_errors]

    # No keys: the whole SecretString is the token (or a dockerconfig document).
    if not ref.keys:
        return _validate_value("aws", ref.region, ref.secret_id, WHOLE_VALUE, raw,
                               config, checker, now)

    # Keys given: the secret must be a JSON object of key -> value.
    try:
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError("secret is not a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return [_error("aws", ref.region, ref.secret_id, key, key,
                       f"expected a JSON secret with keys: {exc}") for key in ref.keys]

    results: List[TokenResult] = []
    for key in ref.keys:
        if key not in doc:
            results.append(_error("aws", ref.region, ref.secret_id, key, key,
                                  f"key '{key}' not found in secret"))
            continue
        results.extend(_validate_value("aws", ref.region, ref.secret_id, key,
                                       str(doc[key]), config, checker, now))
    return results


# --- Shared token pipeline --------------------------------------------------

def _validate_value(provider, location, name, key, raw, config, checker, now) -> List[TokenResult]:
    """Extract token(s) from one raw secret value and validate each."""
    tokens = extract_tokens(key, raw)
    if not tokens:
        return [_error(provider, location, name, key, key,
                       f"no token found in key '{key}'")]
    return [_validate_token(provider, location, name, key, extracted, config, checker, now)
            for extracted in tokens]


def _validate_token(provider, location, name, key, extracted, config, checker, now) -> TokenResult:
    token_type = detect.detect_type(extracted.token)

    def result(status, expires_at=None, days_left=None, message=""):
        return TokenResult(
            provider=provider, location=location, name=name, key=key,
            source=extracted.source, token_type=token_type, status=status,
            expires_at=expires_at, days_left=days_left, message=message,
        )

    if not detect.is_github_token(extracted.token):
        return result(Status.SKIPPED, message="not a GitHub token; skipped")

    check = checker(extracted.token, config.github_api_url)

    if check.error and not check.valid and check.expires_at is None and "401" not in check.error:
        # Network / unexpected error (distinct from an explicit 401 rejection).
        return result(Status.ERROR, message=check.error)

    if not check.valid:
        return result(Status.INVALID, message=check.error or "token invalid")

    if check.expires_at is None:
        return result(Status.NO_EXPIRY, message="valid; no expiration reported")

    days_left = (check.expires_at - now).days
    status = _status_for_expiry(check.expires_at, now, config.warn_days)
    return result(status, expires_at=check.expires_at, days_left=days_left)


def _status_for_expiry(expires_at: datetime, now: datetime, warn_days: int) -> Status:
    # Inclusive, exact-time boundary: warn the moment the token expires within
    # warn_days from now (a token expiring in exactly warn_days warns).
    if expires_at <= now:
        return Status.EXPIRED
    if expires_at <= now + timedelta(days=warn_days):
        return Status.WARN
    return Status.OK


def _error(provider, location, name, key, source, message) -> TokenResult:
    return TokenResult(
        provider=provider, location=location, name=name, key=key, source=source,
        token_type="-", status=Status.ERROR, message=message,
    )
