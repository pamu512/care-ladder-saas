"""Remediation Wave 2: F1 webhook PG persistence, F6 checkout tenant, F4 stub gate,
F8 plan enum, F3 ack absolute base URL."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base, Tenant


@pytest.fixture()
def engine():
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        s.add(Tenant(id="demo-facility", name="Demo Facility", mode="facility", plan="demo"))
        s.add(Tenant(id="demo-home", name="Demo Home", mode="home", plan="home"))
        s.commit()
    return eng


@pytest.fixture()
def client(monkeypatch, engine):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "wave2-test")
    app = create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=engine))
    return TestClient(app)


def _login(client, email="facility@careladder.local", pw="demo-pass-facility"):
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200


def _signed_webhook(client, monkeypatch, payload: dict):
    """Demo env accepts unsigned (documented); we assert the PG write, which is the fix."""
    import json as _json

    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    return client.post(
        "/billing/webhook",
        content=_json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


# F1: webhook persists plan/status to Postgres, not just memory
def test_f1_webhook_persists_plan_status_to_pg(client, engine, monkeypatch):
    _login(client)
    r = _signed_webhook(client, monkeypatch, {
        "type": "checkout.session.completed",
        "data": {"object": {
            "customer": "cus_test_123",
            "metadata": {"tenant_id": "demo-facility", "plan": "facility_starter"},
            "subscription": "sub_test_1",
        }},
    })
    assert r.status_code == 200, r.text
    with sessionmaker(bind=engine)() as s:
        row = s.get(Tenant, "demo-facility")
        assert row.plan == "facility_starter", "plan must persist to PG"
        assert row.subscription_status == "active", "status must persist to PG"
        assert row.stripe_customer_id == "cus_test_123"


# F6: checkout uses session tenant
def test_f6_checkout_uses_session_tenant(client, monkeypatch):
    _login(client)  # facility session
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    import care_ladder.billing.stripe_checkout as sc

    captured = {}

    class FakeCheckout:
        @staticmethod
        def create(**kw):
            captured.update(kw)
            return type("S", (), {"url": "https://checkout.stripe.com/test"})()

    import types
    monkeypatch.setattr(sc, "stripe", types.SimpleNamespace(
        checkout=FakeCheckout, StripeError=Exception), raising=False)
    r = client.post("/billing/checkout", json={"plan": "facility_starter"})
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        md = captured.get("metadata") or {}
        assert md.get("tenant_id") == "demo-facility", f"tenant must come from session: {md}"


def test_f6_checkout_anon_401(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    r = client.post("/billing/checkout", json={"plan": "home"})
    assert r.status_code == 401


# F4: stub-success gated to demo env
def test_f4_stub_success_gated(client, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "production")
    r = client.get("/billing/stub-success", params={"plan": "facility_starter"})
    assert r.status_code in (403, 404), "non-demo env must not flip plans"

    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    r2 = client.get("/billing/stub-success", params={"plan": "facility_starter"})
    assert r2.status_code == 200


# F8: invalid plan rejected
def test_f8_invalid_plan_422(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    r = client.post("/billing/checkout", json={"plan": "banana"})
    assert r.status_code == 422


# F3: ack URLs absolute when base env set
def test_f3_public_base_url_env(monkeypatch):
    from care_ladder.api.app import _public_base_url

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://care-ladder-saas.onrender.com")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://ignored.example")
    assert _public_base_url() == "https://care-ladder-saas.onrender.com"

    monkeypatch.delenv("PUBLIC_BASE_URL")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://care-ladder-saas.onrender.com")
    assert _public_base_url() == "https://care-ladder-saas.onrender.com", "Render fallback must work"

    monkeypatch.delenv("RENDER_EXTERNAL_URL")
    assert _public_base_url() == ""
