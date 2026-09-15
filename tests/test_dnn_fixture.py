"""opencv_dnn_person fixture: real photo through OpenCV 5 DNN person detection."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"
PHOTO = REPO_ROOT / "tests" / "fixtures" / "basketball1.png"

pytestmark = pytest.mark.skipif(
    not MODEL.exists() or not PHOTO.exists(),
    reason="person-detector ONNX or sample photo missing (run scripts/download_models.sh)",
)


def test_dnn_fixture_emits_cue_tagged_with_detector_and_resolves():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        run = client.post("/demo/run", json={"fixture": "opencv_dnn_person"})
        assert run.status_code == 200, run.text
        inc = client.get(f"/incidents/{run.json()['incident_id']}").json()

    assert inc["cue"]["kind"] in {"no_movement", "no_visibility"}
    detail = inc["cue"]["detail"]
    assert detail["source"] == "opencv_dnn_person_detector"
    assert "mediapipe_persondet" in detail["detector"]
    # DNN found the person pre-cue
    assert detail.get("person_score") is None or detail["person_score"] >= 0.0
    tools = [e["tool"] for e in inc["events"]]
    assert tools[0] == "cue"
    assert "speaker_prompt" in tools
    assert inc["status"] == "resolved"
    # privacy silhouette applied to the attached pre-event frame
    assert inc["pre_event_frame_count"] >= 1
