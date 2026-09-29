"""Stripe Checkout session creation + webhook signature verification.

Fail-closed rules (plan Global Constraints):
- non-demo env without STRIPE_SECRET_KEY: checkout raises 503 (never a fake URL)
- non-demo env without STRIPE_WEBHOOK_SECRET: webhook POSTs are rejected
- bad/missing signature on a configured secret: rejected
- demo env: honest stub checkout URL (documented in UI copy)
"""
from __future__ import annotations

import html
import os
from typing import Any

from care_ladder.billing.plans import PRICE_ENV


class BillingError(Exception):
    status = 400


def _env() -> str:
    return os.environ.get("CARE_LADDER_ENV", "demo").lower()


def _https_origin(raw: str) -> str:
    origin = (raw or "").strip().rstrip("/")
    if not origin:
        return ""
    if origin.startswith("http://"):
        origin = "https://" + origin[len("http://") :]
    elif not origin.startswith("https://"):
        origin = "https://" + origin
    return origin


def resolve_checkout_base_url(request: Any | None = None, base_url: str = "") -> str:
    """Absolute https origin for Stripe success/cancel URLs.

    Prefer the incoming request (X-Forwarded-Proto/Host, then request.base_url).
    Fall back to PUBLIC_BASE_URL or Render's RENDER_EXTERNAL_URL.
    """
    if base_url:
        origin = _https_origin(base_url)
        if origin:
            return origin
    if request is not None:
        headers = request.headers
        proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        host = (headers.get("x-forwarded-host") or headers.get("host") or "").split(",")[0].strip()
        if host:
            scheme = proto or getattr(getattr(request, "url", None), "scheme", "") or "https"
            return _https_origin(f"{scheme}://{host}")
        req_base = str(getattr(request, "base_url", "") or "").rstrip("/")
        if req_base:
            return _https_origin(req_base)
    env = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or ""
    origin = _https_origin(env)
    if origin:
        return origin
    raise BillingError("public base URL not configured")


def create_checkout_url(plan: str, tenant_id: str, base_url: str = "") -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        if _env() == "demo":
            return f"{base_url}/billing/stub-success?plan={plan}&tenant={tenant_id}"
        raise BillingError("billing not configured")  # caller maps to 503
    import stripe

    stripe.api_key = key
    origin = resolve_checkout_base_url(base_url=base_url)
    price_env = PRICE_ENV.get(plan)
    price_id = os.environ.get(price_env, "") if price_env else ""
    if not price_id:
        raise BillingError(f"no price configured for plan {plan}")
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=(
                f"{origin}/billing/return?from=checkout"
                "&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{origin}/billing/return?from=cancel",
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
    except stripe.StripeError as exc:
        raise BillingError("checkout unavailable") from exc
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


_RETURN_COPY = {
    "portal": (
        "Billing portal closed",
        "You left the Stripe customer portal. Closing the portal does not create a new charge.",
    ),
    "checkout": (
        "Checkout completed",
        "Checkout finished. Plan activation is awaiting webhook verification. "
        "This page does not confirm a live subscription by itself.",
    ),
    "cancel": (
        "Checkout canceled",
        "Checkout was canceled. No charge was made.",
    ),
}


def render_billing_return_html(from_kind: str) -> str:
    """Human landing page after Stripe Portal or Checkout.

    JSON /billing/success and /billing/cancel stay for API clients; humans
    need HTML with a way back to the consoles.
    """
    kind = (from_kind or "").strip().lower()
    title, body = _RETURN_COPY.get(
        kind,
        (
            "Back from Stripe",
            "You returned from Stripe billing. Use a console link below to continue.",
        ),
    )
    title_esc = html.escape(title)
    body_esc = html.escape(body)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Care Ladder · {title_esc}</title>
<style>
  :root {{ --fg:#0f172a; --muted:#64748b; --accent:#0e7490; --border:#e2e8f0; }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px;
         background:#f8fafc; color:var(--fg); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .card {{ background:#fff; border:1px solid var(--border); border-radius:16px; padding:28px 24px; max-width:460px; width:100%;
          box-shadow:0 1px 3px rgba(15,23,42,.06); }}
  .brand {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); font-weight:700; margin-bottom:14px; }}
  h1 {{ font-size:20px; margin-bottom:10px; }}
  p {{ font-size:15px; color:var(--muted); margin-bottom:18px; }}
  .links {{ display:flex; flex-direction:column; gap:8px; }}
  a {{ display:block; text-align:center; text-decoration:none; border-radius:10px; padding:10px 14px; font-size:14px; font-weight:600; }}
  a.primary {{ background:var(--accent); color:#fff; }}
  a.secondary {{ border:1px solid var(--border); color:var(--fg); }}
  .note {{ font-size:12px; color:var(--muted); margin-top:16px; margin-bottom:0; }}
</style>
</head>
<body>
  <div class="card">
    <div class="brand">Care Ladder</div>
    <h1>{title_esc}</h1>
    <p>{body_esc}</p>
    <div class="links">
      <a class="primary" href="/ui/">Caregiver console</a>
      <a class="secondary" href="/ui/facility/">Facility floor console</a>
    </div>
    <p class="note">Not a medical device. Billing changes apply only after Stripe confirms them.</p>
  </div>
</body>
</html>
"""
