"""Task 4: place + person on alerts and cases."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client_facility(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t4")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"}).status_code == 200
    return c


def test_alert_includes_place_and_subject(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    r = client_facility.get("/facility/alerts")
    assert r.status_code == 200
    row = r.json()["alerts"][0] if "alerts" in r.json() else r.json()["queue"][0]
    assert row["place_label"]
    assert row["subject_display_name"] == "Margaret Hale"
    assert row["subject_kind"] == "resident"
    assert row["case"]["subject_display_name"] == "Margaret Hale"
    assert row["case"]["place_label"]


def test_case_out_includes_subject(client_facility):
    assert client_facility.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    r = client_facility.get("/facility/cases")
    cs = r.json()["open"]
    assert cs
    c0 = cs[0]
    assert c0["subject_display_name"] == "Margaret Hale"
    assert c0["place_label"]
    # back-compat alias holds
    assert "room_label" in c0


def test_domain_case_open_from_incident_subject():
    from care_ladder.facility.models import Case

    case = Case.open_from_incident(
        incident_id="inc-1",
        tenant_id="t1",
        room_label="Bay 3",
        origin="from_silence",
        priority="P2",
        subject_display_name="Dana P.",
        subject_kind="patient",
        subject_id="pt-9",
    )
    assert case.subject_display_name == "Dana P."
    assert case.subject_kind == "patient"
    assert case.place_label == "Bay 3"  # place aliases room when unset


def test_ui_card_title_uses_place_and_person(client_facility):
    html = client_facility.get("/ui/facility/").text
    # title line template: {place} · {person or Unknown subject}; human_id secondary
    assert "place_label" in html and "subject_display_name" in html
    assert "Unknown" in html
