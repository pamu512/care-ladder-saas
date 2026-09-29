"""Task 7: rehab demo - common gym zone, patient vocabulary."""
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
    monkeypatch.setenv("SESSION_SECRET", "tm-t7")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"}).status_code == 200
    return c


def test_rehab_fixture_skips_speech_in_gym(client_facility):
    r = client_facility.post("/demo/run", json={"fixture": "rehab_gym_no_visibility"})
    assert r.status_code == 200
    inc = client_facility.get(f"/incidents/{r.json()['incident_id']}").json()
    speaker = [e for e in inc["events"] if e["tool"] == "speaker_prompt"]
    assert speaker and all(e["detail"].get("skipped") for e in speaker)
    assert speaker[0]["detail"]["zone_id"] == "gym"


def test_rehab_case_carries_patient(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "rehab_gym_no_visibility"}).status_code == 200
    alerts = client_facility.get("/facility/alerts").json()
    queue = alerts.get("queue") or alerts.get("alerts")
    row = queue[0]
    assert row["subject_kind"] == "patient"
    assert row["subject_display_name"] == "Dana Patel"
    assert row["place_label"] == "Gym"


def test_rehab_settings_switch(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "rehab_gym_no_visibility"}).status_code == 200
    s = client_facility.get("/facility/settings").json()
    assert s["facility_type"] == "rehab"
    assert s["vocabulary"]["subject"] == "patient"
    assert s["sla_ack_sec"] == 90


def test_demo_rehab_yaml_zone_kinds():
    from pathlib import Path

    import yaml

    data = yaml.safe_load(Path("configs/demo_rehab.yaml").read_text())
    kinds = {z["id"]: z.get("kind", "private") for z in data["zones"]}
    assert kinds["bay_1"] == "private"
    assert kinds["gym"] == "common"
