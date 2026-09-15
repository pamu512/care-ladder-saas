"""Real video ingest: synthetic MP4 → CueDetector → cue + pre-event window."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from care_ladder.models import CueEvent  # noqa: F401
from care_ladder.vision.cues import CueDetector
from care_ladder.vision.ingest import ingest_video, save_upload


def _make_clip(path: Path, *, person_frames: int = 20, total_frames: int = 30, fps: int = 5):
    """Tiny MP4: textured person stands in frame, then leaves (empty room)."""
    w, h = 320, 240
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert vw.isOpened()
    rng = np.random.default_rng(11)
    for i in range(total_frames):
        frame = (rng.random((h, w, 3)) * 20 + 30).astype(np.uint8)
        if i < person_frames:
            frame[60:190, 130:200] = (110, 130, 150)  # torso
            cv2.circle(frame, (165, 45), 20, (180, 170, 160), -1)  # head
        vw.write(frame)
    vw.release()


def test_ingest_video_detects_person_leaving(tmp_path: Path):
    clip = tmp_path / "leaves.mp4"
    _make_clip(clip)

    det = CueDetector(
        no_movement_timeout_sec=99.0,  # isolate no_visibility
        zone=((0, 0), (320, 0), (320, 240), (0, 240)),
        motion_source="mog2",
    )
    result = ingest_video(clip, det, pre_event_seconds=2.0)

    assert result.cue is not None
    assert result.cue.kind == "no_visibility"
    assert result.fps == 5.0
    assert result.frame_count > 0
    # pre-event window captured frames, including person-present ones
    assert 0 < len(result.pre_event_frames) <= 15
    assert result.detector_source in {"contour_blob", "dnn_person_detector"}


def test_ingest_video_stillness_cue(tmp_path: Path):
    clip = tmp_path / "still.mp4"
    _make_clip(clip, person_frames=30, total_frames=30)  # person never leaves

    det = CueDetector(
        no_movement_timeout_sec=2.0,
        zone=((0, 0), (320, 0), (320, 240), (0, 240)),
        motion_source="mog2",
    )
    result = ingest_video(clip, det)
    assert result.cue is not None
    assert result.cue.kind == "no_movement"


def test_save_upload_roundtrip(tmp_path: Path):
    clip = tmp_path / "x.mp4"
    _make_clip(clip, person_frames=2, total_frames=3)
    data = clip.read_bytes()
    spilled = save_upload(data)
    try:
        assert spilled.exists() and spilled.stat().st_size == len(data)
    finally:
        spilled.unlink()


def test_ingest_rejects_garbage(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    det = CueDetector(no_movement_timeout_sec=2.0, zone=((0, 0), (9, 0), (9, 9), (0, 9)))
    with pytest.raises(ValueError):
        ingest_video(bad, det)
