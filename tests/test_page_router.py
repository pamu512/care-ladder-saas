"""Multi-channel page router: honest stubs, real-send paths, unknown channels."""

from __future__ import annotations

import asyncio

import httpx2 as httpx
import pytest

from care_ladder.channels.router import (
    PageRouter,
    SlackAdapter,
    TeamsAdapter,
    TelegramAdapter,
    WhatsAppAdapter,
    channel_active_envs,
)


def test_stub_when_no_credentials(monkeypatch):
    for var in (
        "SLACK_WEBHOOK_URL",
        "TEAMS_WEBHOOK_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "WHATSAPP_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_TO",
    ):
        monkeypatch.delenv(var, raising=False)
    router = PageRouter()
    for cid in ("slack", "teams", "whatsapp", "telegram"):
        res = router.get(cid).notify("page")
        # honesty convention: adapter stub, delivered recorded per channel
        assert res["adapter"] in ("stub", cid), res
        assert res["channel"] == cid
    assert channel_active_envs() == []


def test_slack_real_post(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/T/B/X")
    sent: list[dict] = []

    async def fake_post(self, url, *, json=None, **kw):
        sent.append({"url": url, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res = SlackAdapter().notify("floor lead needed")
    assert res["adapter"] == "slack"
    assert res["delivered"] is True
    assert sent and "floor lead needed" in sent[0]["json"]["text"]


def test_teams_real_post(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.example/hook")
    sent: list[dict] = []

    async def fake_post(self, url, *, json=None, **kw):
        sent.append({"url": url, "json": json})
        return httpx.Response(202, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res = TeamsAdapter().notify("room 4 check-in")
    assert res["adapter"] == "teams"
    assert res["delivered"] is True
    assert sent and sent[0]["json"] == {"text": "room 4 check-in"}


def test_telegram_real_post(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")
    sent: list[dict] = []

    async def fake_post(self, url, *, json=None, **kw):
        sent.append({"url": url, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res = TelegramAdapter().notify("residents needs help")
    assert res["adapter"] == "telegram"
    assert res["delivered"] is True
    assert sent and sent[0]["url"].endswith("/botT123/sendMessage")
    assert sent[0]["json"]["chat_id"] == "-100999"
    assert channel_active_envs() == ["telegram"]


def test_whatsapp_real_post(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "EAAG")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "99")
    monkeypatch.setenv("WHATSAPP_TO", "+12125550104")
    sent: list[dict] = []

    async def fake_post(self, url, *, json=None, headers=None, **kw):
        sent.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res = WhatsAppAdapter().notify("ack please")
    assert res["adapter"] == "whatsapp"
    assert res["delivered"] is True
    assert sent and "/99/messages" in sent[0]["url"]
    assert sent[0]["headers"]["Authorization"] == "Bearer EAAG"
    assert sent[0]["json"]["to"] == "+12125550104"


def test_channel_error_never_raises(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/T/B/X")

    def boom(self, url, *, json=None, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    res = SlackAdapter().notify("page")
    assert res["delivered"] is False
    assert "network down" in res["error"]
    # ladder must keep walking: result shape stays uniform
    assert res["adapter"] == "slack" and res["message"] == "page"


def test_unknown_channel_routes_to_honest_stub():
    res = PageRouter().get("pagerduty").notify("page")
    assert res["adapter"] == "stub"
    assert res["delivered"] is False
    assert "unknown channel" in res["error"]


def test_router_overrides_injection():
    class Fake:
        id = "slack"

        def notify(self, message):
            return {"adapter": "fake", "channel": "slack", "delivered": True, "message": message}

    router = PageRouter(channels={"slack": Fake()})
    assert router.get("slack").notify("x")["adapter"] == "fake"
    # other channels still default-constructed
    assert router.get("teams").notify("x")["adapter"] in ("stub", "teams")
