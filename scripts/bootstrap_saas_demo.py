#!/usr/bin/env python
"""Idempotent demo bootstrap for the SaaS deploy (Task 10).

Creates the schema (create_all - this fork ships no alembic migrations) and
the two demo tenants + users the landing page logs in, if missing. Safe to
run on every container start (Render restarts re-run it).

Env: DATABASE_URL (postgres in prod, sqlite fallback for local smoke),
SESSION_SECRET is read by the app, not here.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from care_ladder.auth.passwords import hash_password  # noqa: E402
from care_ladder.db.base import create_engine_from_url, make_session_factory  # noqa: E402
from care_ladder.db.models import Base, Tenant, User  # noqa: E402

DEMO_TENANTS = [
    {
        "id": "demo-home",
        "name": "Demo Home",
        "mode": "home",
        "plan": "home",
        "email": "demo@careladder.local",
        "password": "demo-pass-home",
    },
    {
        "id": "demo-facility",
        "name": "Demo Facility",
        "mode": "facility",
        "plan": "demo",
        "email": "facility@careladder.local",
        "password": "demo-pass-facility",
    },
]


def _ensure_schema_columns(engine) -> None:
    """create_all never ALTERs existing tables; add missing columns idempotently.

    Render Postgres keeps its schema across deploys, so model changes need
    additive ALTERs here (this fork deliberately ships no Alembic).
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("tenants"):
        return  # fresh database; create_all below handles everything
    existing = {c["name"] for c in inspector.get_columns("tenants")}
    with engine.begin() as conn:
        if "stripe_customer_id" not in existing:
            conn.execute(
                text("ALTER TABLE tenants ADD COLUMN stripe_customer_id VARCHAR(64)")
            )
            print("bootstrap: added tenants.stripe_customer_id")


def bootstrap(database_url: str | None = None) -> None:
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///./saas-demo.db")
    engine = create_engine_from_url(url)
    _ensure_schema_columns(engine)
    Base.metadata.create_all(engine)  # idempotent
    factory = make_session_factory(engine)
    session = factory()
    try:
        for spec in DEMO_TENANTS:
            existing = session.get(Tenant, spec["id"])
            if existing is None:
                tenant = Tenant(
                    id=spec["id"], name=spec["name"],
                    mode=spec["mode"], plan=spec["plan"],
                )
                session.add(tenant)
                session.flush()
                print(f"bootstrap: created tenant {spec['id']}")
            else:
                tenant = existing
                # keep our demo rows aligned with the spec (e.g. plan renames)
                if tenant.plan != spec["plan"] or tenant.mode != spec["mode"]:
                    tenant.plan = spec["plan"]
                    tenant.mode = spec["mode"]
                    print(f"bootstrap: realigned tenant {spec['id']} -> plan={spec['plan']}")
                print(f"bootstrap: tenant {spec['id']} exists")
            user = (
                session.query(User).filter(User.email == spec["email"]).one_or_none()
            )
            if user is None:
                session.add(
                    User(
                        id=f"{spec['id']}-owner",
                        tenant_id=tenant.id,
                        email=spec["email"],
                        password_hash=hash_password(spec["password"]),
                    )
                )
                print(f"bootstrap: created user {spec['email']}")
            else:
                print(f"bootstrap: user {spec['email']} exists")
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    bootstrap()
    print("bootstrap: done")
