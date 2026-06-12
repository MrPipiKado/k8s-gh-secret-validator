import textwrap

import pytest

from token_validator.config import ConfigError, load_config


def write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_defaults_applied(tmp_path):
    path = write(tmp_path, """
        secrets:
          - namespace: default
            name: s
            keys: [token]
    """)
    cfg = load_config(path)
    assert cfg.warn_days == 7
    assert cfg.github_api_url == "https://api.github.com"
    assert cfg.teams.enabled is False
    assert cfg.secrets[0].name == "s"


def test_missing_secrets_raises(tmp_path):
    path = write(tmp_path, "warn_days: 3\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_keys_raises(tmp_path):
    path = write(tmp_path, """
        secrets:
          - name: s
    """)
    with pytest.raises(ConfigError):
        load_config(path)


def test_env_var_overrides_blank_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://hook")
    path = write(tmp_path, """
        secrets:
          - name: s
            keys: [token]
        notifiers:
          teams:
            enabled: true
    """)
    cfg = load_config(path)
    assert cfg.teams.webhook_url == "https://hook"
    assert cfg.teams.enabled is True
