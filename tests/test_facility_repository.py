"""Slice 2: Postgres-backed facility repository (sqlite in tests, same as tenancy suite)."""
from care_ladder.db.models import Base
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import StaffRow, CaseRow
from care_ladder.facility.models import Case, StaffMember
from care_ladder.facility.repository import FacilityRepository


def _repo(tenant="demo-facility", seed=True):
    engine = create_engine_from_url("sqlite://")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    s = Session()
    if seed:
        s.add(StaffRow(id="st-1", tenant_id=tenant, display_name="Maria G.", role="RN", initials="MG", status="available"))
        s.add(StaffRow(id="st-2", tenant_id=tenant, display_name="Alex R.", role="CNA", initials="AR", status="on_break",
                       break_until=None))
        s.commit()
    return FacilityRepository(s, tenant), s


def test_break_blocks_and_override_path():
    repo, _ = _repo()
    alex = repo.get_staff("st-2")
    assert alex.assignable() is False
    repo.set_break("st-2", False)
    assert repo.get_staff("st-2").assignable() is True


def test_tenant_isolation():
    repo_a, _ = _repo("tenant-a")
    repo_b, _ = _repo("tenant-b", seed=False)
    c = Case.open_from_incident(incident_id="i1", tenant_id="tenant-a", room_label="101",
                                origin="from_silence", priority="P2")
    repo_a.open_case(c)
    assert repo_b.get_case(c.id) is None
    assert repo_b.list_staff() == []
    assert repo_a.list_cases() and repo_a.list_cases()[0].id == c.id


def test_case_lifecycle_persisted():
    repo, _ = _repo()
    c = Case.open_from_incident(incident_id="i2", tenant_id="demo-facility", room_label="204",
                                origin="from_negative_reply", priority="P1")
    repo.open_case(c)
    c.state = "handling"
    c.priority = "P2"
    repo.save(c)
    got = repo.get_case(c.id)
    assert got.state == "handling" and got.priority == "P2"
    assert got.close(documentation="Resident dizzy after standing; vitals stable; MD notified same shift.") is True
    repo.save(got)
    assert repo.get_case(c.id).state == "closed"
    assert [x for x in repo.list_cases(include_closed=False)] == []
