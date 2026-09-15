"""CueDetector ↔ PersonTracker integration: person_count/track info in cue details."""

import numpy as np

from care_ladder.vision.cues import CueDetector


def _blank(w=160, h=120):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _still_person_frame(w=160, h=120):
    f = _blank(w, h)
    f[40:80, 60:100] = 200
    return f


def test_no_movement_cue_includes_person_count_and_tracks():
    det = CueDetector(
        no_movement_timeout_sec=2.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
    )
    f = _still_person_frame()
    det.observe(f, t=0.0)
    det.observe(f, t=0.5)
    cue = det.observe(f, t=2.5)
    assert cue is not None and cue.kind == "no_movement"
    assert cue.detail["person_count"] == 1
    assert cue.detail["tracks"][0]["height_ratio"] > 0
    assert cue.detail["track_events"][0]["type"] == "enter"


def test_tracking_can_be_disabled():
    det = CueDetector(
        no_movement_timeout_sec=2.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
        tracking_enabled=False,
    )
    f = _still_person_frame()
    det.observe(f, t=0.0)
    det.observe(f, t=0.5)
    cue = det.observe(f, t=2.5)
    assert cue is not None
    assert "person_count" not in cue.detail
