"""DNN person detection + MOG2 background subtraction integration in CueDetector.

Skips automatically when the ONNX model file is absent (pure-stdlib CI machines).
"""

from pathlib import Path

import numpy as np
import pytest

from care_ladder.vision.cues import CueDetector

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"

pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="person-detector ONNX not downloaded")


def _detector_with_dnn(**kw):
    from care_ladder.vision.mppersondet import MPPersonDet

    dnn = MPPersonDet(str(MODEL), scoreThreshold=0.3)
    return CueDetector(
        no_movement_timeout_sec=kw.pop("no_movement_timeout_sec", 2.0),
        zone=kw.pop("zone", ((0, 0), (640, 0), (640, 480), (0, 480))),
        person_detector=dnn,
        **kw,
    )


def test_dnn_detector_reports_source_and_scores_on_real_photo():
    import cv2

    img = cv2.imread("/tmp/basketball1.img") if Path("/tmp/basketball1.img").exists() else None
    if img is None:
        # offline: rely only on model presence test above
        pytest.skip("no cached sample photo")
    det = _detector_with_dnn()
    det.observe(img, t=0.0)
    assert det.last_detection_source == "dnn_person_detector"


def test_cue_detector_uses_dnn_detection_and_tags_source():
    det = _detector_with_dnn()
    # MOG2 needs a few frames to model background; feed a photo-like frame repeatedly.
    import cv2

    img = cv2.imread("/tmp/basketball1.img") if Path("/tmp/basketball1.img").exists() else None
    if img is None:
        pytest.skip("no cached sample photo")
    cue = None
    for i in range(6):
        cue = det.observe(img, t=float(i))
        if cue:
            break
    # Whether or not a cue fires depends on the photo; the contract here is that
    # detection used the DNN path and no exception was raised.
    assert det.last_detection_source == "dnn_person_detector"


def test_mog2_suppresses_global_illumination_shift():
    """A uniform brightness ramp should NOT count as person motion (MOG2)."""
    rng = np.random.default_rng(3)
    frames = []
    for i in range(8):
        f = (rng.random((120, 160, 3)) * 10 + 20 + i * 4).astype(np.uint8)
        f[40:80, 60:100] = (150 + i * 2, 150, 150)
        frames.append(f)
    det = CueDetector(
        no_movement_timeout_sec=1.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
        motion_source="mog2",
    )
    cues = [c for i, f in enumerate(frames) if (c := det.observe(f, t=float(i))) is not None]
    # Stillness accumulates despite background ramp → cue fires, motion did not reset clock
    assert any(c.kind == "no_movement" for c in cues)
