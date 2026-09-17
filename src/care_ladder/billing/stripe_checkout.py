"""Stripe Checkout session creation + webhook signature verification.

Fail-closed rules (plan Global Constraints):
- non-demo env without STRIPE_SECRET_KEY: checkout raises 503 (never a fake URL)
- non-demo env without STRIPE_WEBHOOK_SECRET: webhook POSTs are rejected
- bad/missing signature on a configured secret: rejected
- demo env: honest stub checkout URL (documented in UI copy)
"""
from __future__ import annotations

import os
from typing import Any


class BillingError(Exception):
    status = 400


def _env() -> str:
    return os.environ.get("CARE_LADDER_ENV", "demo").lower()


def create_checkout_url(plan: str, tenant_id: str, base_url: str = "") -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        if _env() == "demo":
            return f"{base_url}/billing/stub-success?plan={plan}&tenant={tenant_id}"
        raise BillingError("billing not configured")  # caller maps to 503
    import stripe

    price_env = {"home": "STRIPE_PRICE_HOME", "facility_starter": "STRIPE_PRICE_FACILITY"}.get(plan)
    price_id = os.environ.get(price_env, "") if price_env else ""
    if not price_id:
        raise BillingError(f"no price configured for plan {plan}")
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/billing/cancel",
        metadata={"tenant_id": tenant_id, "plan": plan},
    )
    return session.url


def verify_webhook(payload: bytes, signature: str) -> bool:
    """True iff the event is authentic. Fail-closed in non-demo envs."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        return _env() == "demo"  # demo accepts unsigned (documented); prod rejects
    if not signature:
        return False
    try:
        import stripe

        stripe.Webhook.construct_event(payload, signature, secret)
        return True
    except Exception:
        return False


def apply_subscription_event(event: dict[str, Any], tenants: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Update tenant plan/status from a verified checkout/subscription event."""
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    meta = obj.get("metadata") or {}
    tenant_id = meta.get("tenant_id") or obj.get("client_reference_id") or ""
    if not tenant_id or tenant_id not in tenants:
        return {"applied": False, "reason": "unknown tenant"}
    t = tenants[tenant_id]
    if etype == "checkout.session.completed":
        t["plan"] = meta.get("plan", t.get("plan"))
        t["status"] = "active"
    elif etype == "customer.subscription.updated":
        t["status"] = obj.get("status", t.get("status"))
    elif etype == "customer.subscription.deleted":
        t["status"] = "canceled"
    return {"applied": True, "tenant_id": tenant_id, "plan": t["plan"], "status": t["status"]}
