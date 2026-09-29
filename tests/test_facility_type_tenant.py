"""Type-models Task 1: tenant facility_type + concurrency settings API."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client_facility(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t1")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    assert r.status_code == 200
    return c


@pytest.fixture()
def client_home(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t1")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": "demo@careladder.local", "password": "demo-pass-home"})
    assert r.status_code == 200
    return c


def test_tenant_defaults_facility_type(client_facility):
    r = client_facility.get("/facility/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["facility_type"] in {
        "daycare_kids", "assisted_living", "rehab", "old_age_home"
    }
    assert "concurrency" in body
    assert body["concurrency"]["one_focus"] is True


def test_patch_facility_type(client_facility):
    r = client_facility.patch(
        "/facility/settings",
        json={"facility_type": "daycare_kids"},
    )
    assert r.status_code == 200
    assert r.json()["facility_type"] == "daycare_kids"
    # persists across reads
    assert client_facility.get("/facility/settings").json()["facility_type"] == "daycare_kids"


def test_patch_invalid_facility_type_rejected(client_facility):
    r = client_facility.patch("/facility/settings", json={"facility_type": "spaceship"})
    assert r.status_code == 422


def test_patch_concurrency(client_facility):
    r = client_facility.patch(
        "/facility/settings",
        json={"concurrency": {"one_focus": True, "pin_peek": True, "pin_limit": 3, "multi_own": False}},
    )
    assert r.status_code == 200
    assert r.json()["concurrency"]["pin_peek"] is True


def test_settings_requires_session(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t1")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    assert c.get("/facility/settings").status_code == 401


def test_settings_home_tenant_403(client_home):
    assert client_home.get("/facility/settings").status_code == 403
