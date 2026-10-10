"""Auth-on home Path A/B: list → detail → frames must share the tenant store.

Live Galuxium (CARE_LADDER_AUTH=on) wrote incidents into a per-tenant memory
store while GET /incidents/{id}/frames still read application.state.store, so
frames 404'd with "incident not found" even when GET /incidents/{id} worked.
The caregiver console then called .json() on non-OK detail payloads and
crashed mid-refresh after updating the stats counters. Empty-state cards
with non-zero Incidents/Resolved.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

_UI = Path(__file__).resolve().parents[1] / "src" / "care_ladder" / "api" / "static" / "index.html"


def _home_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    client = TestClient(create_app(store=AuditStore()))
    r = client.post(
        "/auth/login",
        json={"email": "demo@careladder.local", "password": "demo-pass-home"},
    )
    assert r.status_code == 200, r.text
    return client


def test_auth_on_home_path_b_list_detail_frames_consistent(monkeypatch):
    client = _home_client(monkeypatch)
    run = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert run.status_code == 200, run.text
    inc_id = run.json()["incident_id"]

    listed = client.get("/incidents")
    assert listed.status_code == 200
    assert any(item["id"] == inc_id for item in listed.json())

    detail = client.get(f"/incidents/{inc_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["cue"]["kind"] == "no_movement"
    tools = [e["tool"] for e in body["events"]]
    assert "dial_contact" in tools

    frames = client.get(f"/incidents/{inc_id}/frames")
    assert frames.status_code == 200, frames.text
    listing = frames.json()
    assert listing["count"] == 0
    assert listing["frame_urls"] == []


def test_auth_on_home_path_a_then_path_b_both_listable(monkeypatch):
    client = _home_client(monkeypatch)
    a = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    b = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert a.status_code == 200 and b.status_code == 200
    ids = {a.json()["incident_id"], b.json()["incident_id"]}
    listed = {item["id"] for item in client.get("/incidents").json()}
    assert ids <= listed
    for inc_id in ids:
        assert client.get(f"/incidents/{inc_id}").status_code == 200
        assert client.get(f"/incidents/{inc_id}/frames").status_code == 200


def test_ui_refresh_guards_non_ok_detail_payloads():
    html = _UI.read_text(encoding="utf-8")
    assert "async function fetchJson" in html
    assert "Array.isArray(list)" in html
    assert "inc.cue" in html
    # Must not assume a detail payload has .cue/.events (401/404 `{detail: ...}`).
    assert "Array.isArray(inc.events)" in html
    assert "r.ok" in html


def test_auth_on_postgres_tenant_store_survives_app_rebuild(monkeypatch, tmp_path):
    db = tmp_path / "saas.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db}")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")

    client = TestClient(create_app())
    assert (
        client.post(
            "/auth/login",
            json={"email": "demo@careladder.local", "password": "demo-pass-home"},
        ).status_code
        == 200
    )
    run = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert run.status_code == 200
    inc_id = run.json()["incident_id"]
    assert client.get(f"/incidents/{inc_id}/frames").status_code == 200

    # New process / Render restart: same DATABASE_URL, no in-memory leftover.
    client2 = TestClient(create_app())
    assert (
        client2.post(
            "/auth/login",
            json={"email": "demo@careladder.local", "password": "demo-pass-home"},
        ).status_code
        == 200
    )
    detail = client2.get(f"/incidents/{inc_id}")
    assert detail.status_code == 200, detail.text
    assert "dial_contact" in [e["tool"] for e in detail.json()["events"]]
    assert client2.get(f"/incidents/{inc_id}/frames").status_code == 200
