"""Ack registry: signed tokens, single-use, expiry, wait loop, scripted acks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from care_ladder.channels.ack import AckRegistry, render_ack_page


def _reg(now: datetime | None = None) -> AckRegistry:
    if now is not None:
        return AckRegistry(now=lambda: now)
    return AckRegistry(secret="test-secret")


def test_pending_created_with_signed_token_and_url():
    reg = _reg()
    p = reg.create_pending("inc1", "rung1", "slack", "help room 4", 300, "https://app.example")
    assert p.ack_url.startswith("https://app.example/ack/")
    assert p.deadline > p.created_at
    s = p.summary()
    assert s["incident_id"] == "inc1" and s["rung_id"] == "rung1"
    assert reg.peek(p.token) is not None


def test_acknowledge_records_outcome_and_is_single_use():
    reg = _reg()
    p = reg.create_pending("inc1", "rung1", "slack", "msg", 300, "https://x")
    outcome, reason = reg.acknowledge(p.token, by="RN Alex", note="room 12")
    assert outcome is not None and reason == "ok"
    assert outcome.acked_by == "RN Alex"
    # token is single-use
    again, reason2 = reg.acknowledge(p.token)
    assert again is None and reason2 == "already acknowledged"
    assert reg.peek(p.token) is None


def test_acknowledge_rejects_foreign_token():
    reg = _reg()
    _, reason = reg.acknowledge("garbage-token")
    assert reason == "invalid token signature"


def test_close_pending_removes_window_without_ack():
    reg = _reg()
    p = reg.create_pending("inc1", "rung1", "teams", "msg", 300, "https://x")
    removed = reg.close_pending("inc1", "rung1", reason="ack_timeout")
    assert removed is not None and removed.token == p.token
    assert reg.peek(p.token) is None
    # acknowledging a closed window fails honestly
    outcome, reason = reg.acknowledge(p.token)
    assert outcome is None


def test_pending_list_drops_expired_windows():
    base = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    class Clock:
        def __init__(self): self.t = base
        def __call__(self): return self.t
    clock = Clock()
    reg = AckRegistry(secret="s", now=clock)
    reg.create_pending("inc1", "rung1", "slack", "msg", 10, "https://x", created_at=base)
    clock.t = base + timedelta(seconds=11)
    assert reg.pending_list() == []


def test_wait_for_ack_returns_none_on_timeout():
    reg = _reg()
    out = asyncio.run(reg.wait_for_ack("inc-none", "rung-none", 0.05))
    assert out is None


def test_wait_for_ack_sees_recorded_ack(monkeypatch):
    reg = _reg()
    p = reg.create_pending("inc1", "rung1", "slack", "msg", 5, "https://x")

    async def scenario():
        async def acker():
            await asyncio.sleep(0.05)
            reg.acknowledge(p.token, by="caretaker")
        await asyncio.gather(acker(), reg.wait_for_ack("inc1", "rung1", 2))
        return reg.outcome_for("inc1", "rung1")

    outcome = asyncio.run(scenario())
    assert outcome is not None and outcome.acked_by == "caretaker"


def test_schedule_auto_ack_arms_and_fires():
    reg = _reg()

    async def scenario():
        assert reg.schedule_auto_ack("inc1", after_sec=0.05, by="Nurse Alex")
        await asyncio.sleep(0.02)
        p = reg.create_pending("inc1", "rungA", "slack", "msg", 30, "https://x")
        out = await reg.wait_for_ack("inc1", "rungA", 5)
        return p, out

    pending, outcome = asyncio.run(scenario())
    assert outcome is not None
    assert outcome.acked_by == "Nurse Alex"
    assert outcome.rung_id == "rungA"


def test_render_ack_page_ok_and_gone():
    reg = _reg()
    p = reg.create_pending("inc1", "rung1", "slack", "resident needs help", 300, "https://x")
    html = render_ack_page(p)
    assert "resident needs help" in html
    assert "/acks/" in html  # posts to the ack endpoint
    assert "\u2014" not in html
    gone = render_ack_page(None)
    assert "unavailable" in gone or "invalid" in gone


def test_token_expiry_fail_closed():
    from itsdangerous import SignatureExpired

    base = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)

    class Clock:
        def __init__(self): self.t = base
        def __call__(self): return self.t

    clock = Clock()
    reg = AckRegistry(secret="s", now=clock)
    p = reg.create_pending("inc1", "rung1", "slack", "msg", 5, "https://x", created_at=base)
    # advance far past deadline+grace: serializer TTL check fires first
    clock.t = base + timedelta(hours=2)
    outcome, reason = reg.acknowledge(p.token)
    assert outcome is None
    assert reason in ("token expired", "ack window closed")
