"""Task 8: Stripe Checkout + fail-closed webhook + plan gating.

C2 review fix baked in: webhook with unset secret in non-demo env REJECTS;
stub checkout only exists in demo env; both rejection paths tested.
"""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.billing.plans import PlanId, tenant_can_use_notify


# ---------- plans / gating ----------

def test_plan_gates():
    assert tenant_can_use_notify({"mode": "facility", "plan": "facility_starter", "status": "active"})
    assert tenant_can_use_notify({"mode": "facility", "plan": "facility_growth", "status": "active"})
    assert tenant_can_use_notify({"mode": "home", "plan": "demo", "status": "demo"})
    assert not tenant_can_use_notify({"mode": "home", "plan": "home", "status": "active"}), \
        "home plan must never notify"
    assert not tenant_can_use_notify({"mode": "facility", "plan": "facility_starter", "status": "past_due"}), \
        "lapsed subscription loses notify"


# ---------- checkout ----------

def test_checkout_stub_only_in_demo(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/billing/checkout", json={"plan": "facility_starter"})
    assert r.status_code == 200
    assert "/billing/stub-success" in r.json()["url"]


def test_checkout_503_when_no_key_in_prod(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "production")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/billing/checkout", json={"plan": "facility_starter"})
    assert r.status_code == 503, "prod must never fake a checkout"
    assert "stub" not in r.text


def test_checkout_sets_stripe_api_key_before_session_create(monkeypatch):
    """Live 500: key was read from env but never assigned to stripe.api_key."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc123")
    monkeypatch.setenv("STRIPE_PRICE_HOME", "price_home_1")
    import stripe
    from care_ladder.billing.stripe_checkout import create_checkout_url

    monkeypatch.setattr(stripe, "api_key", None)
    captured: dict[str, str | None] = {}

    class FakeSession:
        url = "https://checkout.stripe.com/c/pay/cs_test"

    def fake_create(**_kwargs):
        captured["api_key"] = stripe.api_key
        return FakeSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    url = create_checkout_url("home", "demo-facility")
    assert captured["api_key"] == "sk_test_abc123"
    assert url == FakeSession.url


def test_checkout_maps_stripe_errors_to_503(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_bad")
    monkeypatch.setenv("STRIPE_PRICE_FACILITY", "price_fac_1")
    import stripe

    def boom(**_kwargs):
        raise stripe.AuthenticationError("Invalid API Key provided")

    monkeypatch.setattr(stripe.checkout.Session, "create", boom)
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/billing/checkout", json={"plan": "facility_starter"})
    assert r.status_code == 503, "Stripe auth/API errors must not leak as raw 500"


# ---------- webhook (fail-closed: C2) ----------

def test_webhook_rejects_unsigned_when_no_secret_prod(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "production")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    client = TestClient(create_app(store=AuditStore()))
    r = client.post(
        "/billing/webhook",
        json={"type": "checkout.session.completed", "data": {"object": {"metadata": {"tenant_id": "demo-facility"}}}},
    )
    assert r.status_code == 400, "unset secret in non-demo must reject, not accept"


def test_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "production")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    client = TestClient(create_app(store=AuditStore()))
    r = client.post(
        "/billing/webhook",
        headers={"stripe-signature": "t=1,v1=deadbeef"},
        content=b"{}",
    )
    assert r.status_code == 400


def test_webhook_demo_accepts_and_sets_plan(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    client = TestClient(create_app(store=AuditStore()))
    r = client.post(
        "/billing/webhook",
        json={"type": "checkout.session.completed",
              "data": {"object": {"metadata": {"tenant_id": "demo-facility", "plan": "facility_starter"}}}},
    )
    assert r.status_code == 200
    ctx = client.get("/billing/tenant/demo-facility").json()
    assert ctx["plan"] == "facility_starter"
