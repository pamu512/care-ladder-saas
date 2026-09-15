"""Pose-based distress heuristics: fall signature from keypoint geometry.

Given BlazePose-style landmarks (33 keypoints, [x, y, z, visibility, presence]),
compute torso orientation / hip height and run a temporal state machine:

- ``upright`` sustained → person suddenly ``horizontal`` (torso near floor-parallel)
  with hip low, sustained ≥ ``sustain_sec`` → **fall signature** cue
  (``pattern: sudden_vertical_to_horizontal``).
- A GRADUAL transition to lying (slow angle drift, e.g. lying down on a bed) does
  not fire the fast-transition gate — it may still raise a low-severity
  on-floor signal after a longer window.

Non-clinical heuristic: geometry only; the ladder (voice check-in → caregiver)
does the confirming. Never claims "fall detected" autonomously.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# BlazePose keypoint indices
L_SHOULDER, R_SHOULDER = 11, 12
L_HIP, R_HIP = 23, 24


def torso_metrics(landmarks: np.ndarray, frame_h: int) -> dict[str, float] | None:
    """Torso angle from vertical + hip height ratio, or None if keypoints unreliable."""
    lms = np.asarray(landmarks)
    if lms.ndim != 2 or lms.shape[0] <= R_HIP:
        return None
    vis = np.mean([lms[L_SHOULDER, 3], lms[R_SHOULDER, 3], lms[L_HIP, 3], lms[R_HIP, 3]])
    if vis < 0.5:
        return None
    sh = (lms[L_SHOULDER, :2] + lms[R_SHOULDER, :2]) / 2.0
    hp = (lms[L_HIP, :2] + lms[R_HIP, :2]) / 2.0
    v = sh - hp
    if np.linalg.norm(v) < 1e-3:
        return None
    # 0° = perfectly upright; 90° = horizontal (lying)
    angle = abs(math.degrees(math.atan2(float(v[0]), -float(v[1]))))
    angle = min(angle, 180.0 - angle)
    return {
        "torso_angle_deg": round(angle, 1),
        "hip_y_ratio": round(float(hp[1]) / max(frame_h, 1), 3),
        "keypoint_vis": round(float(vis), 2),
    }


@dataclass
class PoseFallState:
    upright_since: float | None = None
    down_since: float | None = None
    last_angle: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class PoseHeuristics:
    """State machine over per-frame torso metrics → fall signature detection."""

    def __init__(
        self,
        *,
        upright_angle_max: float = 35.0,   # below → counts as upright
        down_angle_min: float = 55.0,      # above → counts as horizontal
        hip_low_ratio: float = 0.60,       # hip y below this fraction of frame → low
        upright_required_sec: float = 1.0, # must be upright this long before a fall counts
        sustain_sec: float = 2.0,          # stay down this long to fire
        gradual_window_sec: float = 4.0,   # slower than this = gradual (no fast-fall)
    ) -> None:
        self.upright_angle_max = upright_angle_max
        self.down_angle_min = down_angle_min
        self.hip_low_ratio = hip_low_ratio
        self.upright_required_sec = upright_required_sec
        self.sustain_sec = sustain_sec
        self.gradual_window_sec = gradual_window_sec
        self.state = PoseFallState()

    def observe(self, metrics: dict[str, float] | None, t: float) -> dict[str, Any] | None:
        """Feed torso metrics (or None when keypoints lost); returns a detail dict
        when the fall signature fires, else None."""
        st = self.state

        if metrics is None:
            # keypoints lost: do not fire, but keep prior timing context
            return None

        angle = metrics["torso_angle_deg"]
        hip_low = metrics["hip_y_ratio"] >= self.hip_low_ratio
        is_upright = angle <= self.upright_angle_max
        is_down = angle >= self.down_angle_min and hip_low

        if is_upright:
            if st.upright_since is None:
                st.upright_since = t
        else:
            # left upright: require a minimum upright history for a "fall from
            # standing" interpretation
            if st.upright_since is not None and t - st.upright_since >= self.upright_required_sec:
                st.events.append({"type": "left_upright", "t": round(t, 2)})
            st.upright_since = None

        if is_down:
            if st.down_since is None:
                st.down_since = t
                st.events.append({"type": "went_horizontal", "t": round(t, 2)})
            elif t - st.down_since >= self.sustain_sec:
                # classify transition speed using the logged left_upright time
                left = [e["t"] for e in st.events if e["type"] == "left_upright"]
                went = [e["t"] for e in st.events if e["type"] == "went_horizontal"]
                sudden = bool(left and went and (went[-1] - left[-1]) <= self.gradual_window_sec)
                detail = {
                    "pattern": "sudden_vertical_to_horizontal" if sudden else "gradual_on_floor",
                    "sudden": sudden,
                    "down_sec": round(t - st.down_since, 2),
                    "torso_angle_deg": angle,
                    "hip_y_ratio": metrics["hip_y_ratio"],
                    "non_clinical": True,
                    "note": "pose-geometry fall signature; not a medical diagnosis",
                }
                # reset so it must re-accumulate
                st.down_since = None
                st.events = st.events[-4:]
                return detail
        else:
            st.down_since = None

        st.last_angle = angle
        return None
