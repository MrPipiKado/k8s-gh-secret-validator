"""Load and validate the YAML config."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml

from .models import SecretRef

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_WARN_DAYS = 7
TEAMS_WEBHOOK_ENV = "TEAMS_WEBHOOK_URL"


class ConfigError(Exception):
    """Raised when the config file is missing required fields or malformed."""


@dataclass
class TeamsConfig:
    enabled: bool = False
    webhook_url: str = ""


@dataclass
class Config:
    secrets: List[SecretRef]
    warn_days: int = DEFAULT_WARN_DAYS
    github_api_url: str = DEFAULT_GITHUB_API_URL
    teams: TeamsConfig = field(default_factory=TeamsConfig)


def load_config(path: str) -> Config:
    """Parse ``path`` into a :class:`Config`, applying defaults.

    Raises :class:`ConfigError` with a clear message on any structural problem.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

    secrets = _parse_secrets(raw.get("secrets"))
    warn_days = _parse_warn_days(raw.get("warn_days", DEFAULT_WARN_DAYS))
    github_api_url = str(raw.get("github_api_url") or DEFAULT_GITHUB_API_URL).rstrip("/")
    teams = _parse_teams(raw.get("notifiers", {}))

    return Config(
        secrets=secrets,
        warn_days=warn_days,
        github_api_url=github_api_url,
        teams=teams,
    )


def _parse_secrets(raw_secrets) -> List[SecretRef]:
    if not raw_secrets:
        raise ConfigError("config must define a non-empty 'secrets' list")
    if not isinstance(raw_secrets, list):
        raise ConfigError("'secrets' must be a list")

    refs: List[SecretRef] = []
    for i, item in enumerate(raw_secrets):
        if not isinstance(item, dict):
            raise ConfigError(f"secrets[{i}] must be a mapping")
        name = item.get("name")
        if not name:
            raise ConfigError(f"secrets[{i}] is missing 'name'")
        namespace = item.get("namespace", "default")
        keys = item.get("keys")
        if not keys or not isinstance(keys, list):
            raise ConfigError(f"secrets[{i}] ({name}) must define a non-empty 'keys' list")
        refs.append(SecretRef(namespace=str(namespace), name=str(name),
                              keys=[str(k) for k in keys]))
    return refs


def _parse_warn_days(value) -> int:
    try:
        warn_days = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'warn_days' must be an integer, got {value!r}") from exc
    if warn_days < 0:
        raise ConfigError("'warn_days' must be >= 0")
    return warn_days


def _parse_teams(notifiers) -> TeamsConfig:
    if not isinstance(notifiers, dict):
        raise ConfigError("'notifiers' must be a mapping")
    teams_raw = notifiers.get("teams") or {}
    if not isinstance(teams_raw, dict):
        raise ConfigError("'notifiers.teams' must be a mapping")
    # Env var wins over a blank config value so the CronJob can inject a secret.
    webhook_url = str(teams_raw.get("webhook_url") or "").strip()
    webhook_url = os.environ.get(TEAMS_WEBHOOK_ENV, webhook_url).strip()
    return TeamsConfig(
        enabled=bool(teams_raw.get("enabled", False)),
        webhook_url=webhook_url,
    )
