"""Stretch S1: CSV audit export."""
import io

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "csv-test")
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def test_csv_export_shape_and_content(client):
    _facility_login(client)
    iid = client.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]

    r = client.get("/facility/audit/export.csv")
    assert r.status_code == 200
    assert "csv" in r.headers.get("content-type", "")
    assert "attachment" in r.headers.get("content-disposition", "")

    lines = r.text.strip().splitlines()
    assert lines[0].startswith("case_id,human_id,incident_id")
    row = next(l for l in lines[1:] if iid in l)
    assert "from_negative_reply" in row
    assert "P1" in row


def test_csv_requires_session(client):
    assert client.get("/facility/audit/export.csv").status_code == 401
