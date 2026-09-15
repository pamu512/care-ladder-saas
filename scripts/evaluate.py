#!/usr/bin/env python
"""Run the labeled cue-detection evaluation and print/write metrics.

Usage:
    python scripts/evaluate.py [--json out.json] [--dnn]

--dnn routes person localization through the OpenCV 5 DNN detector when the
ONNX model is present (auto for the photo case; synthetic cases use the
contour path which is the demo default).

Non-clinical evaluation on labeled fixtures only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from care_ladder.vision.cues import CueDetector  # noqa: E402
from care_ladder.vision.eval_cases import build_cases, summarize  # noqa: E402

MODEL = ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"


def run_case(case, use_dnn: bool) -> dict:
    frames = case.frames()  # may be empty when photo fixture / clip missing
    if not frames:
        return {
            "case_id": case.case_id,
            "expect_cue": case.expect_cue,
            "emitted": None,
            "skipped": "no frames (missing photo fixture or clip — run scripts/download_clips.sh)",
        }

    detector_kwargs = {}
    POSE_MODEL = ROOT / "models" / "pose_estimation_mediapipe_2023mar.onnx"
    if use_dnn and MODEL.exists() and case.case_id.startswith(("photo", "clip")):
        from care_ladder.vision.mppersondet import MPPersonDet
        from care_ladder.vision.mppose import MPPose

        detector_kwargs["person_detector"] = MPPersonDet(str(MODEL), scoreThreshold=0.3)
        if POSE_MODEL.exists():
            detector_kwargs["pose_model"] = MPPose(str(POSE_MODEL), confThreshold=0.5)

    # Detector tuned per-case: stillness timeout just under the case budget.
    if case.case_id.startswith("clip"):
        timeout = 99.0  # clip cases run real time; pose machine has its own timing
    else:
        timeout = min(case.timeout_sec, 3.0) if case.expect_cue == "no_movement" else 99.0
    frames_preview = case.frames()  # may be empty when photo fixture missing
    if frames_preview:
        h, w = frames_preview[0][0].shape[:2]
    else:
        w, h = 320, 240
    det = CueDetector(
        no_movement_timeout_sec=timeout,
        zone=((0, 0), (w, 0), (w, h), (0, h)),
        motion_source="mog2",
        **detector_kwargs,
    )
    frames = frames_preview

    emitted = None
    time_to_cue = None
    for frame, t in frames:
        cue = det.observe(frame, t=t)
        if cue is not None:
            # keep the FIRST cue; record timing
            if emitted is None:
                emitted = cue.kind
                time_to_cue = round(t, 2)
            if cue.kind == case.expect_cue:
                emitted = cue.kind
                time_to_cue = round(t, 2)
                break

    hit = emitted == case.expect_cue
    return {
        "case_id": case.case_id,
        "description": case.description,
        "expect_cue": case.expect_cue,
        "emitted": emitted,
        "time_to_cue_sec": time_to_cue if hit else None,
        "pass": hit,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None, help="write metrics JSON here")
    ap.add_argument("--dnn", action="store_true", help="use DNN person detection where applicable")
    args = ap.parse_args()

    results = [run_case(c, use_dnn=args.dnn) for c in build_cases()]
    metrics = summarize(results)
    metrics["dnn"] = bool(args.dnn and MODEL.exists())

    print(json.dumps(metrics, indent=2))
    if args.json:
        args.json.write_text(json.dumps(metrics, indent=2))
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0 if all(r.get("pass") for r in results if not r.get("skipped")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
