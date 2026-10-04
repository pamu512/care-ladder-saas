"""Consume tests for the vendored opencv-care-ladder fall_cls_v1 artifact.

Non-clinical: no Kaggle bytes, no live video. Synthetic tiny frames only.
"""

from pathlib import Path

import numpy as np
import pytest

from care_ladder.vision.fall_cls import (
    FALL_CLS_SHA256,
    default_model_path,
    preprocess_bgr,
    score_frame,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ONNX = REPO_ROOT / "models" / "fall_cls_v1.onnx"
CARD = REPO_ROOT / "models" / "MODEL_CARD.md"


def test_vendored_onnx_sha256_matches_model_card():
    assert ONNX.is_file()
    assert sha256_file(ONNX) == FALL_CLS_SHA256
    assert default_model_path() == ONNX
    text = CARD.read_text(encoding="utf-8")
    assert FALL_CLS_SHA256 in text
    assert "Not a diagnosis" in text


def test_synthetic_tiny_image_infer_is_2class_softmax():
    from care_ladder.vision.fall_cls import FallClassifier

    blob = preprocess_bgr(np.zeros((8, 12, 3), dtype=np.uint8))
    assert blob.shape == (3, 32, 32)
    assert blob.dtype == np.float32
    assert float(blob.min()) >= 0.0
    assert float(blob.max()) <= 1.0

    clf = FallClassifier(ONNX)
    frame = np.full((16, 16, 3), 40, dtype=np.uint8)
    frame[10:14, 2:14] = (220, 40, 40)  # wide low bar, not a real fall photo
    out = clf.infer(frame)
    scores = np.asarray([out["scores"]["no_fall"], out["scores"]["fall"]], dtype=np.float32)
    assert scores.shape == (2,)
    assert scores.dtype == np.float32
    assert pytest.approx(float(scores.sum()), abs=1e-5) == 1.0
    assert out["artifact"] == "fall_cls_v1"
    assert out["non_clinical"] is True
    assert out["label"] in ("no_fall", "fall")


def test_score_frame_fail_soft_on_empty_and_opt_out(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_FALL_CLS", "0")
    assert score_frame(np.zeros((4, 4, 3), dtype=np.uint8)) is None
    monkeypatch.setenv("CARE_LADDER_FALL_CLS", "1")
    assert score_frame(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_distress_cue_gets_optional_fall_cls_soft_signal(monkeypatch):
    from care_ladder.vision.cues import CueDetector

    monkeypatch.setenv("CARE_LADDER_FALL_CLS", "1")
    det = CueDetector(
        no_movement_timeout_sec=99.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
        distress_sustain_sec=1.0,
    )
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[90:110, 40:120] = 200
    assert det.observe(frame, t=0.0) is None
    assert det.observe(frame, t=0.5) is None
    cue = det.observe(frame, t=1.5)
    assert cue is not None
    assert cue.kind == "distress_heuristic"
    assert cue.confidence == 0.7
    soft = cue.detail.get("fall_cls")
    assert soft is not None
    assert soft["non_clinical"] is True
    assert pytest.approx(soft["scores"]["no_fall"] + soft["scores"]["fall"], abs=1e-5) == 1.0


def test_fall_cls_opt_out_does_not_change_distress_kind(monkeypatch):
    from care_ladder.vision.cues import CueDetector

    monkeypatch.setenv("CARE_LADDER_FALL_CLS", "0")
    det = CueDetector(
        no_movement_timeout_sec=99.0,
        zone=((0, 0), (160, 0), (160, 120), (0, 120)),
        distress_sustain_sec=1.0,
    )
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[90:110, 40:120] = 200
    det.observe(frame, t=0.0)
    det.observe(frame, t=0.5)
    cue = det.observe(frame, t=1.5)
    assert cue is not None
    assert cue.kind == "distress_heuristic"
    assert "fall_cls" not in cue.detail
