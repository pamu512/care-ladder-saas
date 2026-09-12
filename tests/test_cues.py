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


def test_no_visibility_latches_does_not_refire_every_frame():
    det = CueDetector(no_movement_timeout_sec=99.0, zone=((0, 0), (80, 0), (80, 120), (0, 120)))
    left = _blank()
    left[40:80, 20:60] = 200
    right = _blank()
    right[40:80, 100:140] = 200
    det.observe(left, t=0.0)
    cue1 = det.observe(right, t=1.0)
    assert cue1 is not None and cue1.kind == "no_visibility"
    cue2 = det.observe(right, t=2.0)
    assert cue2 is None  # latched / cleared — no spam


def test_no_movement_latches_until_motion_resets():
    det = CueDetector(no_movement_timeout_sec=3.0, zone=((0, 0), (160, 0), (160, 120), (0, 120)))
    frame = _blank()
    frame[40:80, 60:100] = 200
    assert det.observe(frame, t=0.0) is None
    cue1 = det.observe(frame, t=3.5)
    assert cue1 is not None and cue1.kind == "no_movement"
    # Immediately after latch, same still frame must not re-fire
    cue2 = det.observe(frame, t=3.6)
    assert cue2 is None


def test_from_plan_respects_disabled_trigger():
    from pathlib import Path

    from care_ladder.plan_loader import load_care_plan

    plan = load_care_plan(Path("configs/demo_home.yaml"))
    # Disable no_movement; keep zone from plan
    plan.triggers.no_movement.enabled = False
    # Short timeout so stillness would otherwise fire
    plan.triggers.no_movement.timeout_sec = 1

    det = CueDetector.from_plan(plan, zone_id="living_room")
    frame = _blank(w=640, h=480)
    frame[200:280, 300:380] = 200
    assert det.observe(frame, t=0.0) is None
    cue = det.observe(frame, t=2.0)
    assert cue is None  # disabled → never emit no_movement


def test_from_plan_uses_timeout_and_zone():
    from pathlib import Path

    from care_ladder.plan_loader import load_care_plan

    plan = load_care_plan(Path("configs/demo_home.yaml"))
    plan.triggers.no_movement.timeout_sec = 2
    det = CueDetector.from_plan(plan, zone_id="living_room")
    assert det.no_movement_timeout_sec == 2.0
    frame = _blank(w=640, h=480)
    frame[200:280, 300:380] = 200
    assert det.observe(frame, t=0.0) is None
    cue = det.observe(frame, t=2.5)
    assert cue is not None
    assert cue.kind == "no_movement"
