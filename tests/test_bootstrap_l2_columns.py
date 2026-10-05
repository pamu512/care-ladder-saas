"""Layer 2 schema evolution: cover + handoffs columns must be ALTERed on an
existing database (create_all never ALTERs; Render keeps its schema)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_bootstrap_adds_cover_and_handoffs_to_existing_db(tmp_path):
    from sqlalchemy import create_engine, inspect

    from care_ladder.db.models import Base
    import scripts.bootstrap_saas_demo as boot

    db = tmp_path / "l2-evolved.db"

    # simulate the PRE-layer-2 schema: staff/cases tables without cover/handoffs
    old_engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(old_engine)
    with old_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE facility_staff_old AS SELECT id, tenant_id, display_name, "
            "role, initials, status, break_until, active_case_id, parked_case_ids "
            "FROM facility_staff"
        )
        conn.exec_driver_sql("DROP TABLE facility_staff")
        conn.exec_driver_sql("ALTER TABLE facility_staff_old RENAME TO facility_staff")
        conn.exec_driver_sql(
            "CREATE TABLE facility_cases_old AS SELECT id, human_id, tenant_id, "
            "incident_id, room_label, place_label, subject_display_name, subject_kind, "
            "subject_id, title, origin, priority, state, owner_staff_id, "
            "slack_thread_url, ack_at, closed_at, documentation, created_at "
            "FROM facility_cases"
        )
        conn.exec_driver_sql("DROP TABLE facility_cases")
        conn.exec_driver_sql("ALTER TABLE facility_cases_old RENAME TO facility_cases")
    old_engine.dispose()

    staff_cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("facility_staff")}
    assert "cover" not in staff_cols
    case_cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("facility_cases")}
    assert "handoffs" not in case_cols

    boot.bootstrap(f"sqlite:///{db}")

    staff_cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("facility_staff")}
    assert "cover" in staff_cols
    case_cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("facility_cases")}
    assert "handoffs" in case_cols

    # second run is a no-op (idempotent)
    boot.bootstrap(f"sqlite:///{db}")
    staff_cols2 = {c["name"] for c in inspect(create_engine(f"sqlite:///{db}")).get_columns("facility_staff")}
    assert staff_cols2 == staff_cols


def test_cover_column_backfills_on_duty(tmp_path):
    """Rows that existed before the ALTER must read cover=on_duty."""
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from care_ladder.db.models import Base
    import scripts.bootstrap_saas_demo as boot

    db = tmp_path / "l2-backfill.db"
    eng = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO facility_staff (id, tenant_id, display_name, role, initials, status, parked_case_ids) "
                "VALUES ('legacy-1', 'demo-facility', 'Legacy L.', 'CNA', 'LL', 'available', '[]')"
            )
        )
    eng.dispose()

    boot.bootstrap(f"sqlite:///{db}")

    eng2 = create_engine(f"sqlite:///{db}")
    with sessionmaker(bind=eng2)() as s:
        row = s.execute(sa.text("SELECT cover FROM facility_staff WHERE id = 'legacy-1'")).one()
        assert row[0] == "on_duty"
