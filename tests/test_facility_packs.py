"""Task 2: pack loading + Zone.kind."""
from pathlib import Path

from care_ladder.facility.packs import FacilityPack, load_pack
from care_ladder.plan_loader import load_care_plan


def test_load_daycare_pack():
    p = load_pack("daycare_kids")
    assert isinstance(p, FacilityPack)
    assert p.vocabulary["subject"] == "child"
    assert p.vocabulary["place"] == "classroom"
    assert p.concurrency["pin_peek"] is True
    assert p.sla_ack_sec == 60
    assert p.roles and p.roles[0]["display_name"] == "Avery Kim"


def test_load_all_four_packs():
    for t in ("daycare_kids", "assisted_living", "rehab", "old_age_home"):
        p = load_pack(t)
        assert p.facility_type == t
        assert p.vocabulary and p.sla_ack_sec > 0 and p.roles


def test_unknown_type_falls_back_to_assisted_living():
    p = load_pack("does_not_exist")
    assert p.facility_type == "assisted_living"


def test_zone_kind_roundtrip():
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    assert all(hasattr(z, "kind") for z in plan.zones)
    common = [z for z in plan.zones if z.id == "common_room"]
    assert common and common[0].kind == "common"


def test_zone_kind_defaults_private():
    from care_ladder.models import Zone

    z = Zone(id="z1", polygon=[[0, 0], [1, 0], [1, 1], [0, 1]])
    assert z.kind == "private"  # back-compat default


def test_settings_merges_pack(monkeypatch):
    from fastapi.testclient import TestClient

    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t2")
    c = TestClient(create_app(store=AuditStore()))
    assert c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"}).status_code == 200
    body = c.get("/facility/settings").json()
    assert body["vocabulary"]["subject"] == "resident"  # assisted_living default
    assert body["sla_ack_sec"] == 120
    c.patch("/facility/settings", json={"facility_type": "daycare_kids"})
    body2 = c.get("/facility/settings").json()
    assert body2["vocabulary"]["subject"] == "child"
    assert body2["sla_ack_sec"] == 60
