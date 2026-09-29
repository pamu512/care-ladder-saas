"""P1 Telegram adapter v2: inline keyboard payload, callback → ack, poll/hook."""

from __future__ import annotations

import httpx2 as httpx

from care_ladder.channels.ack import AckRegistry
from care_ladder.channels.bot import family_alert_buttons
from care_ladder.channels.router import (
    TelegramAdapter,
    TelegramInbound,
    telegram_inline_keyboard,
    telegram_mode,
)


def test_inline_keyboard_payload_shape():
    buttons = family_alert_buttons("Sarah")
    markup = telegram_inline_keyboard(buttons, callback_id="abc123")
    rows = markup["inline_keyboard"]
    assert len(rows) == 3
    texts = [row[0]["text"] for row in rows]
    datas = [row[0]["callback_data"] for row in rows]
    assert texts[0] == "I'm on it. I'll call her myself"
    assert texts[1] == "Call Mom now"
    assert "Sarah" in texts[2]
    assert all(d.startswith("cl:") and d.endswith(":abc123") for d in datas)
    assert datas[0] == "cl:ack:abc123"
    blob = "".join(texts)
    assert "\u2014" not in blob


def test_notify_alert_posts_sendmessage_with_keyboard(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")
    sent: list[dict] = []

    async def fake_post(self, url, *, json=None, **kw):
        sent.append({"url": url, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url), json={"ok": True, "result": {"message_id": 44}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    adapter = TelegramAdapter()
    res = adapter.notify_alert("Mom didn't answer. Paging you now.", callback_id="tok12", next_contact="Sarah")
    assert res["adapter"] == "telegram"
    assert res["delivered"] is True
    body = sent[0]["json"]
    assert sent[0]["url"].endswith("/botT123/sendMessage")
    assert body["chat_id"] == "-100999"
    assert "reply_markup" in body
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "cl:ack:tok12"
    assert "\u2014" not in body["text"]


def test_notify_alert_stays_stub_without_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    res = TelegramAdapter().notify_alert("page", callback_id="x")
    assert res["adapter"] == "stub"
    assert res["channel"] == "telegram"
    assert res["delivered"] is True


def test_callback_query_parses_to_inbound_ack():
    inbound = TelegramAdapter.parse_update(
        {
            "update_id": 1,
            "callback_query": {
                "id": "cq1",
                "data": "cl:ack:tok12",
                "from": {"first_name": "James", "id": 9},
                "message": {"message_id": 77, "chat": {"id": -100999}},
            },
        }
    )
    assert inbound is not None
    assert inbound.action == "ack"
    assert inbound.callback_id == "tok12"
    assert inbound.msg_ref == "77"
    assert inbound.by == "James"
    assert inbound.chat_ref == "-100999"
    assert inbound.origin == "button"


def test_numbered_text_parses_to_inbound_reply():
    inbound = TelegramAdapter.parse_update(
        {
            "update_id": 2,
            "message": {
                "message_id": 80,
                "chat": {"id": -100999},
                "from": {"first_name": "James"},
                "text": "1",
            },
        }
    )
    assert inbound is not None
    assert inbound.action == "ack"
    assert inbound.origin == "reply"
    assert inbound.msg_ref == "80"
    assert inbound.text == "1"


def test_callback_routes_to_registry_first_wins():
    reg = AckRegistry(secret="tg-v2")
    pending = reg.create_pending("inc1", "page_family", "telegram", "page", 300, "https://x")
    adapter = TelegramAdapter()
    inbound = TelegramAdapter.parse_update(
        {
            "callback_query": {
                "id": "cq",
                "data": f"cl:ack:{pending.token[:12]}",
                "from": {"first_name": "James"},
                "message": {"message_id": 5, "chat": {"id": 1}},
            }
        }
    )
    assert inbound is not None
    outcome, reason = adapter.ack_from_inbound(inbound, reg, token=pending.token)
    assert reason == "ok" and outcome is not None
    assert outcome.channel == "telegram"
    assert outcome.msg_ref == "5"
    assert outcome.origin == "button"
    again, reason2 = adapter.ack_from_inbound(inbound, reg, token=pending.token)
    assert again is None and reason2 == "already acknowledged"


def test_telegram_mode_defaults_to_poll(monkeypatch):
    monkeypatch.delenv("TELEGRAM_MODE", raising=False)
    assert telegram_mode() == "poll"
    monkeypatch.setenv("TELEGRAM_MODE", "hook")
    assert telegram_mode() == "hook"
    monkeypatch.setenv("TELEGRAM_MODE", "webhook")
    assert telegram_mode() == "hook"
    monkeypatch.setenv("TELEGRAM_MODE", "POLL")
    assert telegram_mode() == "poll"


def test_telegram_inbound_type_exported():
    assert TelegramInbound.__annotations__["action"]


def test_telegram_webhook_first_wins_without_live_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    from fastapi.testclient import TestClient

    from care_ladder.api.app import app_module_registry, create_app
    from care_ladder.audit.store import AuditStore

    client = TestClient(create_app(store=AuditStore()))
    registry = app_module_registry()
    pending = registry.create_pending("inc-hook", "page_family", "telegram", "page", 300, "https://x")
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
    kept = registry.outcome_for("inc-hook", "page_family")
    assert kept is not None
    assert kept.acked_by == "James"
    assert kept.msg_ref == "9"
    assert kept.origin == "button"
    again = client.post(
        "/telegram/webhook",
        json={
            "callback_query": {
                "id": "cq2",
                "data": f"cl:ack:{pending.token[:12]}",
                "from": {"first_name": "Sarah"},
                "message": {"message_id": 10, "chat": {"id": -1001}},
            }
        },
    )
    assert again.status_code == 200
    assert registry.outcome_for("inc-hook", "page_family").acked_by == "James"


def test_family_telegram_page_fixture_stub_path():
    from fastapi.testclient import TestClient

    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore

    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "family_telegram_page"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_and_await_ack" in tools
    assert "bot" in tools
    bot = [e for e in inc["events"] if e["tool"] == "bot"]
    assert any(e["detail"].get("message_kind") == "inform_card" for e in bot)
    assert all(e.get("at") for e in bot)
    assert all("\u2014" not in str(e["detail"].get("text") or "") for e in bot)
