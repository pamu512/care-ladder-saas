"""CloudSinks: privacy-gated S3 upload + EventBridge emission (fakes, no AWS)."""

from __future__ import annotations

import numpy as np

from care_ladder.cloud.sinks import CloudSinks
from care_ladder.models import CueEvent, Incident


class FakeS3:
    def __init__(self):
        self.objects = []

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        assert Body[:8] == b"\x89PNG\r\n\x1a\n"
        self.objects.append((Bucket, Key, Metadata))


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)


def _sinks(monkeypatch, bucket="b", bus="e"):
    sinks = CloudSinks(bucket=bucket, bus=bus)
    sinks._s3 = FakeS3()
    sinks._events = FakeEvents()
    return sinks


def _incident(frames=True):
    inc = Incident(
        id="i1",
        household_id="h",
        cue=CueEvent(kind="no_movement", confidence=0.9, detail={}),
        events=[],
        status="resolved",
        pre_event_frame_count=1,
        privacy="blur",
    )
    if frames:
        inc.__dict__["_private_pre_event_frames"] = [
            np.full((16, 16, 3), 90, dtype=np.uint8)
        ]
    return inc


def test_upload_and_emit_roundtrip(monkeypatch):
    sinks = _sinks(monkeypatch)
    uris = sinks.upload_clip_frames("i1", _incident().__dict__["_private_pre_event_frames"], "blur")
    assert uris == ["s3://b/incidents/i1/pre_event_000.png"]
    bucket, key, meta = sinks._s3.objects[0]
    assert (bucket, key) == ("b", "incidents/i1/pre_event_000.png")
    assert meta["privacy"] == "blur"

    inc = _incident()
    assert sinks.emit_cue(inc, uris) is True
    entry = sinks._events.entries[0]
    assert entry["Source"] == "care.ladder"
    assert entry["DetailType"] == "CareLadderCue"
    import json

    detail = json.loads(entry["Detail"])
    assert detail["incident_id"] == "i1"
    assert detail["kind"] == "no_movement"
    assert detail["clip_s3_uris"] == uris


def test_upload_refuses_without_privacy_tag(monkeypatch):
    sinks = _sinks(monkeypatch)
    frames = [np.zeros((8, 8, 3), np.uint8)]
    assert sinks.upload_clip_frames("i1", frames, None) == []
    assert sinks.upload_clip_frames("i1", frames, "raw") == []
    assert sinks._s3.objects == []


def test_disabled_when_unconfigured(monkeypatch):
    sinks = CloudSinks(bucket="", bus="")
    assert sinks.enabled is False
    assert sinks.emit_cue(_incident()) is False
    assert sinks.upload_clip_frames("i1", [], "blur") == []
