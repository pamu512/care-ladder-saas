"""I1: demo fixture that runs OpenCV CueDetector then run_incident."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_opencv_stillness_fixture_cue_comes_from_detector():
    app = create_app(store=AuditStore())
    client = TestClient(app)

    run = client.post("/demo/run", json={"fixture": "opencv_stillness"})
    assert run.status_code == 200
    incident_id = run.json()["incident_id"]

    detail = client.get(f"/incidents/{incident_id}")
    assert detail.status_code == 200
    incident = detail.json()

    assert incident["cue"]["kind"] == "no_movement"
    # Provenance: cue must be marked as coming from OpenCV detector path
    cue_ev = incident["events"][0]
    assert cue_ev["tool"] == "cue"
    assert cue_ev["cue_kind"] == "no_movement"
    src = cue_ev["detail"].get("source") or incident["cue"]["detail"].get("source")
    assert src == "opencv_cue_detector"
    assert len(incident["events"]) >= 3
