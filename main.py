"""CLI entrypoint for the GitHub token expiration validator."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from token_validator.config import ConfigError, load_config
from token_validator.models import Status
from token_validator.report import ConsoleReporter, TeamsReporter
from token_validator.validator import validate


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validate GitHub tokens in Kubernetes secrets and report expiry.",
    )
    p.add_argument("--config", required=True, help="path to the YAML config file")
    p.add_argument("--warn-days", type=int, default=None,
                   help="override the warn window (days) from the config")
    p.add_argument("--json", action="store_true",
                   help="also emit machine-readable JSON results to stdout")
    p.add_argument("--fail-on-expiring", action="store_true",
                   help="exit non-zero if any token is EXPIRED/WARN/INVALID")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def _emit_json(results) -> None:
    payload = []
    for r in results:
        d = asdict(r)
        d["status"] = r.status.value
        d["expires_at"] = r.expires_at.isoformat() if r.expires_at else None
        payload.append(d)
    print(json.dumps(payload, indent=2))


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.warn_days is not None:
        config.warn_days = args.warn_days

    results = validate(config)

    ConsoleReporter().report(results)
    if args.json:
        _emit_json(results)

    TeamsReporter(config.teams).report(results)

    if args.fail_on_expiring and any(r.status.is_actionable() for r in results):
        return 1
    if any(r.status is Status.ERROR for r in results):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
