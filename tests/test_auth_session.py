"""Task 2: password + signed-session auth, tenant scoping on the API.

H1: anonymous = 401 under CARE_LADDER_AUTH=on (no shared anonymous tenant).
H2: cross-tenant isolation at the API layer (A fetch of B's incident = 404).
"""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.auth.passwords import hash_password, verify_password
from care_ladder.auth.sessions import SessionData, create_session_token, read_session_token


def test_password_roundtrip():
    h = hash_password("demo-pass-home")
    assert verify_password("demo-pass-home", h)
    assert not verify_password("wrong", h)


def test_session_token_roundtrip():
    secret = "test-secret-not-for-prod"
    tok = create_session_token(
        SessionData(user_id="u1", tenant_id="ten-home", email="demo@careladder.local"),
        secret=secret,
    )
    data = read_session_token(tok, secret=secret)
    assert data is not None
    assert data.tenant_id == "ten-home"
    assert data.email == "demo@careladder.local"
    # wrong secret does not validate
    assert read_session_token(tok, secret="other") is None


def _auth_client(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    app = create_app(store=AuditStore())
    return TestClient(app)


def test_login_sets_cookie_and_me_returns_tenant(monkeypatch):
    client = _auth_client(monkeypatch)
    r = client.post("/auth/login", json={"email": "demo@careladder.local", "password": "demo-pass-home"})
    assert r.status_code == 200
    assert "care_ladder_session" in r.cookies
    me = client.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "demo@careladder.local"
    assert body["tenant"]["mode"] in ("home", "facility")


def test_bad_login_rejected(monkeypatch):
    client = _auth_client(monkeypatch)
    r = client.post("/auth/login", json={"email": "demo@careladder.local", "password": "nope"})
    assert r.status_code == 401


def test_anonymous_gets_401_when_auth_on(monkeypatch):
    # H1: judges use the demo login; anonymous never shares a tenant
    client = _auth_client(monkeypatch)
    assert client.post("/demo/run", json={"fixture": "no_movement_ok"}).status_code == 401
    assert client.get("/incidents").status_code == 401


def test_cross_tenant_incident_isolation(monkeypatch):
    # H2: tenant A's incident is invisible to tenant B through the API
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    app = create_app(store=AuditStore())
    client_a = TestClient(app)
    client_a.post("/auth/login", json={"email": "demo@careladder.local", "password": "demo-pass-home"})
    r = client_a.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert r.status_code == 200
    inc_id = r.json()["incident_id"]

    client_b = TestClient(app)
    client_b.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    assert client_b.get(f"/incidents/{inc_id}").status_code == 404
    assert all(i["id"] != inc_id for i in client_b.get("/incidents").json())


def test_auth_off_keeps_existing_open_behavior(monkeypatch):
    # upstream Path A/B contract unchanged when auth is off (local/dev default)
    monkeypatch.delenv("CARE_LADDER_AUTH", raising=False)
    app = create_app(store=AuditStore())
    client = TestClient(app)
    assert client.get("/incidents").status_code == 200
    r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert r.status_code == 200
