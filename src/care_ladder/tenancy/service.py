"""In-memory demo tenant registry for AUTH=on memory mode.

Production (Postgres) seeds the same rows via scripts/bootstrap_saas_demo.py;
this keeps the AUTH surface testable without a database.
"""
from dataclasses import dataclass


@dataclass
class DemoUser:
    email: str
    password: str
    tenant_id: str
    tenant_mode: str
    tenant_plan: str


DEMO_USERS: dict[str, DemoUser] = {
    "demo@careladder.local": DemoUser(
        email="demo@careladder.local",
        password="demo-pass-home",
        tenant_id="demo-home",
        tenant_mode="home",
        tenant_plan="home",
    ),
    "facility@careladder.local": DemoUser(
        email="facility@careladder.local",
        password="demo-pass-facility",
        tenant_id="demo-facility",
        tenant_mode="facility",
        tenant_plan="facility_starter",
    ),
}


def find_demo_user(email: str) -> DemoUser | None:
    return DEMO_USERS.get(email.lower())
