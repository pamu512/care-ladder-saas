"""Landing page (Task 9): pricing, facility wedge, demo login flow."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

DEMO_USERS = {
    "home": ("demo@careladder.local", "demo-pass-home"),
    "facility": ("facility@careladder.local", "demo-pass-facility"),
}


def test_landing_has_pricing_and_facility_wedge():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/")
    assert r.status_code == 200
    text = r.text.lower()
    assert "facility" in text
    # Bare "$9" also matches "$99"; require the Home /mo marker.
    assert "$9<small>/mo" in r.text or "$9/mo" in r.text
    assert "$49" in r.text
    assert "$99" in r.text
    assert "$29" not in r.text
    assert "$199" not in r.text
    assert "$499" not in r.text
    assert "not a medical" in text or "not medical" in text
    assert "diagnoses patients" not in text and "clinical accuracy" not in text
    assert "demo" in text


def test_landing_links_to_ui():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/")
    assert "/ui" in r.text


def test_landing_demo_login_home():
    client = TestClient(create_app(store=AuditStore()))
    email, password = DEMO_USERS["home"]
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    assert r.json()["tenant"]["mode"] == "home"


def test_landing_demo_login_facility():
    client = TestClient(create_app(store=AuditStore()))
    email, password = DEMO_USERS["facility"]
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    assert r.json()["tenant"]["mode"] == "facility"


def test_landing_demo_login_bad_password_401():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post(
        "/auth/login", json={"email": "demo@careladder.local", "password": "wrong"}
    )
    assert r.status_code == 401


def test_landing_footer_disclaimers_present():
    client = TestClient(create_app(store=AuditStore()))
    html = client.get("/").text
    assert "fail-closed" in html.lower() or "emergency" in html.lower()
    assert "911 dispatch" not in html.lower()
    assert "hipaa" not in html.lower()
