"""Reporters turn validation results into output / alerts.

``ConsoleReporter`` always runs. ``TeamsReporter`` is implemented but disabled by
default; it only fires when explicitly enabled and there are actionable rows.
"""

from __future__ import annotations

import abc
import logging
from collections import Counter
from typing import List

import requests

from .config import TeamsConfig
from .models import Status, TokenResult

log = logging.getLogger(__name__)


class Reporter(abc.ABC):
    @abc.abstractmethod
    def report(self, results: List[TokenResult]) -> None:
        ...


def _fmt_expires(r: TokenResult) -> str:
    if r.expires_at is None:
        return "-"
    return r.expires_at.strftime("%Y-%m-%d %H:%M UTC")


def _fmt_days(r: TokenResult) -> str:
    return "-" if r.days_left is None else str(r.days_left)


class ConsoleReporter(Reporter):
    """Print an aligned table plus a summary line."""

    COLUMNS = ("PROVIDER", "LOCATION", "SECRET", "KEY", "SOURCE", "TYPE", "STATUS",
               "EXPIRES", "DAYS", "MESSAGE")

    def report(self, results: List[TokenResult]) -> None:
        if not results:
            print("No tokens to validate.")
            return

        rows = [
            (r.provider, r.location, r.name, r.key, r.source, r.token_type,
             r.status.value, _fmt_expires(r), _fmt_days(r), r.message)
            for r in results
        ]
        widths = [
            max(len(self.COLUMNS[i]), max(len(row[i]) for row in rows))
            for i in range(len(self.COLUMNS))
        ]

        def line(cells):
            return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

        print(line(self.COLUMNS))
        print("  ".join("-" * w for w in widths))
        for row in rows:
            print(line(row))

        print()
        print(self._summary(results))

    @staticmethod
    def _summary(results: List[TokenResult]) -> str:
        counts = Counter(r.status for r in results)
        parts = [f"{status.value}={counts[status]}"
                 for status in Status if counts[status]]
        return f"Summary: {len(results)} token(s) | " + ", ".join(parts)


class TeamsReporter(Reporter):
    """Post an alert to an MS Teams incoming webhook (disabled by default)."""

    def __init__(self, cfg: TeamsConfig, timeout: int = 10):
        self.cfg = cfg
        self.timeout = timeout

    def report(self, results: List[TokenResult]) -> None:
        if not self.cfg.enabled:
            log.debug("Teams notifier disabled; skipping")
            return
        if not self.cfg.webhook_url:
            log.warning("Teams notifier enabled but no webhook_url/TEAMS_WEBHOOK_URL set; skipping")
            return

        actionable = [r for r in results if r.status.is_actionable()]
        if not actionable:
            log.info("Teams notifier: no actionable tokens; nothing to send")
            return

        payload = self._build_card(actionable)
        try:
            resp = requests.post(self.cfg.webhook_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            log.info("Teams alert sent for %d token(s)", len(actionable))
        except requests.RequestException as exc:
            # Never let a notification failure crash the job.
            log.error("failed to send Teams alert: %s", exc)

    @staticmethod
    def _build_card(actionable: List[TokenResult]) -> dict:
        counts = Counter(r.status for r in actionable)
        summary = ", ".join(f"{s.value}: {counts[s]}" for s in Status if counts[s])

        facts = []
        for r in actionable:
            expires = _fmt_expires(r)
            detail = f"{r.status.value} (expires {expires})" if r.expires_at else r.status.value
            facts.append({
                "name": f"{r.provider}:{r.location}/{r.name}[{r.key}] @ {r.source}",
                "value": detail,
            })

        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "D7263D",
            "summary": "GitHub token expiration alert",
            "title": "GitHub token expiration alert",
            "sections": [{
                "activitySubtitle": summary,
                "facts": facts,
                "markdown": True,
            }],
        }
