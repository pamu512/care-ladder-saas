"""FastAPI incident timeline + demo trigger (demo fixtures only; no live camera)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import asyncio

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from uuid import uuid4
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from care_ladder.audit.store import AuditStore
from care_ladder.channels.dial import StubDialer
from care_ladder.cloud.sinks import CloudSinks
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector
from care_ladder.vision.ingest import ingest_video, save_upload

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEMO_PLAN_PATH = _REPO_ROOT / "configs" / "demo_home.yaml"

SUPPORTED_FIXTURES = frozenset(
    {
        "no_movement_ok",
        "no_movement_silence",
        "opencv_stillness",
        "opencv_dnn_person",
        "opencv_pose_person",
        "facility_notify_silence",
    }
)
_FACILITY_PLAN_PATH = _REPO_ROOT / "configs" / "demo_facility.yaml"
_POSE_MODEL_PATH = _REPO_ROOT / "models" / "pose_estimation_mediapipe_2023mar.onnx"
_MODEL_PATH = _REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"
# Midday UTC so quiet_hours soft-suppress does not hide the judge demo ladder.
DEMO_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


class CheckoutRequest(BaseModel):
    plan: str


class LoginRequest(BaseModel):
    email: str
    password: str


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


async def _run_facility_notify_silence(store: AuditStore):
    """Facility fixture: check-in silence -> notify ops -> supervisor -> dial primary."""
    from care_ladder.channels.notify import NotifyChannelAdapter
    from care_ladder.channels.supervisor import NotifySupervisorAdapter

    plan = load_care_plan(_FACILITY_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_notify_silence"})
    speaker = SpeakerSimulator(scripted=[])  # silence
    dialer = StubDialer(behavior={"caregiver": "answered"})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        store=store,
        notifier=NotifyChannelAdapter(),
        supervisor_notifier=NotifySupervisorAdapter(supervisor=plan.supervisor),
        now=DEMO_NOW,
    )
    return incident


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


def _default_store() -> AuditStore:
    """dynamodb when CARE_LADDER_STORE=dynamodb (and boto3 present), else memory."""
    if os.environ.get("CARE_LADDER_STORE", "").lower() == "dynamodb":
        try:
            from care_ladder.audit.dynamo_store import DynamoAuditStore

            return DynamoAuditStore()
        except Exception as exc:  # pragma: no cover - env-dependent
            print(f"WARNING: CARE_LADDER_STORE=dynamodb failed ({exc}); using memory")
    return AuditStore()


async def _publish_cloud(incident) -> None:
    """Best-effort S3 clip upload + EventBridge cue emission (no-ops locally).

    Never fails the incident: cloud sink errors are logged and swallowed.
    """
    try:
        sinks = CloudSinks()
        if not sinks.enabled:
            return
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        uris = sinks.upload_clip_frames(incident.id, frames, incident.privacy)
        sinks.emit_cue(incident, uris)
    except Exception as exc:  # pragma: no cover - env-dependent
        print(f"WARNING: cloud publish failed for {incident.id}: {exc}")


async def _run_opencv_pose_person(store: AuditStore):
    """Fixture: real photo → person ONNX → pose ONNX → torso metrics, no distress.

    Standing person: pose runs, torso angle computed, no distress cue; the
    incident demonstrates the pose path end-to-end with `source: pose_heuristics`
    context in the cue detail (pattern telemetry, not a fall).
    """
    import cv2

    photo = cv2.imread(str(_REPO_ROOT / "tests" / "fixtures" / "basketball1.png"))
    if photo is None:
        raise RuntimeError("opencv_pose_person fixture: sample photo missing")
    if not _MODEL_PATH.exists() or not _POSE_MODEL_PATH.exists():
        raise RuntimeError("opencv_pose_person fixture: run scripts/download_models.sh first")

    from care_ladder.vision.mppersondet import MPPersonDet
    from care_ladder.vision.mppose import MPPose

    plan = load_care_plan(_DEMO_PLAN_PATH)
    plan.triggers.no_movement.timeout_sec = 2
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)
    detector.pose_model = MPPose(str(_POSE_MODEL_PATH), confThreshold=0.5)

    cue = None
    for t in [0.0, 0.5, 1.0, 2.5, 3.0]:
        cue = detector.observe(photo, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_pose_person fixture: detector emitted no cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_pose_path",
        "pose": getattr(detector, "last_pose_metrics", None),
        "models": ["person_detection_mediapipe_2023mar", "pose_estimation_mediapipe_2023mar"],
        "fixture": "opencv_pose_person",
    }
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})
    return await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        pre_event_frames=[photo], store=store, privacy_mode="silhouette", now=DEMO_NOW,
    )


# In-flight upload analysis jobs: job_id -> {status, filename, incident_id, error}
_UPLOAD_JOBS: dict[str, dict[str, Any]] = {}

# bcrypt hashes for the seeded demo users (computed once; passwords are in
# tenancy.service and only ever live in demo mode)
_DEMO_HASHES: dict[str, str] = {}


def _demo_hash(email: str) -> str:
    from care_ladder.auth.passwords import hash_password
    from care_ladder.tenancy.service import find_demo_user

    if email not in _DEMO_HASHES:
        user = find_demo_user(email)
        _DEMO_HASHES[email] = hash_password(user.password) if user else "!"
    return _DEMO_HASHES[email]


def create_app(store: AuditStore | None = None) -> FastAPI:
    """Build FastAPI app with injectable store (tests inject a fresh memory store)."""
    audit = store if store is not None else _default_store()
    application = FastAPI(
        title="Care Ladder",
        description="Incident timeline + demo trigger (reserved phones; emergency fail-closed).",
        version="0.1.0",
    )
    application.state.store = audit

    static_dir = Path(__file__).resolve().parent / "static"
    application.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")

    # ---- SaaS auth (Task 2) -------------------------------------------------
    # CARE_LADDER_AUTH=on requires a session on /demo/* and /incidents*;
    # unauthenticated = 401 (no shared anonymous tenant). AUTH off (default)
    # keeps the upstream open demo behavior untouched.
    from care_ladder.auth.sessions import COOKIE_NAME, read_session_token

    def _auth_on() -> bool:
        return os.environ.get("CARE_LADDER_AUTH", "off").lower() in ("on", "1", "true")

    def _session_secret() -> str:
        return os.environ.get("SESSION_SECRET", "")

    def _require_session(request: Request):
        """Returns SessionData or None; None => caller must 401 (when auth on)."""
        if not _auth_on():
            return None
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or not _session_secret():
            raise HTTPException(status_code=401, detail="authentication required")
        data = read_session_token(token, secret=_session_secret())
        if data is None:
            raise HTTPException(status_code=401, detail="invalid or expired session")
        return data

    @application.post("/auth/login")
    def auth_login(body: LoginRequest, response: Response):
        from care_ladder.tenancy.service import find_demo_user

        user = find_demo_user(body.email)
        from care_ladder.auth.passwords import verify_password

        if user is None or not verify_password(body.password, _demo_hash(user.email)):
            raise HTTPException(status_code=401, detail="invalid email or password")
        from care_ladder.auth.sessions import SessionData, create_session_token

        token = create_session_token(
            SessionData(user_id=user.email, tenant_id=user.tenant_id, email=user.email),
            secret=_session_secret(),
        )
        response.set_cookie(
            COOKIE_NAME, token, max_age=7 * 24 * 3600, httponly=True, samesite="lax"
        )
        return {
            "email": user.email,
            "tenant": {
                "id": user.tenant_id,
                "mode": user.tenant_mode,
                "plan": user.tenant_plan,
            },
        }

    @application.post("/auth/logout")
    def auth_logout(response: Response):
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True}

    @application.get("/auth/me")
    def auth_me(request: Request):
        session = _require_session(request)
        if session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        from care_ladder.tenancy.service import find_demo_user

        user = find_demo_user(session.email)
        if user is None:
            raise HTTPException(status_code=401, detail="unknown session user")
        return {
            "email": user.email,
            "tenant": {
                "id": user.tenant_id,
                "mode": user.tenant_mode,
                "plan": user.tenant_plan,
            },
        }

    def _tenant_store(request: Request):
        """Per-tenant store when auth on: memory mode keeps a dict of stores;
        a shared store (Postgres-backed) is scoped at construction elsewhere."""
        session = _require_session(request)
        if session is None:
            return application.state.store
        if not hasattr(application.state, "tenant_stores"):
            application.state.tenant_stores = {}
        return application.state.tenant_stores.setdefault(
            session.tenant_id, AuditStore()
        )

    # ---- billing (Task 8) ---------------------------------------------------
    _BILLING_TENANTS: dict[str, dict[str, Any]] = {
        "demo-home": {"mode": "home", "plan": "home", "status": "active"},
        "demo-facility": {"mode": "facility", "plan": "demo", "status": "demo"},
    }
    application.state.billing_tenants = _BILLING_TENANTS

    @application.post("/billing/checkout")
    def billing_checkout(body: CheckoutRequest):
        from care_ladder.billing.stripe_checkout import BillingError, create_checkout_url

        try:
            url = create_checkout_url(body.plan, tenant_id="demo-facility")
        except BillingError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return {"url": url}

    @application.get("/billing/stub-success")
    def billing_stub_success(plan: str, tenant: str = "demo-facility"):
        t = application.state.billing_tenants.setdefault(
            tenant, {"mode": "facility", "plan": "demo", "status": "demo"}
        )
        t["plan"] = plan
        t["status"] = "active"
        return {"ok": True, "plan": plan, "note": "demo stub checkout; no card was charged"}

    @application.post("/billing/webhook")
    async def billing_webhook(request: Request):
        import json as _json

        from care_ladder.billing.stripe_checkout import apply_subscription_event, verify_webhook

        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        if not verify_webhook(payload, signature):
            raise HTTPException(status_code=400, detail="webhook verification failed")
        event = _json.loads(payload or b"{}")
        result = apply_subscription_event(event, application.state.billing_tenants)
        return result

    @application.get("/billing/tenant/{tenant_id}")
    def billing_tenant(tenant_id: str):
        t = application.state.billing_tenants.get(tenant_id)
        if t is None:
            raise HTTPException(status_code=404, detail="unknown tenant")
        return t

    @application.get("/demo/context")
    def demo_context():
        """Unauthenticated landing context (Render health check target)."""
        return {
            "auth": _auth_on(),
            "demo_login_available": True,
        }

    @application.get("/incidents")
    def list_incidents(request: Request) -> list[dict[str, Any]]:
        store = _tenant_store(request)
        return [_incident_summary(i) for i in store.list_incidents()]

    @application.get("/incidents/{incident_id}")
    def get_incident(incident_id: str, request: Request) -> dict[str, Any]:
        store = _tenant_store(request)
        incident = store.get(incident_id)
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

    @application.post("/demo/upload", response_model=DemoRunResponse)
    async def demo_upload(file: UploadFile) -> DemoRunResponse:
        """Real video ingest: upload a clip → OpenCV decode → CueDetector → ladder.

        Returns 202 immediately with a job id; the CPU-heavy decode+DNN scan
        runs in a worker thread (a 28 MB / 100+ s clip takes minutes on a
        0.5-vCPU Fargate task — far past gateway timeouts — and would block
        the event loop if awaited inline). Poll GET /demo/upload/{job_id} for
        the resulting incident.
        """
        data = await file.read()
        if len(data) > 64 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="clip too large (max 64 MB)")
        suffix = Path(file.filename or "clip.mp4").suffix.lower() or ".mp4"
        if suffix not in {".mp4", ".mov", ".avi", ".m4v", ".webm"}:
            raise HTTPException(status_code=400, detail=f"unsupported type {suffix!r}")

        spilled = save_upload(data, suffix=suffix)
        job_id = uuid4().hex
        _UPLOAD_JOBS[job_id] = {
            "status": "processing",
            "filename": file.filename,
            "incident_id": None,
            "error": None,
        }

        def _process() -> None:
            entry = _UPLOAD_JOBS[job_id]
            try:
                entry["incident_id"] = _run_upload_sync(spilled, application.state.store)
                entry["status"] = "done"
            except HTTPException as exc:
                entry["status"] = "error"
                entry["error"] = exc.detail
            except Exception as exc:  # pragma: no cover - env-dependent
                entry["status"] = "error"
                entry["error"] = f"analysis failed: {exc}"
            finally:
                Path(spilled).unlink(missing_ok=True)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _process)
        return DemoRunResponse(incident_id=job_id)

    @application.get("/demo/upload/{job_id}")
    def upload_job_status(job_id: str) -> dict[str, Any]:
        job = _UPLOAD_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job id")
        return job

    def _run_upload_sync(spilled: Path, store: AuditStore) -> str:
        """CPU-heavy upload analysis (runs in executor thread): decode →
        detectors → ladder. Returns incident id; raises HTTPException on
        undecodable/no-cue input."""
        plan = load_care_plan(_DEMO_PLAN_PATH)
        plan.triggers.no_movement.timeout_sec = 2  # demo clock
        detector = CueDetector.from_plan(plan, zone_id="living_room")
        if _MODEL_PATH.exists():
            from care_ladder.vision.mppersondet import MPPersonDet
            from care_ladder.vision.mppose import MPPose

            detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)
            if _POSE_MODEL_PATH.exists():
                detector.pose_model = MPPose(str(_POSE_MODEL_PATH), confThreshold=0.5)

        # Clip resolution may differ from plan zone canvas; use full-frame zone.
        probe = cv2.VideoCapture(str(spilled))
        ok, first = probe.read()
        probe.release()
        if not ok:
            raise HTTPException(
                status_code=422,
                detail="clip could not be decoded — is it a valid video file?",
            )
        h, w = first.shape[:2]
        detector.zone = np.asarray(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )

        result = ingest_video(spilled, detector, sample_hz=5.0, prefer_distress=True, max_seconds=180.0)
        if result.cue is None and detector.person_detector is not None:
            # DNN found nobody in the whole clip (stylized/low-res footage):
            # fall back to the contour-blob path and re-run once.
            detector.person_detector = None
            detector.pose_model = None
            result = ingest_video(spilled, detector)

        if result.cue is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no cue emitted from clip ({result.frame_count} frames, "
                    f"{result.duration_sec}s) — try a clip with a still person, "
                    "someone leaving frame, or lying on the floor"
                ),
            )

        result.cue.detail = {
            **result.cue.detail,
            # keep the more specific pose label when the pose path fired
            "source": result.cue.detail.get("source", f"uploaded_clip:{result.detector_source}"),
            "clip_frames": result.frame_count,
            "clip_fps": result.fps,
            "clip_duration_sec": result.duration_sec,
        }
        speaker = SpeakerSimulator(scripted=[])
        dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
        incident = asyncio.run(
            run_incident(
                cue=result.cue,
                plan=plan,
                speaker=speaker,
                dialer=dialer,
                pre_event_frames=result.pre_event_frames[-4:],
                store=store,
                privacy_mode="blur",
                now=DEMO_NOW,
            )
        )
        asyncio.run(_publish_cloud(incident))
        return incident.id

    @application.post("/demo/run", response_model=DemoRunResponse)
    async def demo_run(body: DemoRunRequest, request: Request) -> DemoRunResponse:
        store = _tenant_store(request)
        if body.fixture not in SUPPORTED_FIXTURES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown fixture {body.fixture!r}; supported: {sorted(SUPPORTED_FIXTURES)}",
            )
        if body.fixture == "no_movement_ok":
            incident = await _run_no_movement_ok(store)
        elif body.fixture == "no_movement_silence":
            incident = await _run_no_movement_silence(store)
        elif body.fixture == "opencv_stillness":
            incident = await _run_opencv_stillness(store)
        elif body.fixture == "opencv_dnn_person":
            incident = await _run_opencv_dnn_person(store)
        elif body.fixture == "opencv_pose_person":
            incident = await _run_opencv_pose_person(store)
        elif body.fixture == "facility_notify_silence":
            incident = await _run_facility_notify_silence(store)
        else:  # pragma: no cover - guarded by SUPPORTED_FIXTURES
            raise HTTPException(status_code=400, detail="unsupported fixture")
        await _publish_cloud(incident)
        return DemoRunResponse(incident_id=incident.id)

    return application


# Default ASGI app for `uvicorn care_ladder.api.app:app`
app = create_app()
