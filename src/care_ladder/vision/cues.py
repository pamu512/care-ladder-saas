"""OpenCV cue detection: stillness, zone visibility, non-clinical distress heuristic."""

from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from care_ladder.models import CarePlan, CueEvent

Point = tuple[float, float]


class CueDetector:
    """Detect Care Ladder cues from a stream of BGR frames.

    Uses frame differencing for motion, contour centroids vs a zone polygon
    (`cv2.pointPolygonTest`) for presence, and a simple aspect-ratio / y-position
    heuristic for a non-clinical on-floor stand-in.

    After emitting a cue, internal timers / presence latch clear so the same cue
    does not spam every subsequent frame.
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
        enable_no_movement: bool = True,
        enable_no_visibility: bool = True,
        enable_distress_heuristic: bool = True,
        person_detector: Any | None = None,
        motion_source: str = "frame_diff",
    ) -> None:
        self.no_movement_timeout_sec = float(no_movement_timeout_sec)
        self.zone = np.asarray(zone, dtype=np.float32)
        self.motion_mean_threshold = motion_mean_threshold
        self.min_blob_area = min_blob_area
        self.distress_sustain_sec = float(distress_sustain_sec)
        self.distress_aspect_min = distress_aspect_min
        self.distress_y_ratio_min = distress_y_ratio_min
        self.binary_threshold = binary_threshold
        self.enable_no_movement = enable_no_movement
        self.enable_no_visibility = enable_no_visibility
        self.enable_distress_heuristic = enable_distress_heuristic
        self.person_detector = person_detector
        if motion_source not in ("frame_diff", "mog2"):
            raise ValueError(f"unknown motion_source {motion_source!r}")
        self.motion_source = motion_source
        self._mog2 = cv2.createBackgroundSubtractorMOG2(
            history=60, varThreshold=32.0, detectShadows=False
        )

        self._prev_gray: np.ndarray | None = None
        self._seen_in_zone = False
        self._presence_frames = 0
        self._still_since: float | None = None
        self._distress_since: float | None = None
        self.last_detection_source: str | None = None

    @classmethod
    def from_plan(cls, plan: CarePlan, zone_id: str | None = None) -> CueDetector:
        """Build a detector from ``CarePlan.triggers`` and a named (or first) zone."""
        if not plan.zones:
            raise ValueError("care plan has no zones for CueDetector.from_plan")
        zone_model = None
        if zone_id is not None:
            for z in plan.zones:
                if z.id == zone_id:
                    zone_model = z
                    break
            if zone_model is None:
                raise ValueError(f"zone_id {zone_id!r} not found in care plan")
        else:
            zone_model = plan.zones[0]

        polygon = [(float(p[0]), float(p[1])) for p in zone_model.polygon]
        return cls(
            no_movement_timeout_sec=float(plan.triggers.no_movement.timeout_sec),
            zone=polygon,
            enable_no_movement=bool(plan.triggers.no_movement.enabled),
            enable_no_visibility=bool(plan.triggers.no_visibility.enabled),
            enable_distress_heuristic=bool(plan.triggers.distress_heuristic.enabled),
        )

    def observe(self, frame: np.ndarray, t: float) -> CueEvent | None:
        gray = (
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if frame.ndim == 3
            else frame
        )
        h, w = gray.shape[:2]

        # Person localization: DNN person detector when available, else contour blob.
        if self.person_detector is not None:
            boxes = self._detect_people_dnn(frame)
            self.last_detection_source = "dnn_person_detector"
            blob = boxes[0] if boxes else None
        else:
            blob = self._largest_blob(gray)
            self.last_detection_source = "contour_blob"
        in_zone = bool(blob and self._point_in_zone(blob["cx"], blob["cy"]))

        # Motion: MOG2 foreground ratio (robust to global illumination drift) or
        # plain frame differencing.
        motion = 0.0
        if self.motion_source == "mog2":
            fg = self._mog2.apply(frame)
            motion = float(np.count_nonzero(fg)) / float(fg.size) * 255.0
        elif self._prev_gray is not None:
            diff = cv2.absdiff(gray, self._prev_gray)
            motion = float(np.mean(diff))
        self._prev_gray = gray.copy()

        if in_zone:
            self._presence_frames += 1
            # Require sustained presence before latching: single-frame noise
            # blobs (highlights, sensor noise) must not arm no_visibility.
            if not self._seen_in_zone and self._presence_frames >= 2:
                self._seen_in_zone = True
            if self._seen_in_zone:
                if self._still_since is None or motion > self.motion_mean_threshold:
                    self._still_since = t
                if self._is_distress_pose(blob, h):
                    if self._distress_since is None:
                        self._distress_since = t
                else:
                    self._distress_since = None
        else:
            self._presence_frames = 0
            self._still_since = None
            self._distress_since = None
            if self._seen_in_zone and self.enable_no_visibility:
                # Latch: require re-entry before another no_visibility.
                self._seen_in_zone = False
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
            self.enable_distress_heuristic
            and in_zone
            and self._distress_since is not None
            and (t - self._distress_since) >= self.distress_sustain_sec
        ):
            assert blob is not None
            sustain = t - self._distress_since
            # Clear so condition must re-accumulate (no per-frame spam).
            self._distress_since = None
            return CueEvent(
                kind="distress_heuristic",
                confidence=0.7,
                detail={
                    "non_clinical": True,
                    "note": "coarse aspect/y heuristic only; not a medical diagnosis",
                    "aspect_ratio": blob["aspect"],
                    "y_ratio": blob["cy"] / float(h),
                    "sustain_sec": sustain,
                },
            )

        if (
            self.enable_no_movement
            and in_zone
            and self._still_since is not None
            and (t - self._still_since) >= self.no_movement_timeout_sec
        ):
            still_sec = t - self._still_since
            # Restart stillness clock so the same still pose does not re-fire next frame.
            self._still_since = t
            return CueEvent(
                kind="no_movement",
                confidence=0.8,
                detail={
                    "still_sec": still_sec,
                    "motion_mean": motion,
                    "timeout_sec": self.no_movement_timeout_sec,
                },
            )

        return None

    def _point_in_zone(self, x: float, y: float) -> bool:
        # >= 0 means inside or on edge
        return cv2.pointPolygonTest(self.zone, (float(x), float(y)), False) >= 0.0

    def _detect_people_dnn(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Run the DNN person detector and normalize boxes to blob-dict shape."""
        rows = self.person_detector.infer(frame)
        out: list[dict[str, Any]] = []
        for r in rows:
            x1, y1, x2, y2 = (float(v) for v in r[:4])
            bw, bh = x2 - x1, y2 - y1
            area = bw * bh
            if area < self.min_blob_area:
                continue
            out.append(
                {
                    "cx": (x1 + x2) / 2.0,
                    "cy": (y1 + y2) / 2.0,
                    "w": float(bw),
                    "h": float(bh),
                    "area": float(area),
                    "aspect": (bw / float(bh)) if bh > 0 else 0.0,
                    "score": float(r[12]),
                }
            )
        return sorted(out, key=lambda b: -b["score"])

    def _largest_blob(self, gray: np.ndarray) -> dict[str, Any] | None:
        # Otsu picks the threshold from the frame histogram, so detection works
        # on realistic multi-tone scenes, not only dark-bg/bright-person demos.
        _, mask = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        frame_area = float(gray.shape[0]) * float(gray.shape[1])
        # Reject background slabs: a contour covering a large fraction of the
        # frame is the scene (floor/wall boundary), not a person.
        candidates = [c for c in contours if cv2.contourArea(c) < 0.2 * frame_area]
        if not candidates:
            return None
        contour = max(candidates, key=cv2.contourArea)
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
