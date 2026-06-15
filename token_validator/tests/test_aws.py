import pytest

from token_validator import aws


class Client:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def get_secret_value(self, SecretId):  # noqa: N803
        if self._exc:
            raise self._exc
        return self._resp


def test_get_secret_string_returns_value():
    c = Client(resp={"SecretString": "ghp_abc"})
    assert aws.get_secret_string(c, "id") == "ghp_abc"


def test_get_secret_string_binary_only_raises():
    c = Client(resp={"SecretBinary": b"\x00"})
    with pytest.raises(aws.AwsError):
        aws.get_secret_string(c, "id")


def test_get_secret_string_client_error_wrapped():
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetSecretValue")
    c = Client(exc=err)
    with pytest.raises(aws.AwsError) as ei:
        aws.get_secret_string(c, "id")
    assert "AccessDeniedException" in str(ei.value)


def test_client_factory_caches_per_region(monkeypatch):
    calls = []
    monkeypatch.setattr(aws, "load_client", lambda region: calls.append(region) or object())
    factory = aws.client_factory()
    a1 = factory("us-east-1")
    a2 = factory("us-east-1")
    factory("eu-west-1")
    assert a1 is a2                 # same region -> cached client
    assert calls == ["us-east-1", "eu-west-1"]
