"""Plan ids + feature gates for SaaS billing."""
from __future__ import annotations

from typing import Any, Literal

PlanId = Literal["home", "demo", "facility_starter", "facility_growth"]

PRICE_ENV = {
    "home": "STRIPE_PRICE_HOME",
    "facility_starter": "STRIPE_PRICE_FACILITY",
}


def tenant_can_use_notify(tenant: dict[str, Any]) -> bool:
    """Facility notify tools require a facility plan with active/demo status.

    Deliberate OR shape per plan review M3: home plans never notify; facility
    plans must be active (or demo status on the free judge tenant).
    """
    if tenant.get("mode") == "home":
        return tenant.get("plan") in ("demo",) and tenant.get("status") in ("demo", "active")
    if tenant.get("mode") == "facility":
        return (
            tenant.get("plan") in ("facility_starter", "facility_growth", "demo")
            and tenant.get("status") in ("active", "trialing", "demo")
        )
    return False
