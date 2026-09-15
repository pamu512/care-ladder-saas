"""Spec §10 Path A: verbal OK resolves without any dial (judge demo path)."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def _run(client: TestClient, fixture: str) -> dict:
    resp = client.post("/demo/run", json={"fixture": fixture})
    assert resp.status_code == 200, resp.text
    inc_id = resp.json()["incident_id"]
    detail = client.get(f"/incidents/{inc_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()


def test_no_movement_ok_resolves_without_dial():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        inc = _run(client, "no_movement_ok")
    tools = [e["tool"] for e in inc["events"]]
    assert "speaker_prompt" in tools
    assert inc["status"] == "resolved"
    assert "dial_contact" not in tools
    assert "emergency" not in tools
    # reply captured in audit trace
    speaker = next(e for e in inc["events"] if e["tool"] == "speaker_prompt")
    assert speaker["detail"]["reply_kind"] == "ok"


def test_unknown_fixture_rejected_400():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        resp = client.post("/demo/run", json={"fixture": "nonsense"})
    assert resp.status_code == 400


def test_ui_served_with_caregiver_console():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Caregiver" in resp.text
    assert "Path A" in resp.text
