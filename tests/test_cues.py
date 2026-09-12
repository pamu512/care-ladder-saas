import numpy as np

from care_ladder.vision.cues import CueDetector


def _blank(w=160, h=120):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_no_movement_after_timeout_with_static_person_blob():
    det = CueDetector(no_movement_timeout_sec=3.0, zone=((0, 0), (160, 0), (160, 120), (0, 120)))
    frame = _blank()
    frame[40:80, 60:100] = 200
    assert det.observe(frame, t=0.0) is None
    assert det.observe(frame, t=1.0) is None
    cue = det.observe(frame, t=3.5)
    assert cue is not None
    assert cue.kind == "no_movement"


def test_no_visibility_when_blob_leaves_zone():
    det = CueDetector(no_movement_timeout_sec=99.0, zone=((0, 0), (80, 0), (80, 120), (0, 120)))
    left = _blank()
    left[40:80, 20:60] = 200
    right = _blank()
    right[40:80, 100:140] = 200
    det.observe(left, t=0.0)
    cue = det.observe(right, t=1.0)
    assert cue is not None
    assert cue.kind == "no_visibility"


def test_distress_heuristic_wide_low_blob():
    """Non-clinical: wide, low blob sustained across frames → distress_heuristic."""
    det = CueDetector(
        no_movement_timeout_sec=99.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
        distress_sustain_sec=1.0,
    )
    frame = _blank()
    # Wide (80px) and short (20px), near bottom of frame (y=90:110)
    frame[90:110, 40:120] = 200
    assert det.observe(frame, t=0.0) is None
    cue = det.observe(frame, t=1.5)
    assert cue is not None
    assert cue.kind == "distress_heuristic"
    assert cue.detail.get("non_clinical") is True
