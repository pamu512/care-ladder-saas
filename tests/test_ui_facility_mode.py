"""Task 7: UI mode badge + notify/supervisor timeline + facility demo button."""

from pathlib import Path

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

_UI = Path(__file__).resolve().parents[1] / "src" / "care_ladder" / "api" / "static" / "index.html"


def test_ui_has_facility_button_and_mode_badge():
    html = _UI.read_text(encoding="utf-8")
    assert 'data-fixture="facility_notify_silence"' in html
    assert "Facility" in html


def test_ui_renders_notify_and_supervisor_rows():
    # timeline row labels for the new tools exist in the JS render path
    html = _UI.read_text(encoding="utf-8")
    assert "notify_channel" in html
    assert "notify_supervisor" in html


def test_ui_served_and_fixture_incident_lists():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    run = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert run.status_code == 200
    listed = client.get("/incidents").json()
    assert any(i["id"] == run.json()["incident_id"] for i in listed)
