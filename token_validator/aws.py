"""Read secrets from AWS Secrets Manager via boto3.

Uses the standard boto3 credential chain (env vars, shared config, or an IAM
role). In EKS the recommended setup is IRSA: annotate the pod's ServiceAccount
with ``eks.amazonaws.com/role-arn`` so it assumes a role allowed to call
``secretsmanager:GetSecretValue``.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

# region -> client
ClientFactory = Callable[[str], object]


class AwsError(Exception):
    """Raised when a secret cannot be read from AWS Secrets Manager."""


def load_client(region: str):
    """Create a Secrets Manager client for ``region``."""
    import boto3  # imported lazily so the dependency is only needed when used

    return boto3.client("secretsmanager", region_name=region)


def client_factory() -> ClientFactory:
    """Return a region -> client function that caches one client per region."""
    cache = {}

    def get(region: str):
        if region not in cache:
            cache[region] = load_client(region)
        return cache[region]

    return get


def get_secret_string(client, secret_id: str) -> str:
    """Fetch a secret's ``SecretString``; raise :class:`AwsError` on failure."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        resp = client.get_secret_value(SecretId=secret_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        raise AwsError(f"{code} reading secret '{secret_id}'") from exc
    except BotoCoreError as exc:
        raise AwsError(f"AWS error reading secret '{secret_id}': {exc}") from exc

    value = resp.get("SecretString")
    if value is None:
        raise AwsError(f"secret '{secret_id}' has no SecretString (binary not supported)")
    return value
