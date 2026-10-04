"""Consume helper for the vendored opencv-care-ladder fall_cls_v1 ONNX.

Sibling artifact from pamu512/opencv-care-ladder @ a7357c0. OpenCV cues still
drive the care ladder; this scores a frame as an optional soft signal.
Non-clinical. Not a diagnosis.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

FALL_CLS_SHA256 = "549721e2b29cad10776fde2cb6186cf19383f982050f37e9335096c1aaadb608"
FALL_CLS_FILENAME = "fall_cls_v1.onnx"
INPUT_SIZE = 32
LABELS = ("no_fall", "fall")

_LAZY: FallClassifier | None | bool = False


def default_model_path() -> Path:
    return Path(__file__).resolve().parents[3] / "models" / FALL_CLS_FILENAME


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fall_cls_enabled() -> bool:
    raw = os.environ.get("CARE_LADDER_FALL_CLS", "1").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def preprocess_bgr(image: np.ndarray, size: int = INPUT_SIZE) -> np.ndarray:
    """Match opencv-care-ladder preprocess: BGR resize then /255 → CHW float32."""
    if image is None or getattr(image, "size", 0) == 0:
        raise ValueError("empty image")
    if image.ndim == 2:
        image = np.stack([image, image, image], axis=-1)
    elif image.ndim != 3 or image.shape[2] < 3:
        raise ValueError(f"expected HWC BGR image, got shape {getattr(image, 'shape', None)}")
    if image.shape[2] > 3:
        image = image[:, :, :3]
    resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
    chw = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    return np.clip(chw, 0.0, 1.0)


class FallClassifier:
    def __init__(self, model_path: str | Path | None = None, *, verify_sha256: bool = True) -> None:
        path = Path(model_path) if model_path is not None else default_model_path()
        if not path.is_file():
            raise FileNotFoundError(f"fall_cls weights missing: {path}")
        if verify_sha256:
            digest = sha256_file(path)
            if digest != FALL_CLS_SHA256:
                raise ValueError(f"fall_cls SHA256 mismatch: {digest} != {FALL_CLS_SHA256}")
        net = cv2.dnn.readNetFromONNX(str(path))
        if net.empty():
            raise RuntimeError(f"OpenCV DNN failed to load {path}")
        self.model_path = path
        self.net = net

    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        blob = preprocess_bgr(image_bgr)[None]
        self.net.setInput(blob)
        out = self.net.forward()
        probs = np.asarray(out, dtype=np.float32).reshape(-1)
        if probs.size != 2:
            raise RuntimeError(f"expected 2-class scores, got {probs.shape}")
        total = float(probs.sum())
        if total <= 0 or not np.isfinite(total):
            raise RuntimeError("onnx scores summed to 0")
        probs = probs / total
        return {
            "artifact": "fall_cls_v1",
            "sha256": FALL_CLS_SHA256,
            "scores": {"no_fall": float(probs[0]), "fall": float(probs[1])},
            "label": LABELS[int(probs.argmax())],
            "non_clinical": True,
            "note": "optional soft cue from opencv-care-ladder fall_cls_v1; not a diagnosis",
        }


def _lazy_classifier() -> FallClassifier | None:
    global _LAZY
    if _LAZY is False:
        try:
            _LAZY = FallClassifier()
        except Exception:
            _LAZY = None
    return None if _LAZY is False else _LAZY


def score_frame(
    image_bgr: np.ndarray,
    classifier: FallClassifier | None = None,
) -> dict[str, Any] | None:
    """Fail-soft scorer. None when disabled, unloadable, or infer fails."""
    if not fall_cls_enabled():
        return None
    try:
        clf = classifier if classifier is not None else _lazy_classifier()
        if clf is None:
            return None
        return clf.infer(image_bgr)
    except Exception:
        return None
