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


# --- AWS Secrets Manager ----------------------------------------------------

import json  # noqa: E402

from token_validator.models import AwsSecretRef  # noqa: E402


class FakeAwsClient:
    """Stand-in for a Secrets Manager client keyed by secret id -> SecretString."""

    def __init__(self, mapping):
        self._m = mapping

    def get_secret_value(self, SecretId):  # noqa: N803 (boto3 arg name)
        from botocore.exceptions import ClientError
        if SecretId not in self._m:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue")
        return {"SecretString": self._m[SecretId]}


def run_aws(secrets_in_aws, refs, checker, warn_days=7):
    client = FakeAwsClient(secrets_in_aws)
    cfg = Config(aws_secrets=refs, warn_days=warn_days,
                 github_api_url="https://api.github.com")
    return validate(cfg, checker=checker, now=NOW,
                    aws_client_factory=lambda region: client)


def test_aws_plain_string_secret():
    aws_secrets = {"prod/gh": "ghp_aws"}
    refs = [AwsSecretRef("us-east-1", "prod/gh", [])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=30))
    res = run_aws(aws_secrets, refs, checker)
    assert len(res) == 1
    assert res[0].provider == "aws"
    assert res[0].location == "us-east-1"
    assert res[0].status is Status.OK


def test_aws_json_keys():
    aws_secrets = {"prod/gh": json.dumps({"GITHUB_TOKEN": "ghp_json", "other": "x"})}
    refs = [AwsSecretRef("eu-west-1", "prod/gh", ["GITHUB_TOKEN"])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=2))
    res = run_aws(aws_secrets, refs, checker)
    assert res[0].status is Status.WARN
    assert res[0].key == "GITHUB_TOKEN"


def test_aws_missing_secret_is_error():
    refs = [AwsSecretRef("us-east-1", "absent", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True)
    res = run_aws({}, refs, checker)
    assert res[0].status is Status.ERROR
    assert "ResourceNotFoundException" in res[0].message


def test_aws_missing_key_is_error():
    aws_secrets = {"prod/gh": json.dumps({"other": "ghp_x"})}
    refs = [AwsSecretRef("us-east-1", "prod/gh", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True)
    res = run_aws(aws_secrets, refs, checker)
    assert res[0].status is Status.ERROR


def test_aws_keys_on_non_json_is_error():
    aws_secrets = {"prod/gh": "ghp_plain_not_json"}
    refs = [AwsSecretRef("us-east-1", "prod/gh", ["token"])]
    checker = lambda t, u: TokenCheck(valid=True)
    res = run_aws(aws_secrets, refs, checker)
    assert res[0].status is Status.ERROR


def test_aws_dockerconfig_in_plain_secret():
    doc = json.dumps({"auths": {"ghcr.io": {"password": "ghp_reg"}}})
    refs = [AwsSecretRef("us-east-1", "prod/pull", [])]
    checker = lambda t, u: TokenCheck(valid=True, expires_at=NOW + timedelta(days=30))
    res = run_aws({"prod/pull": doc}, refs, checker)
    assert res[0].source == "ghcr.io"
    assert res[0].status is Status.OK
