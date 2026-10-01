"""P3 family console re-roll: setup + archive UI, runtime mirror, no ack panel."""

from pathlib import Path

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

_UI = Path(__file__).resolve().parents[1] / "src" / "care_ladder" / "api" / "static" / "index.html"


def _html() -> str:
    return _UI.read_text(encoding="utf-8")


def test_family_console_locked_surfaces():
    html = _html()
    assert "The Marshall home" in html
    assert "Invite family" in html
    assert 'aria-label="Chat runtime status"' in html
    assert "chatstrip" in html
    assert "Open WhatsApp" in html
    assert "Open Telegram" in html
    assert "check-ins answered" in html
    assert "Today with Mom" in html
    assert "If Mom doesn't answer" in html
    assert "Family chat" in html
    assert "Household" in html
    assert "This week" in html
    assert 'id="settings-panel"' in html
    assert 'id="invite-panel"' in html
    assert 'details class="demo"' in html
    assert "Path A · Mom answers OK" in html
    assert 'data-fixture="no_movement_ok"' in html
    assert 'data-fixture="no_movement_silence"' in html
    assert "/ui/facility/" in html
    assert 'id="governance"' in html
    assert "/family/runtime" in html
    assert "/acks/pending" in html
    assert "/billing/checkout" in html
    assert "/billing/portal" in html


def test_family_console_no_em_dashes_or_emoji_icons():
    html = _html()
    assert "\u2014" not in html
    for ch in ("⚠", "✅", "⚠️", "☀", "🌙", "😅"):
        assert ch not in html


def test_family_console_no_coming_soon_or_interactive_ack():
    html = _html()
    assert "coming soon" not in html.lower()
    assert "ack-btn" not in html
    assert "Acknowledge: I'm on it" not in html
    # Fixture chrome lives in the collapsed demo strip, not the header.
    header = html.split("<main>", 1)[0]
    assert "data-fixture=" not in header
    assert "Path A · Mom answers OK" not in header
    assert "Path A · Mom answers OK" in html.split("<main>", 1)[1]


def test_family_console_js_refresh_guards():
    html = _html()
    assert "async function fetchJson" in html
    assert "Array.isArray(list)" in html
    assert "inc.cue" in html
    assert "Array.isArray(inc.events)" in html
    assert "r.ok" in html


def test_family_runtime_auth_off_is_honest_demo_fixture():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/family/runtime")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "demo_fixture"
    assert body["state"] in {"idle", "family_paged"}
    assert "last_message" in body
    assert body["last_message"]["kind"] != "evening_recap"
    assert "whatsapp" in body["channels"]
    assert "telegram" in body["channels"]
    assert "deep_link" in body["channels"]["whatsapp"]
    assert body["channels"]["whatsapp"]["live"] is False
    assert body["channels"]["whatsapp"]["status"] == "demo"
    assert body["channels"]["telegram"]["live"] is False
    assert "hero" in body
    assert "checkins_answered_today" in body["hero"]
    assert "calls_this_week" in body["hero"]
    html = client.get("/ui/").text
    assert "no live bot thread" in html or "demo fixture" in html.lower()


def test_family_hero_week_rate_uses_week_sends():
    from datetime import datetime, timedelta, timezone

    from care_ladder.api.app import _family_hero
    from care_ladder.models import AuditEvent, CueEvent, Incident

    now = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
    older = Incident(
        id="old",
        household_id="h",
        cue=CueEvent(kind="no_movement", confidence=0.9),
        events=[
            AuditEvent(tool="cue", at=now - timedelta(days=3), detail={}),
            AuditEvent(
                tool="speaker_prompt",
                at=now - timedelta(days=3),
                detail={"reply_kind": "ok"},
            ),
        ],
        status="resolved",
    )
    today_open = Incident(
        id="new",
        household_id="h",
        cue=CueEvent(kind="no_movement", confidence=0.9),
        events=[AuditEvent(tool="cue", at=now - timedelta(hours=1), detail={})],
        status="open",
    )
    hero = _family_hero([older, today_open], now)
    assert hero["week"]["checkins_answered"] == 1
    assert hero["week"]["response_rate_pct"] == 50
    assert hero["checkins_answered_today"] == 0
    assert hero["checkins_sent_today"] == 1


def test_family_runtime_auth_on_requires_session(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "family-console-test")
    client = TestClient(create_app(store=AuditStore()))
    assert client.get("/family/runtime").status_code == 401
    assert (
        client.post(
            "/auth/login",
            json={"email": "demo@careladder.local", "password": "demo-pass-home"},
        ).status_code
        == 200
    )
    r = client.get("/family/runtime")
    assert r.status_code == 200
    assert r.json()["source"] == "demo_fixture"


def test_family_runtime_hero_from_path_a():
    client = TestClient(create_app(store=AuditStore()))
    empty = client.get("/family/runtime").json()["hero"]
    assert empty["checkins_answered_today"] == 0
    assert empty["calls_this_week"] == 0
    run = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert run.status_code == 200
    hero = client.get("/family/runtime").json()["hero"]
    assert hero["checkins_answered_today"] >= 1
    assert hero["calls_this_week"] == 0
    assert hero["since_last_response"] is not None


def test_family_runtime_mirrors_pending_ack_without_claiming_bot(monkeypatch):
    from care_ladder.api.app import app_module_registry

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "family-console-test")
    client = TestClient(create_app(store=AuditStore()))
    assert (
        client.post(
            "/auth/login",
            json={"email": "demo@careladder.local", "password": "demo-pass-home"},
        ).status_code
        == 200
    )
    registry = app_module_registry()
    pending = registry.create_pending(
        "inc-mirror",
        "rung-page",
        "whatsapp",
        "Mom did not answer the check-in",
        300,
        "https://x",
        tenant_id="demo-home",
    )
    try:
        body = client.get("/family/runtime").json()
        assert body["state"] == "family_paged"
        assert body["pending_ack"]["incident_id"] == pending.incident_id
        assert body["pending_ack"].get("token") is None  # mirror only; no console ack token
        assert "demo" in body["source"]
    finally:
        registry.close_pending(pending.incident_id, pending.rung_id, reason="test_cleanup")


def test_ui_served_as_family_console():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Path A" in r.text
    assert "family" in r.text.lower()
    assert "Caregiver console" not in r.text
