"""PoseHeuristics: fall-signature state machine from torso metrics."""

from care_ladder.vision.pose_heuristics import PoseHeuristics, torso_metrics


def _upright(t=0.0):
    return {"torso_angle_deg": 8.0, "hip_y_ratio": 0.40, "keypoint_vis": 0.98}


def _down(t=0.0):
    return {"torso_angle_deg": 82.0, "hip_y_ratio": 0.85, "keypoint_vis": 0.95}


def test_sudden_fall_fires_with_sudden_flag():
    h = PoseHeuristics(sustain_sec=2.0)
    # upright 0..3s (≥ upright_required)
    for t in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        assert h.observe(_upright(), t) is None
    # sudden fall at t=3.2, sustained
    assert h.observe(_down(), 3.2) is None   # transition frame
    assert h.observe(_down(), 3.6) is None
    detail = h.observe(_down(), 5.4)         # ≥ sustain 2.0
    assert detail is not None
    assert detail["pattern"] == "sudden_vertical_to_horizontal"
    assert detail["sudden"] is True
    assert detail["non_clinical"] is True
    assert detail["torso_angle_deg"] > 55


def test_gradual_lying_down_not_sudden():
    h = PoseHeuristics(sustain_sec=2.0, gradual_window_sec=4.0)
    for t in [0.0, 0.5, 1.0, 2.0]:
        h.observe(_upright(), t)
    # slow drift: leaves upright at 2.5, reaches horizontal only at 8s
    h.observe({"torso_angle_deg": 40.0, "hip_y_ratio": 0.5, "keypoint_vis": 0.9}, 2.5)
    h.observe({"torso_angle_deg": 50.0, "hip_y_ratio": 0.55, "keypoint_vis": 0.9}, 5.0)
    h.observe(_down(), 8.0)      # transition frame
    detail = h.observe(_down(), 10.5)
    # gradual lying down is NOT cue-worthy — no distress detail returned
    assert detail is None
    assert any(e["type"] == "gradual_on_floor_ignored" for e in h.state.events)


def test_unreliable_keypoints_never_fire():
    h = PoseHeuristics(sustain_sec=1.0)
    h.observe(_upright(), 0.0)
    h.observe(_upright(), 1.0)
    assert h.observe(None, 1.5) is None
    # even many None frames later
    assert h.observe(None, 30.0) is None


def test_torso_metrics_geometry():
    import numpy as np

    # standing: shoulders above hips, x aligned
    lms = np.zeros((33, 5))
    lms[L := 11, :2] = (100, 100)
    lms[12, :2] = (110, 100)   # R shoulder
    lms[23, :2] = (100, 200)   # L hip
    lms[24, :2] = (110, 200)   # R hip
    lms[:, 3] = 0.99
    m = torso_metrics(lms, frame_h=400)
    assert m["torso_angle_deg"] < 10
    assert m["hip_y_ratio"] == 0.5

    # lying: hips and shoulders at same y (horizontal torso)
    lms[11, :2] = (200, 300)
    lms[12, :2] = (200, 310)
    lms[23, :2] = (100, 300)
    lms[24, :2] = (100, 310)
    m = torso_metrics(lms, frame_h=400)
    assert m["torso_angle_deg"] > 75

    # low visibility → None
    lms[:, 3] = 0.2
    assert torso_metrics(lms, frame_h=400) is None
