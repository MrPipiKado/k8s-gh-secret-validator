import base64
from datetime import datetime, timedelta, timezone

from token_validator.config import Config
from token_validator.github import TokenCheck
from token_validator.models import SecretRef, Status
from token_validator.validator import validate

NOW = datetime(2026, 6, 12, tzinfo=timezone.utc)


class FakeSecret:
    def __init__(self, data):
        # mirror V1Secret.data: base64-encoded string values
        self.data = {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}


class FakeApi:
    """Minimal stand-in for CoreV1Api keyed by (namespace, name)."""

    def __init__(self, secrets):
        self._secrets = secrets

    def read_namespaced_secret(self, name, namespace):
        from kubernetes.client.rest import ApiException
        key = (namespace, name)
        if key not in self._secrets:
            raise ApiException(status=404, reason="Not Found")
        return self._secrets[key]


def make_config(secrets, warn_days=7):
    return Config(secrets=secrets, warn_days=warn_days,
                  github_api_url="https://api.github.com")


def run(secrets_on_cluster, refs, checker, warn_days=7):
    api = FakeApi(secrets_on_cluster)
    return validate(make_config(refs, warn_days), api=api, checker=checker, now=NOW)


def test_ok_when_far_from_expiry():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=30))
    res = run(secrets, refs, checker)
    assert res[0].status is Status.OK
    assert res[0].days_left == 30


def test_warn_within_window():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=3))
    res = run(secrets, refs, checker, warn_days=7)
    assert res[0].status is Status.WARN


def test_warn_boundary_exactly_warn_days_is_inclusive():
    # Expiring in exactly warn_days should WARN (inclusive boundary).
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=7))
    res = run(secrets, refs, checker, warn_days=7)
    assert res[0].status is Status.WARN


def test_ok_just_outside_warn_window():
    # A second past the warn window stays OK (exact-time, not day-floored).
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(
        valid=True, expires_at=NOW + timedelta(days=7, seconds=1))
    res = run(secrets, refs, checker, warn_days=7)
    assert res[0].status is Status.OK


def test_expired():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW - timedelta(days=1))
    res = run(secrets, refs, checker)
    assert res[0].status is Status.EXPIRED


def test_no_expiry():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=None)
    res = run(secrets, refs, checker)
    assert res[0].status is Status.NO_EXPIRY


def test_invalid_token():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=False, error="token invalid or revoked (401)")
    res = run(secrets, refs, checker)
    assert res[0].status is Status.INVALID


def test_non_github_token_skipped():
    secrets = {("default", "s"): FakeSecret({"token": "dckr_pat_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    # checker must not even be consulted for skipped tokens.
    def checker(t, u):
        raise AssertionError("checker should not run for non-GitHub tokens")
    res = run(secrets, refs, checker)
    assert res[0].status is Status.SKIPPED


def test_missing_secret_is_error_not_fatal():
    secrets = {}  # secret absent
    refs = [SecretRef("default", "missing", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True)
    res = run(secrets, refs, checker)
    assert len(res) == 1
    assert res[0].status is Status.ERROR


def test_missing_key_is_error():
    secrets = {("default", "s"): FakeSecret({"other": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True)
    res = run(secrets, refs, checker)
    assert res[0].status is Status.ERROR


def test_network_error_is_error_status():
    secrets = {("default", "s"): FakeSecret({"token": "ghp_x"})}
    refs = [SecretRef("default", "s", ["token"])]
    checker = lambda t, u: TokenCheck(valid=False, error="request failed: timeout")
    res = run(secrets, refs, checker)
    assert res[0].status is Status.ERROR


def test_dockerconfig_yields_per_registry_results():
    import json
    doc = json.dumps({"auths": {
        "ghcr.io": {"password": "ghp_one"},
        "docker.io": {"password": "dckr_two"},  # non-github -> skipped
    }})
    secrets = {("default", "s"): FakeSecret({".dockerconfigjson": doc})}
    refs = [SecretRef("default", "s", [".dockerconfigjson"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=30))
    res = run(secrets, refs, checker)
    by_source = {r.source: r.status for r in res}
    assert by_source["ghcr.io"] is Status.OK
    assert by_source["docker.io"] is Status.SKIPPED
