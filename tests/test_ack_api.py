"""HTTP ack surface + demo fixtures: /acks endpoints, console wiring, e2e ack."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def _client() -> TestClient:
    return TestClient(create_app(store=AuditStore()))


def test_demo_context_lists_ack_surface():
    r = _client().get("/demo/context")
    assert r.status_code == 200
    body = r.json()
    assert "ack_channels_active" in body


def test_ack_fixture_resolved_end_to_end():
    client = _client()
    r = client.post("/demo/run", json={"fixture": "facility_ack_resolved"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_and_await_ack" in tools
    resolve = next(e for e in inc["events"] if e["tool"] == "resolve")
    assert resolve["detail"]["reason"] == "caretaker_ack"
    assert "Nurse Alex" in resolve["detail"]["acked_by"]
    # escalation stopped before supervisor/dial
    assert "notify_supervisor" not in tools
    assert "dial_contact" not in tools
    assert inc["status"] == "resolved"
    # scripted ack consumed the pending window
    assert client.get("/acks/pending").json() == []


def test_ack_fixture_timeout_escalates_end_to_end():
    client = _client()
    r = client.post("/demo/run", json={"fixture": "facility_ack_timeout"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "ack_timeout" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    assert inc["status"] == "resolved"  # caregiver answered at dial
    # pending list drains after timeout close
    assert client.get("/acks/pending").json() == []


def test_console_has_ack_panel_and_fixture_buttons():
    from pathlib import Path

    ui = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "care_ladder"
        / "api"
        / "static"
        / "index.html"
    )
    html = ui.read_text(encoding="utf-8")
    assert 'data-fixture="facility_ack_resolved"' in html
    assert 'data-fixture="facility_ack_timeout"' in html
    assert "/acks/pending" in html
    assert "notify_and_await_ack" in html  # timeline label present
    # Ack is mirrored in the chat strip; no interactive console ack surface.
    assert "ack-btn" not in html
    assert "chatstrip" in html


def test_ack_page_renders_for_live_token():
    """Simulate an open window, then GET /ack/{token} without a session."""
    from care_ladder.api.app import app_module_registry
    from care_ladder.channels.ack import AckRegistry

    client = _client()
    registry: AckRegistry = app_module_registry()
    p = registry.create_pending(
        "inc-live", "rung-live", "slack", "resident needs help in room 9", 300, "https://x"
    )
    r = client.get(f"/ack/{p.token}")
    assert r.status_code == 200
    assert "resident needs help in room 9" in r.text
    assert "/acks/" in r.text
    # Without a session tenant, /acks/pending never dumps all windows (P1).
    assert client.get("/acks/pending").json() == []
    # acknowledging via HTTP closes it and records who
    post = client.post(f"/acks/{p.token}", json={"by": "RN Dana", "note": "room 9"})
    assert post.status_code == 200
    body = post.json()
    assert body["acked_by"] == "RN Dana"
    assert client.get("/acks/pending").json() == []
    # single use: second POST is 410
    assert client.post(f"/acks/{p.token}", json={}).status_code == 410


def test_bad_token_410():
    client = _client()
    r = client.post("/acks/not-a-real-token", json={})
    assert r.status_code == 410
    r2 = client.get("/ack/not-a-real-token")
    assert r2.status_code == 200
    assert "unavailable" in r2.text or "invalid" in r2.text
