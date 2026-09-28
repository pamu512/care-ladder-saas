"""Schema evolution: bootstrap must add missing columns to an existing DB.

Regression test for the Render deploy failure: create_all does not ALTER
existing tables, so Tenant.stripe_customer_id was missing on the live
Postgres and every SELECT on tenants crashed the container start.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_bootstrap_adds_missing_column_to_existing_db(tmp_path):
    from sqlalchemy import create_engine, inspect

    from care_ladder.db.models import Base
    import scripts.bootstrap_saas_demo as boot

    db = tmp_path / "evolved.db"

    # simulate the OLD schema (pre-stripe_customer_id) as Render had it
    old_engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(old_engine)
    with old_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE tenants_old AS SELECT id, name, mode, plan, "
            "subscription_status, created_at FROM tenants"
        )
        conn.exec_driver_sql("DROP TABLE tenants")
        conn.exec_driver_sql("ALTER TABLE tenants_old RENAME TO tenants")
    old_engine.dispose()

    assert "stripe_customer_id" not in {
        c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("tenants")
    }

    # bootstrap on the evolved DB must add the column and still seed
    boot.bootstrap(f"sqlite:///{db}")

    cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("tenants")}
    assert "stripe_customer_id" in cols

    # idempotent on a second run
    boot.bootstrap(f"sqlite:///{db}")
    cols2 = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("tenants")}
    assert "stripe_customer_id" in cols2
