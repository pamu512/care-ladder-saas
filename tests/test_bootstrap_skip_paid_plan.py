"""ROI #4: bootstrap must not reset plan when subscription_status != demo."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_bootstrap_skips_plan_realign_for_active_subscription(tmp_path):
    from care_ladder.db.base import create_engine_from_url, make_session_factory
    from care_ladder.db.models import Tenant
    import scripts.bootstrap_saas_demo as boot

    db = tmp_path / "paid.db"
    url = f"sqlite:///{db}"
    boot.bootstrap(url)

    engine = create_engine_from_url(url)
    factory = make_session_factory(engine)
    with factory() as s:
        row = s.get(Tenant, "demo-facility")
        assert row is not None
        row.plan = "facility_starter"
        row.subscription_status = "active"
        s.commit()

    boot.bootstrap(url)
    boot.bootstrap(url)  # second pass still preserves

    with factory() as s:
        row = s.get(Tenant, "demo-facility")
        assert row.plan == "facility_starter"
        assert row.subscription_status == "active"


def test_bootstrap_still_realigns_demo_status_rows(tmp_path):
    from care_ladder.db.base import create_engine_from_url, make_session_factory
    from care_ladder.db.models import Tenant
    import scripts.bootstrap_saas_demo as boot

    db = tmp_path / "demo.db"
    url = f"sqlite:///{db}"
    boot.bootstrap(url)

    engine = create_engine_from_url(url)
    factory = make_session_factory(engine)
    with factory() as s:
        row = s.get(Tenant, "demo-facility")
        row.plan = "facility_growth"  # drifted demo row
        row.subscription_status = "demo"
        s.commit()

    boot.bootstrap(url)

    with factory() as s:
        row = s.get(Tenant, "demo-facility")
        assert row.plan == "demo"  # realigned to seed
        assert row.subscription_status == "demo"
