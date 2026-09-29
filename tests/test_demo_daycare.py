"""Task 6: daycare demo - common-zone fixture, no spoken check-in, child vocabulary."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client_facility(monkeypatch):
    import sys

    _appmod = sys.modules["care_ladder.api.app"]
    _appmod._FACILITY_STATES.clear()
    _appmod._SETTINGS_OVERRIDES.clear()
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t6")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"}).status_code == 200
    return c


def test_daycare_fixture_runs_and_skips_speech(client_facility):
    r = client_facility.post("/demo/run", json={"fixture": "daycare_common_no_visibility"})
    assert r.status_code == 200
    inc = client_facility.get(f"/incidents/{r.json()['incident_id']}").json()
    events = inc.get("events") or []
    speaker = [e for e in events if e.get("tool") == "speaker_prompt"]
    assert speaker and all(e["detail"].get("skipped") for e in speaker), "daycare common zone must skip spoken check-in"
    assert speaker[0]["detail"]["reason"] == "common_zone_no_spoken_checkin"


def test_daycare_fixture_opens_case_with_child(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "daycare_common_no_visibility"}).status_code == 200
    alerts = client_facility.get("/facility/alerts").json()
    queue = alerts.get("queue") or alerts.get("alerts")
    assert queue, "daycare fixture must open/page a case"
    row = queue[0]
    assert row["subject_kind"] == "child"
    assert row["subject_display_name"]
    assert row["place_label"]


def test_daycare_sets_facility_type(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "daycare_common_no_visibility"}).status_code == 200
    s = client_facility.get("/facility/settings").json()
    assert s["facility_type"] == "daycare_kids"
    assert s["vocabulary"]["subject"] == "child"
    assert s["vocabulary"]["place"] == "classroom"
    assert s["concurrency"]["pin_peek"] is True


def test_demo_daycare_yaml_all_common():
    from pathlib import Path

    import yaml

    data = yaml.safe_load(Path("configs/demo_daycare.yaml").read_text())
    zones = data.get("zones") or []
    assert zones, "daycare plan needs zones"
    assert all(z.get("kind") == "common" for z in zones)


def test_ui_has_daycare_demo_button(client_facility):
    html = client_facility.get("/ui/facility/").text
    assert "daycare_common_no_visibility" in html
    assert "Daycare demo" in html
