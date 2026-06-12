import base64
import json

from token_validator.extract import extract_tokens


def test_plain_key_yields_one_token():
    tokens = extract_tokens("token", "ghp_abc123\n")
    assert len(tokens) == 1
    assert tokens[0].token == "ghp_abc123"
    assert tokens[0].source == "token"


def test_empty_plain_value_yields_nothing():
    assert extract_tokens("token", "   ") == []


def _docker_json(entries):
    return json.dumps({"auths": entries})


def test_dockerconfig_password_form():
    raw = _docker_json({"ghcr.io": {"username": "bot", "password": "ghp_pw"}})
    tokens = extract_tokens(".dockerconfigjson", raw)
    assert len(tokens) == 1
    assert tokens[0].token == "ghp_pw"
    assert tokens[0].source == "ghcr.io"


def test_dockerconfig_auth_base64_form():
    auth = base64.b64encode(b"bot:ghp_fromauth").decode()
    raw = _docker_json({"ghcr.io": {"auth": auth}})
    tokens = extract_tokens(".dockerconfigjson", raw)
    assert len(tokens) == 1
    assert tokens[0].token == "ghp_fromauth"


def test_dockerconfig_multiple_registries():
    auth = base64.b64encode(b"u:ghp_two").decode()
    raw = _docker_json({
        "ghcr.io": {"password": "ghp_one"},
        "docker.pkg.github.com": {"auth": auth},
    })
    tokens = extract_tokens(".dockerconfigjson", raw)
    sources = {t.source: t.token for t in tokens}
    assert sources == {"ghcr.io": "ghp_one", "docker.pkg.github.com": "ghp_two"}


def test_dockerconfig_detected_by_content_on_other_key():
    raw = _docker_json({"ghcr.io": {"password": "ghp_pw"}})
    # Even if the key name is unusual, an auths document is parsed as docker config.
    tokens = extract_tokens("dockerconfig", raw)
    assert len(tokens) == 1
    assert tokens[0].token == "ghp_pw"


def test_password_preferred_over_auth():
    auth = base64.b64encode(b"u:ghp_fromauth").decode()
    raw = _docker_json({"ghcr.io": {"password": "ghp_pw", "auth": auth}})
    tokens = extract_tokens(".dockerconfigjson", raw)
    assert tokens[0].token == "ghp_pw"
