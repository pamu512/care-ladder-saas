"""Stretch S1/S3/S4: CSV export, quiet-hours exposure, real-Slack flag surface."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "stretch-test")
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def test_quiet_hours_in_alerts(client):
    _facility_login(client)
    body = client.get("/facility/alerts").json()
    qh = body.get("quiet_hours")
    assert qh and qh["start"] == "22:00" and qh["end"] == "07:00"
    assert qh["policy"] == "soft_suppress_non_distress"


def test_console_page_renders_quiet_chip_and_csv_button(client):
    html = client.get("/ui/facility/").text
    assert "quiet-chip" in html
    assert "/facility/audit/export.csv" in html or "export.csv" in html
