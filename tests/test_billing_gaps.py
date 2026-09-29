"""Plan-gap fixes: facility fixture gated by tenant plan; Customer Portal."""

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.billing.plans import tenant_can_use_notify


def _state(client):
    return client._transport.app.state  # TestClient -> ASGI app (private attr; stable here)


def _client(monkeypatch, **env):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    app = create_app(store=AuditStore())
    return TestClient(app)


def _login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


# ---------- facility fixture gating ----------

def test_facility_fixture_requires_facility_plan(monkeypatch):
    """Home-plan tenant cannot run the facility notify ladder (403)."""
    client = _client(monkeypatch)
    _login(client, "demo@careladder.local", "demo-pass-home")  # home tenant
    r = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert r.status_code == 403
    assert "facility" in r.json()["detail"].lower()


def test_facility_fixture_allowed_for_facility_tenant(monkeypatch):
    """demo-facility (plan=demo) can run the facility ladder."""
    client = _client(monkeypatch)
    _login(client, "facility@careladder.local", "demo-pass-facility")
    r = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_and_await_ack" in tools  # redesigned facility ladder (ack rung)
    assert "dial_contact" in tools or "notify_supervisor" in tools


def test_facility_fixture_blocked_when_subscription_lapsed(monkeypatch):
    """Past-due facility tenant loses notify access."""
    client = _client(monkeypatch)
    _login(client, "facility@careladder.local", "demo-pass-facility")
    # simulate a lapsed subscription on the billing tenant record
    app_tenants = _state(client).billing_tenants
    app_tenants["demo-facility"]["status"] = "past_due"
    r = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert r.status_code == 403


def test_auth_off_fixture_still_open():
    """Upstream contract: no auth, no gating (local/demo default)."""
    from care_ladder.api.app import create_app as ca

    client = TestClient(ca(store=AuditStore()))
    assert client.post("/demo/run", json={"fixture": "facility_notify_silence"}).status_code == 200


# ---------- customer portal ----------

def test_portal_503_without_stripe_customer(monkeypatch):
    """Portal needs a persisted Stripe customer; none -> honest 503, not a fake URL."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    client = _client(monkeypatch)
    _login(client, "facility@careladder.local", "demo-pass-facility")
    r = client.post("/billing/portal")
    assert r.status_code == 503
    assert "checkout" not in r.text.lower() or "portal" in r.text.lower()


def test_portal_url_created_when_customer_exists(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    client = _client(monkeypatch)
    _login(client, "facility@careladder.local", "demo-pass-facility")
    # simulate the webhook having persisted a customer id for this tenant
    _state(client).billing_tenants["demo-facility"]["stripe_customer_id"] = "cus_test_123"

    import stripe
    from unittest.mock import patch

    class FakeSession:
        url = "https://billing.stripe.com/p/session/test"

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeSession()

    with patch.object(stripe.billing_portal.Session, "create", side_effect=fake_create):
        r = client.post("/billing/portal")
    assert r.status_code == 200
    assert r.json()["url"].startswith("https://billing.stripe.com/")
    assert "/billing/return" in captured["return_url"]
    assert "from=portal" in captured["return_url"]


def test_webhook_persists_customer_id(monkeypatch):
    """checkout.session.completed must persist customer for later portal use."""
    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    monkeypatch.setenv("CARE_LADDER_ALLOW_UNSIGNED_WEBHOOKS", "1")
    client = _client(monkeypatch)
    import json

    r = client.post(
        "/billing/webhook",
        json={"type": "checkout.session.completed",
              "data": {"object": {"metadata": {"tenant_id": "demo-facility", "plan": "facility_starter"},
                                  "customer": "cus_test_abc"}}},
    )
    assert r.status_code == 200
    assert _state(client).billing_tenants["demo-facility"]["stripe_customer_id"] == "cus_test_abc"


def test_ack_fixtures_gated_too(monkeypatch):
    """All facility fixtures (incl. the new ack demos) sit behind the plan gate."""
    client = _client(monkeypatch)
    _login(client, "demo@careladder.local", "demo-pass-home")
    for fixture in ("facility_ack_resolved", "facility_ack_timeout"):
        r = client.post("/demo/run", json={"fixture": fixture})
        assert r.status_code == 403, f"{fixture} must be gated for home tenants"
