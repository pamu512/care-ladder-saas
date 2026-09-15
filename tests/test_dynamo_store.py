"""DynamoAuditStore with a scripted low-level client (no AWS in CI)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from care_ladder.audit.dynamo_store import DynamoAuditStore, _from_ddb, _to_ddb
from care_ladder.models import AuditEvent, CueEvent, Incident


class FakeDDB:
    """Minimal DynamoDB low-level client: enough for the store's calls."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.tables: list[str] = []

    def list_tables(self):
        return {"TableNames": self.tables}

    def create_table(self, TableName, **kw):
        self.tables.append(TableName)
        return {"TableDescription": {"TableStatus": "CREATING"}}

    def get_waiter(self, name):
        class W:
            def wait(inner, **kw):
                assert name == "table_exists"

        return W()

    def put_item(self, TableName, Item):
        key = Item["incident_id"]["S"]
        self.items[key] = Item
        return {}

    def get_item(self, TableName, Key):
        item = self.items.get(Key["incident_id"]["S"])
        return {"Item": item} if item else {}

    def scan(self, TableName, Limit=None):
        return {"Items": list(self.items.values())[: (Limit or 100)]}


def _incident(frame_shape=(24, 32, 3)):
    frames = [np.full(frame_shape, 128, dtype=np.uint8)]
    inc = Incident(
        id="abc123",
        household_id="demo-home-1",
        cue=CueEvent(kind="no_movement", confidence=0.9, detail={"x": 1}),
        events=[AuditEvent(tool="cue", detail={"a": True, "b": [1, 2], "c": "s"})],
        status="resolved",
        pre_event_frame_count=1,
        privacy="blur",
    )
    inc.__dict__["_private_pre_event_frames"] = frames
    return inc


def test_roundtrip_including_frames():
    ddb = FakeDDB()
    store = DynamoAuditStore(table_name="t1", client=ddb)
    inc = _incident()
    store.save(inc)

    # fresh store, same backing table (simulates restart / new task)
    store2 = DynamoAuditStore(table_name="t1", client=ddb)
    loaded = store2.get("abc123")
    assert loaded is not None
    assert loaded.id == "abc123"
    assert loaded.cue.kind == "no_movement"
    assert loaded.status == "resolved"
    assert loaded.events[0].detail["a"] is True
    frames = loaded.__dict__.get("_private_pre_event_frames") or []
    assert len(frames) == 1
    assert frames[0].shape == (24, 32, 3)


def test_list_after_restart():
    ddb = FakeDDB()
    s1 = DynamoAuditStore(table_name="t2", client=ddb)
    s1.save(_incident())
    s2 = DynamoAuditStore(table_name="t2", client=ddb)
    listing = s2.list_incidents()
    assert [i.id for i in listing] == ["abc123"]


def test_missing_returns_none():
    ddb = FakeDDB()
    store = DynamoAuditStore(table_name="t3", client=ddb)
    assert store.get("nope") is None


def test_ddb_marshalling_types():
    val = {"a": 1, "b": 1.5, "c": True, "d": None, "e": [1, "x"], "f": {"g": "h"}}
    assert _from_ddb(_to_ddb(val)) == val
