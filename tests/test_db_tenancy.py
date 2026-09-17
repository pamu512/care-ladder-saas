"""Task 1: Postgres tenancy models + tenant-scoped PostgresAuditStore.

Uses SQLite in-memory for hermetic tests (same SQLAlchemy 2.x ORM surface the
Postgres deployment uses). If a real DATABASE_URL is set, the same models run
against Postgres unchanged.
"""

from care_ladder.audit.store import AuditStore  # in-memory reference
from care_ladder.audit.postgres_store import PostgresAuditStore
from care_ladder.db.base import create_engine_from_url, make_session_factory
from care_ladder.db.models import Tenant, User, IncidentRow, AuditEventRow, TenantMode


def make_db():
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    Tenant.metadata.create_all(engine)
    return make_session_factory(engine)


def seed_tenants(SessionLocal):
    with SessionLocal() as s:
        home = Tenant(id="ten-home", name="Demo Home", mode="home", plan="home",
                      subscription_status="active")
        fac = Tenant(id="ten-fac", name="Demo Facility", mode="facility",
                     plan="facility_starter", subscription_status="active")
        s.add_all([home, fac,
                   User(id="u1", tenant_id="ten-home", email="demo@careladder.local",
                        password_hash="x", role="owner"),
                   User(id="u2", tenant_id="ten-fac", email="facility@careladder.local",
                        password_hash="x", role="owner")])
        s.commit()


def test_tenant_modes_and_seed_shape():
    SessionLocal = make_db()
    seed_tenants(SessionLocal)
    with SessionLocal() as s:
        assert s.get(Tenant, "ten-home").mode == "home"
        assert s.get(Tenant, "ten-fac").mode == "facility"
        assert s.get(Tenant, "ten-fac").plan == "facility_starter"
        users = s.query(User).filter_by(tenant_id="ten-fac").all()
        assert len(users) == 1


def test_incident_rows_are_tenant_scoped():
    SessionLocal = make_db()
    seed_tenants(SessionLocal)
    store_a = PostgresAuditStore(SessionLocal, tenant_id="ten-home")
    store_b = PostgresAuditStore(SessionLocal, tenant_id="ten-fac")

    # run Path A through the app with store_a, like the API does
    from fastapi.testclient import TestClient
    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore as MemoryStore

    app = create_app(store=store_a)
    client = TestClient(app)
    r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert r.status_code == 200
    inc_id = r.json()["incident_id"]

    # tenant B cannot see tenant A's incident
    assert store_b.get(inc_id) is None
    assert all(i.id != inc_id for i in store_b.list_incidents())
    # tenant A can
    got = store_a.get(inc_id)
    assert got is not None
    assert got.id == inc_id
    assert [i.id for i in store_a.list_incidents()] == [inc_id]

    # rows carry tenant_id
    with SessionLocal() as s:
        row = s.query(IncidentRow).one()
        assert row.tenant_id == "ten-home"
        assert row.incident_id == inc_id
        evs = s.query(AuditEventRow).all()
        assert evs, "audit events persisted"
        assert all(e.tenant_id == "ten-home" for e in evs)
