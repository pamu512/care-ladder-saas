"""Task 6: facility demo fixture; Path A/B must remain unchanged (home mode)."""

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_home_path_a_unchanged():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert tools[0] == "cue"
    assert "speaker_prompt" in tools
    assert "dial_contact" not in tools  # verbal OK: no dial
    assert inc["status"] == "resolved"
    assert "notify_channel" not in tools and "notify_supervisor" not in tools


def test_home_path_b_unchanged():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "dial_contact" in tools
    assert inc["status"] == "resolved"
    assert "notify_channel" not in tools and "notify_supervisor" not in tools


def test_facility_fixture_runs_notify_ladder():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_channel" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    assert inc["status"] in ("resolved", "exhausted")
    # adapter honesty: stub or slack recorded in the audit trail
    notify_ev = next(e for e in inc["events"] if e["tool"] == "notify_channel")
    assert notify_ev["detail"]["adapter"] in ("stub", "slack")
    # no emergency tool ever ran
    assert "emergency" not in tools


def test_unknown_fixture_still_400():
    client = TestClient(create_app(store=AuditStore()))
    assert client.post("/demo/run", json={"fixture": "nope"}).status_code == 400
