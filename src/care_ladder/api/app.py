"""FastAPI incident timeline + demo trigger (demo fixtures only; no live camera)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from care_ladder.audit.store import AuditStore
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEMO_PLAN_PATH = _REPO_ROOT / "configs" / "demo_home.yaml"

SUPPORTED_FIXTURES = frozenset(
    {
        "no_movement_ok",
        "no_movement_silence",
        "opencv_stillness",
        "opencv_dnn_person",
    }
)
_MODEL_PATH = _REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"
# Midday UTC so quiet_hours soft-suppress does not hide the judge demo ladder.
DEMO_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


class DemoRunRequest(BaseModel):
    fixture: str = Field(
        ...,
        description='Demo fixture id, e.g. "no_movement_silence" or "opencv_stillness"',
    )


class DemoRunResponse(BaseModel):
    incident_id: str


def _incident_summary(incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "household_id": incident.household_id,
        "status": incident.status,
        "cue": incident.cue.model_dump(),
        "event_count": len(incident.events),
    }


async def _run_no_movement_ok(store: AuditStore):
    """Fixture: no_movement cue + verbal OK → resolve without dial (spec §10 Path A)."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "no_movement_ok"})
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})  # never reached on this path
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        store=store,
        now=DEMO_NOW,
    )
    return incident


async def _run_no_movement_silence(store: AuditStore):
    """Fixture: no_movement cue + speaker silence → escalate via stub dialer."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "no_movement_silence"})
    # Silence path: empty script → escalate; secondary answers so incident resolves.
    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        store=store,
        now=DEMO_NOW,
    )
    return incident


def _synthetic_stillness_frames(
    *,
    width: int = 160,
    height: int = 120,
) -> list[np.ndarray]:
    """Build a short synthetic still-person sequence for CueDetector (no live camera)."""
    frames: list[np.ndarray] = []
    for _ in range(4):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[40:80, 60:100] = 200
        frames.append(frame)
    return frames


async def _run_opencv_stillness(store: AuditStore):
    """Fixture: synthetic frames → CueDetector.observe → run_incident (OpenCV path)."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    # Short timeout so demo/tests emit no_movement without waiting plan's 900s.
    plan.triggers.no_movement.timeout_sec = 2
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    # Zone in demo YAML is 640x480; use matching canvas so blob sits in-zone.
    frames = _synthetic_stillness_frames(width=640, height=480)
    # Place blob well inside living_room polygon
    for f in frames:
        f[:, :] = 0
        f[200:280, 300:380] = 200

    cue: CueEvent | None = None
    times = [0.0, 1.0, 2.5, 3.0]
    for frame, t in zip(frames, times, strict=True):
        cue = detector.observe(frame, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_stillness fixture: CueDetector did not emit a cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_cue_detector",
        "fixture": "opencv_stillness",
    }

    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    # Attach last frames (privacy-blurred inside run_incident).
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=frames[-2:],
        store=store,
        privacy_mode="blur",
        now=DEMO_NOW,
    )
    return incident


async def _run_opencv_dnn_person(store: AuditStore):
    """Fixture: real photo → DNN person detector → zone check → ladder.

    Uses tests/fixtures/basketball1.png (OpenCV sample image with a person).
    Requires models/person_detection_mediapipe_2023mar.onnx (scripts/download_models.sh).
    The DNN localizes the person (in-zone) every frame; identical frames → motion stays
    ~0 → `no_movement` cue → ladder.
    """
    import cv2

    photo = cv2.imread(str(_REPO_ROOT / "tests" / "fixtures" / "basketball1.png"))
    if photo is None:
        raise RuntimeError("opencv_dnn_person fixture: sample photo missing")
    if not _MODEL_PATH.exists():
        raise RuntimeError(
            "opencv_dnn_person fixture: run scripts/download_models.sh first"
        )

    from care_ladder.vision.mppersondet import MPPersonDet

    plan = load_care_plan(_DEMO_PLAN_PATH)
    plan.triggers.no_movement.timeout_sec = 2  # demo clock, not plan's 900s
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)

    cue: CueEvent | None = None
    times = [0.0, 1.0, 2.5, 3.0]
    for t in times:
        cue = detector.observe(photo, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_dnn_person fixture: detector emitted no cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_dnn_person_detector",
        "detector": "mediapipe_persondet_2023mar (OpenCV 5 DNN)",
        "fixture": "opencv_dnn_person",
    }

    speaker = SpeakerSimulator(scripted=["I'm fine, thanks"])
    dialer = StubDialer(behavior={})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[photo],
        store=store,
        privacy_mode="silhouette",
        now=DEMO_NOW,
    )
    return incident


def create_app(store: AuditStore | None = None) -> FastAPI:
    """Build FastAPI app with injectable in-memory AuditStore (tests use a fresh store)."""
    audit = store if store is not None else AuditStore()
    application = FastAPI(
        title="Care Ladder",
        description="Incident timeline + demo trigger (reserved phones; emergency fail-closed).",
        version="0.1.0",
    )
    application.state.store = audit

    static_dir = Path(__file__).resolve().parent / "static"
    application.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")

    @application.get("/incidents")
    def list_incidents() -> list[dict[str, Any]]:
        return [_incident_summary(i) for i in application.state.store.list_incidents()]

    @application.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict[str, Any]:
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        # Full timeline JSON: ordered audit events (cue → tools → resolve/jump).
        return incident.model_dump()

    @application.get("/incidents/{incident_id}/frames/{index}", response_class=Response)
    def get_incident_frame(incident_id: str, index: int):
        """Serve a privacy-transformed pre-event frame as PNG.

        Frames reaching this endpoint already went through blur/silhouette in
        run_incident; raw identifiable pixels never enter the store.
        """
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        if not (0 <= index < len(frames)):
            raise HTTPException(
                status_code=404,
                detail=f"frame index {index} out of range (0..{max(len(frames)-1, 0)})",
            )
        ok, buf = cv2.imencode(".png", frames[index])
        if not ok:
            raise HTTPException(status_code=500, detail="png encode failed")
        return Response(content=buf.tobytes(), media_type="image/png")

    @application.get("/incidents/{incident_id}/frames")
    def list_incident_frames(incident_id: str) -> dict[str, Any]:
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        return {
            "privacy": incident.privacy,
            "count": len(frames),
            "frame_urls": [f"/incidents/{incident_id}/frames/{i}" for i in range(len(frames))],
        }

    @application.post("/demo/run", response_model=DemoRunResponse)
    async def demo_run(body: DemoRunRequest) -> DemoRunResponse:
        if body.fixture not in SUPPORTED_FIXTURES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown fixture {body.fixture!r}; supported: {sorted(SUPPORTED_FIXTURES)}",
            )
        if body.fixture == "no_movement_ok":
            incident = await _run_no_movement_ok(application.state.store)
        elif body.fixture == "no_movement_silence":
            incident = await _run_no_movement_silence(application.state.store)
        elif body.fixture == "opencv_stillness":
            incident = await _run_opencv_stillness(application.state.store)
        elif body.fixture == "opencv_dnn_person":
            incident = await _run_opencv_dnn_person(application.state.store)
        else:  # pragma: no cover - guarded by SUPPORTED_FIXTURES
            raise HTTPException(status_code=400, detail="unsupported fixture")
        return DemoRunResponse(incident_id=incident.id)

    return application


# Default ASGI app for `uvicorn care_ladder.api.app:app`
app = create_app()
