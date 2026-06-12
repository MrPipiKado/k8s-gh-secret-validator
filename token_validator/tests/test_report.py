from datetime import datetime, timezone

from token_validator.config import TeamsConfig
from token_validator.models import Status, TokenResult
from token_validator.report import TeamsReporter


def _result(status):
    return TokenResult(
        namespace="default", name="s", key="token", source="token",
        token_type="classic PAT", status=status,
        expires_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        class Resp:
            def raise_for_status(self_inner):
                return None
        return Resp()


def test_disabled_does_not_post(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("token_validator.report.requests.post", rec)
    TeamsReporter(TeamsConfig(enabled=False, webhook_url="https://x")).report(
        [_result(Status.EXPIRED)])
    assert rec.calls == []


def test_enabled_without_url_does_not_post(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("token_validator.report.requests.post", rec)
    TeamsReporter(TeamsConfig(enabled=True, webhook_url="")).report(
        [_result(Status.EXPIRED)])
    assert rec.calls == []


def test_no_actionable_rows_does_not_post(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("token_validator.report.requests.post", rec)
    TeamsReporter(TeamsConfig(enabled=True, webhook_url="https://x")).report(
        [_result(Status.OK), _result(Status.NO_EXPIRY), _result(Status.SKIPPED)])
    assert rec.calls == []


def test_posts_on_actionable(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("token_validator.report.requests.post", rec)
    TeamsReporter(TeamsConfig(enabled=True, webhook_url="https://x")).report(
        [_result(Status.EXPIRED), _result(Status.OK)])
    assert len(rec.calls) == 1
    url, payload = rec.calls[0]
    assert url == "https://x"
    assert payload["@type"] == "MessageCard"
    # Only the actionable (EXPIRED) row should appear.
    assert len(payload["sections"][0]["facts"]) == 1
