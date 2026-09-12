"""OpenCV cue detection: stillness, zone visibility, non-clinical distress heuristic."""

from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from care_ladder.models import CueEvent

Point = tuple[float, float]


class CueDetector:
    """Detect Care Ladder cues from a stream of BGR frames.

    Uses frame differencing for motion, contour centroids vs a zone polygon
    (`cv2.pointPolygonTest`) for presence, and a simple aspect-ratio / y-position
    heuristic for a non-clinical on-floor stand-in.
    """

    def __init__(
        self,
        no_movement_timeout_sec: float,
        zone: Sequence[Point],
        *,
        motion_mean_threshold: float = 2.0,
        min_blob_area: float = 100.0,
        distress_sustain_sec: float = 2.0,
        distress_aspect_min: float = 2.0,
        distress_y_ratio_min: float = 0.65,
        binary_threshold: int = 40,
    ) -> None:
        self.no_movement_timeout_sec = float(no_movement_timeout_sec)
        self.zone = np.asarray(zone, dtype=np.float32)
        self.motion_mean_threshold = motion_mean_threshold
        self.min_blob_area = min_blob_area
        self.distress_sustain_sec = float(distress_sustain_sec)
        self.distress_aspect_min = distress_aspect_min
        self.distress_y_ratio_min = distress_y_ratio_min
        self.binary_threshold = binary_threshold

        self._prev_gray: np.ndarray | None = None
        self._seen_in_zone = False
        self._still_since: float | None = None
        self._distress_since: float | None = None

    def observe(self, frame: np.ndarray, t: float) -> CueEvent | None:
        gray = (
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if frame.ndim == 3
            else frame
        )
        h, w = gray.shape[:2]
        blob = self._largest_blob(gray)
        in_zone = bool(blob and self._point_in_zone(blob["cx"], blob["cy"]))

        motion = 0.0
        if self._prev_gray is not None:
            diff = cv2.absdiff(gray, self._prev_gray)
            motion = float(np.mean(diff))
        self._prev_gray = gray.copy()

        if in_zone:
            self._seen_in_zone = True
            if self._still_since is None or motion > self.motion_mean_threshold:
                self._still_since = t
            if self._is_distress_pose(blob, h):
                if self._distress_since is None:
                    self._distress_since = t
            else:
                self._distress_since = None
        else:
            self._still_since = None
            self._distress_since = None
            if self._seen_in_zone:
                return CueEvent(
                    kind="no_visibility",
                    confidence=0.85,
                    detail={
                        "reason": "blob_left_zone_or_absent",
                        "in_zone": False,
                        "motion_mean": motion,
                    },
                )

        if (
            in_zone
            and self._distress_since is not None
            and (t - self._distress_since) >= self.distress_sustain_sec
        ):
            assert blob is not None
            return CueEvent(
                kind="distress_heuristic",
                confidence=0.7,
                detail={
                    "non_clinical": True,
                    "note": "coarse aspect/y heuristic only; not a medical diagnosis",
                    "aspect_ratio": blob["aspect"],
                    "y_ratio": blob["cy"] / float(h),
                    "sustain_sec": t - self._distress_since,
                },
            )

        if (
            in_zone
            and self._still_since is not None
            and (t - self._still_since) >= self.no_movement_timeout_sec
        ):
            return CueEvent(
                kind="no_movement",
                confidence=0.8,
                detail={
                    "still_sec": t - self._still_since,
                    "motion_mean": motion,
                    "timeout_sec": self.no_movement_timeout_sec,
                },
            )

        return None

    def _point_in_zone(self, x: float, y: float) -> bool:
        # >= 0 means inside or on edge
        return cv2.pointPolygonTest(self.zone, (float(x), float(y)), False) >= 0.0

    def _largest_blob(self, gray: np.ndarray) -> dict[str, Any] | None:
        _, mask = cv2.threshold(
            gray, self.binary_threshold, 255, cv2.THRESH_BINARY
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < self.min_blob_area:
            return None
        x, y, bw, bh = cv2.boundingRect(contour)
        m = cv2.moments(contour)
        if m["m00"] == 0:
            cx = x + bw / 2.0
            cy = y + bh / 2.0
        else:
            cx = float(m["m10"] / m["m00"])
            cy = float(m["m01"] / m["m00"])
        aspect = (bw / float(bh)) if bh > 0 else 0.0
        return {
            "cx": cx,
            "cy": cy,
            "w": float(bw),
            "h": float(bh),
            "area": area,
            "aspect": aspect,
        }

    def _is_distress_pose(self, blob: dict[str, Any] | None, frame_h: int) -> bool:
        if not blob or frame_h <= 0:
            return False
        y_ratio = blob["cy"] / float(frame_h)
        return (
            blob["aspect"] >= self.distress_aspect_min
            and y_ratio >= self.distress_y_ratio_min
        )
