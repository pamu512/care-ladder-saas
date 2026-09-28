"""Remediation Wave 3: F2 acks tenant-scoped, F5 upload auth+tenant store, N7 policy."""
import io

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "wave3-test")
    app = create_app(store=AuditStore())
    return TestClient(app)


def _login(client, email="facility@careladder.local", pw="demo-pass-facility"):
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200


# F2: /acks/pending requires session + tenant scope
def test_f2_acks_pending_requires_session(client):
    assert client.get("/acks/pending").status_code == 401


def test_f2_acks_pending_home_tenant_gets_facility_scope_check(client):
    _login(client, "demo@careladder.local", "demo-pass-home")
    r = client.get("/acks/pending")
    assert r.status_code == 200  # home tenant may ask; must see only own (none here)
    assert r.json() == []


# F5: /demo/upload requires session when auth on
def test_f5_upload_requires_session(client):
    r = client.post("/demo/upload", files={"file": ("x.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")})
    # may be 401 (auth gate) before any processing
    assert r.status_code == 401


def test_f5_upload_authed_accepted_into_job(client):
    _login(client)
    r = client.post("/demo/upload", files={"file": ("x.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42minimal"), "video/mp4")})
    assert r.status_code in (200, 202), r.text
    assert "incident_id" in r.json()
