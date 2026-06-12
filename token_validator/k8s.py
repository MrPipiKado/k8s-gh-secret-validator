"""Read secrets from the cluster via the official kubernetes Python client.

No ``kubectl`` shell-out: the app talks to the API directly so it runs cleanly as
an in-cluster CronJob (ServiceAccount auth) and falls back to a local kubeconfig
for development.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

log = logging.getLogger(__name__)


class K8sError(Exception):
    """Raised when a secret cannot be read from the cluster."""


def load_client() -> client.CoreV1Api:
    """Build a CoreV1Api, preferring in-cluster config (the CronJob path)."""
    try:
        config.load_incluster_config()
        log.debug("loaded in-cluster kube config")
    except ConfigException:
        config.load_kube_config()
        log.debug("loaded local kube config")
    return client.CoreV1Api()


def read_secret(api: client.CoreV1Api, namespace: str, name: str) -> "client.V1Secret":
    """Fetch a secret object; raise :class:`K8sError` with a clear message."""
    from kubernetes.client.rest import ApiException

    try:
        return api.read_namespaced_secret(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            raise K8sError(f"secret {namespace}/{name} not found") from exc
        if exc.status in (401, 403):
            raise K8sError(
                f"not authorized to read secret {namespace}/{name} "
                f"(check RBAC): {exc.reason}"
            ) from exc
        raise K8sError(f"error reading secret {namespace}/{name}: {exc.reason}") from exc


def decode_secret_value(secret: "client.V1Secret", key: str) -> Optional[str]:
    """Return the base64-decoded value for ``key``, or ``None`` if absent.

    The ``data`` field is base64-encoded by the API server. ``stringData`` is
    only present on the way in, so we read from ``data``.
    """
    data = secret.data or {}
    if key not in data:
        return None
    return base64.b64decode(data[key]).decode("utf-8")
