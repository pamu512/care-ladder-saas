"""P0: POST /telegram/webhook authenticates X-Telegram-Bot-Api-Secret-Token."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import app_module_registry, create_app
from care_ladder.audit.store import AuditStore


def _client():
    return TestClient(create_app(store=AuditStore()))


def _fresh_pending(incident_id: str, rung_id: str = "page_family"):
    """Create pending after clearing shared registry collisions on token[:12]."""
    registry = app_module_registry()
    # Drop any live windows so callback prefixes cannot collide across tests.
    for token in list(getattr(registry, "_pending_by_token", {})):
        p = registry._pending_by_token.get(token)
        if p is not None:
            registry.close_pending(p.incident_id, p.rung_id, reason="test_reset")
    return registry, registry.create_pending(
        incident_id, rung_id, "telegram", "page", 300, "https://x"
    )


def test_stub_mode_webhook_still_accepts_without_secret(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    registry, pending = _fresh_pending("stub-aaa-1")
    with _client() as client:
        r = client.post(
            "/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cq",
                    "data": f"cl:ack:{pending.token[:12]}",
                    "from": {"first_name": "James"},
                    "message": {"message_id": 9, "chat": {"id": -1001}},
                }
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert registry.outcome_for("stub-aaa-1", "page_family") is not None


def test_live_webhook_rejects_forged_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "expected-secret")
    registry, pending = _fresh_pending("forge-bbb-1")
    with _client() as client:
        bad = client.post(
            "/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cq",
                    "data": f"cl:ack:{pending.token[:12]}",
                    "from": {"first_name": "Eve"},
                    "message": {"message_id": 1, "chat": {"id": -1}},
                }
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        missing = client.post(
            "/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cq2",
                    "data": f"cl:ack:{pending.token[:12]}",
                    "from": {"first_name": "Eve"},
                    "message": {"message_id": 2, "chat": {"id": -1}},
                }
            },
        )
    assert bad.status_code == 200
    assert bad.json() == {"ok": False, "handled": False, "reason": "webhook_secret_mismatch"}
    assert missing.status_code == 200
    assert missing.json()["reason"] == "webhook_secret_mismatch"
    assert registry.outcome_for("forge-bbb-1", "page_family") is None
    assert registry.peek(pending.token) is not None


def test_live_webhook_rejects_when_secret_unset(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    with _client() as client:
        r = client.post(
            "/telegram/webhook",
            json={
                "message": {
                    "text": "1",
                    "message_id": 1,
                    "chat": {"id": 1},
                    "from": {"first_name": "X"},
                }
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "webhook_secret_unset"


def test_live_webhook_accepts_valid_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "expected-secret")
    registry, pending = _fresh_pending("okxx-ccc-1")
    with _client() as client:
        r = client.post(
            "/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cq",
                    "data": f"cl:ack:{pending.token[:12]}",
                    "from": {"first_name": "James"},
                    "message": {"message_id": 9, "chat": {"id": -1001}},
                }
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "expected-secret"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    kept = registry.outcome_for("okxx-ccc-1", "page_family")
    assert kept is not None
    assert kept.acked_by == "James"


def test_set_webhook_includes_secret_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    from care_ladder.channels.router import TelegramAdapter

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp()

    monkeypatch.setattr("httpx2.AsyncClient", _FakeClient)
    adapter = TelegramAdapter()
    result = adapter.set_webhook("https://example.com/telegram/webhook")
    assert result.get("delivered") is True
    assert captured["json"]["url"] == "https://example.com/telegram/webhook"
    assert captured["json"]["secret_token"] == "hook-secret"
