"""End-to-end pose path: person ONNX → pose ONNX → fall-signature cue.

Skips when either model file is absent.
"""

from pathlib import Path

import numpy as np
import pytest

from care_ladder.vision.cues import CueDetector

REPO = Path(__file__).resolve().parents[1]
PERSON = REPO / "models" / "person_detection_mediapipe_2023mar.onnx"
POSE = REPO / "models" / "pose_estimation_mediapipe_2023mar.onnx"

pytestmark = pytest.mark.skipif(
    not PERSON.exists() or not POSE.exists(), reason="ONNX models not downloaded"
)


def test_pose_path_tagged_source_on_real_photo():
    import cv2

    from care_ladder.vision.mppersondet import MPPersonDet
    from care_ladder.vision.mppose import MPPose

    det = CueDetector(
        no_movement_timeout_sec=99.0,
        zone=((0, 0), (640, 0), (640, 480), (0, 480)),
        person_detector=MPPersonDet(str(PERSON), scoreThreshold=0.3),
        pose_model=MPPose(str(POSE), confThreshold=0.5),
    )
    img = cv2.imread(str(REPO / "tests" / "fixtures" / "basketball1.png"))
    # standing person — pose must NOT fire distress; detector must not crash
    for t in [0.0, 0.5, 1.0, 2.0, 3.0, 4.0]:
        cue = det.observe(img, t=t)
        if cue is not None:
            assert cue.kind != "distress_heuristic" or cue.detail.get("source") != "pose_heuristics"
    assert det.last_detection_source == "dnn_person_detector"
    metrics = getattr(det, "last_pose_metrics", None)
    if metrics is not None:  # pose ran
        assert metrics["torso_angle_deg"] < 55  # person is standing
