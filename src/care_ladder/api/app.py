"""FastAPI incident timeline + demo trigger (demo fixtures only; no live camera)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
        "facility_ack_resolved",
        "facility_ack_timeout",
        "facility_negative_reply",
        "facility_positive_reply",
    }
)
_FACILITY_PLAN_PATH = _REPO_ROOT / "configs" / "demo_facility.yaml"
_POSE_MODEL_PATH = _REPO_ROOT / "models" / "pose_estimation_mediapipe_2023mar.onnx"
_MODEL_PATH = _REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"
# Midday UTC so quiet_hours soft-suppress does not hide the judge demo ladder.
DEMO_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


# --- Mockup H facility console state (process-local demo; Postgres rows via
# --- FacilityRepository when DATABASE_URL is configured - Slice 4)
_FACILITY_STATES: dict[str, "FacilityState"] = {}


def _facility_state(tenant_id: str, session_factory=None) -> "FacilityState":
    """Facility console state.

    Postgres-backed persistence when a session factory exists (DATABASE_URL):
    cases + staff survive restarts through FacilityRepository. Falls back to
    the process-local demo state otherwise (auth-off local demos).
    """
    from care_ladder.db.models import StaffRow
    from care_ladder.facility.models import StaffMember
    from care_ladder.facility.service import FacilityState

    state = _FACILITY_STATES.get(tenant_id)
    if state is None:
        state = FacilityState()
        if session_factory is not None:
            state.session_factory = session_factory
            with session_factory() as session:
                from care_ladder.facility.repository import FacilityRepository

                repo = FacilityRepository(session, tenant_id)
                roster = repo.list_staff()
                if not roster:  # fresh DB: seed the demo roster rows
                    seeds = _demo_roster_specs(tenant_id)
                    from datetime import timedelta

                    for spec in seeds:
                        session.add(
                            StaffRow(
                                id=spec["id"], tenant_id=tenant_id,
                                display_name=spec["display_name"], role=spec["role"],
                                initials=spec["initials"], status=spec["status"],
                            )
                        )
                    session.commit()
                    roster = repo.list_staff()
                for m in roster:
                    state.staff[m.id] = m
                for c in repo.list_cases():
                    state.cases[c.id] = c
                state.load_overrides()  # N3: overrides survive restarts
        elif tenant_id == "demo-facility":
            for spec in _demo_roster_specs(tenant_id):
                state.staff[spec["id"]] = StaffMember(
                    id=spec["id"], tenant_id=tenant_id, display_name=spec["display_name"],
                    role=spec["role"], initials=spec["initials"], status=spec["status"],
                )
        _FACILITY_STATES[tenant_id] = state
    return state


def _demo_roster_specs(tenant_id: str) -> list[dict[str, str]]:
    return [
        {"id": "demo-facility-maria", "display_name": "Maria G.", "role": "RN", "initials": "MG", "status": "available"},
        {"id": "demo-facility-alex", "display_name": "Alex R.", "role": "CNA", "initials": "AR", "status": "on_break"},
        {"id": "demo-facility-jamie", "display_name": "Jamie D.", "role": "CNA", "initials": "JD", "status": "available"},
        {"id": "demo-facility-lead", "display_name": "Floor Lead", "role": "Lead", "initials": "FL", "status": "available"},
    ]


def _facility_after_incident(tenant_id: str, incident, fixture: str, session_factory=None) -> None:
    """Mockup H: open cases / record resident-resolved after a facility fixture."""
    from care_ladder.facility.models import Case, Priority

    state = _facility_state(tenant_id, session_factory)
    if fixture == "facility_positive_reply":
        state.resident_resolved.append(
            {
                "incident_id": incident.id,
                "room_label": "204",
                "at": None,
                "reply_class": "positive",
            }
        )
        return
    if fixture == "facility_negative_reply":
        origin, priority = "from_negative_reply", Priority.default_for(incident.cue.kind, "negative")
    else:  # silence path fixtures
        origin, priority = "from_silence", Priority.default_for(incident.cue.kind, "silence")
    case = Case.open_from_incident(
        incident_id=incident.id,
        tenant_id=tenant_id,
        room_label="204",
        origin=origin,
        priority=priority,
        human_id=state.next_human_id(),
    )
    state.open_case(case)


class CheckoutRequest(BaseModel):
    plan: Literal["home", "facility_starter", "facility_growth"]


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


class AckRequest(BaseModel):
    by: str | None = Field(default=None, description="who acknowledged (free text, e.g. 'RN Alex')")
    note: str | None = Field(default=None, description="optional context, e.g. 'at room 12'")


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


async def _run_facility_reply(store: AuditStore, *, negative: bool):
    """Facility reply-classification fixtures (Mockup H section 4.1).

    - facility_negative_reply: resident answers "I need help" -> classified
      negative -> P1, skip wait rungs, page group, open Case.
    - facility_positive_reply: resident answers "I'm fine" -> resolved by
      resident response; no case.
    Classification is pinned by the fixture (fixture override wins).
    """
    from care_ladder.channels.notify import NotifyChannelAdapter

    plan = load_care_plan(_FACILITY_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_negative_reply" if negative else "facility_positive_reply"})
    scripted = ["I need help, I cannot get up"] if negative else ["I'm fine"]
    speaker = SpeakerSimulator(scripted=scripted)
    dialer = StubDialer(behavior={})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        store=store,
        notifier=NotifyChannelAdapter(),
        now=DEMO_NOW,
    )
    # Pin classification into the speaker_prompt event detail (fixture override)
    from care_ladder.facility.classify import classify_reply

    cls = classify_reply(scripted[0], fixture_class="negative" if negative else "positive")
    for e in incident.events:
        if e.tool == "speaker_prompt":
            e.detail = {**e.detail, "reply_class": cls.reply_class, "classify_source": cls.source}
    store.save(incident)
    return incident


async def _run_facility_ack_scenario(store: AuditStore, *, acked: bool):
    """Facility fixtures for the ack loop: page caretakers → wait → resolve or escalate.

    - ``facility_ack_resolved``: a caretaker acknowledges within the (shortened
      demo) window → incident resolves with ``reason: caretaker_ack`` and the
      supervisor/dial rungs never fire.
    - ``facility_ack_timeout``: nobody acknowledges → ladder escalates to
      supervisor page + dial and logs ``ack_timeout`` in the timeline.
    """
    import copy

    from care_ladder.channels.router import PageRouter

    plan = copy.deepcopy(load_care_plan(_FACILITY_PLAN_PATH))
    # Short real ack window so the demo shows the wait without hanging (2s).
    for rung in plan.rungs:
        if rung.tool == "notify_and_await_ack":
            rung.params["ack_timeout_sec"] = 2

    cue = CueEvent(
        kind="no_movement",
        confidence=0.9,
        detail={"fixture": "facility_ack_resolved" if acked else "facility_ack_timeout"},
    )
    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={"caregiver": "answered"})

    incident_id = uuid4().hex
    registry = _app_ack_registry()
    if acked:
        registry.schedule_auto_ack(
            incident_id,
            after_sec=0.5,
            by="Nurse Alex (scripted ack)",
            channel="slack",
            note="heading to common_room",
        )

    return await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        store=store,
        page_router=PageRouter(),
        ack_registry=registry,
        ack_base_url=_public_base_url(),
        max_ack_wait_sec=-1,  # honor the plan's shortened 2s window
        now=DEMO_NOW,
        incident_id=incident_id,
    )


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


def _session_factory_from_env():
    """Shared SQLAlchemy session factory when DATABASE_URL is set (Render Postgres)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    from care_ladder.db.base import create_engine_from_url, make_session_factory
    from care_ladder.db.models import Base

    engine = create_engine_from_url(url)
    Base.metadata.create_all(engine)  # idempotent; bootstrap also does this
    return make_session_factory(engine)


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

# App-level ack registry: shared by demo fixtures (orchestrator wait loop) and
# the /ack + /acks HTTP surface so a caretaker link tap resolves the in-flight
# wait. Reuses SESSION_SECRET when set so tokens stay valid across workers
# that share the secret; otherwise a per-process secret (restart = links die,
# fail-closed, same honesty note as the upload-job map).
_ACK_REGISTRY = None


def _app_ack_registry() -> "AckRegistry":
    global _ACK_REGISTRY
    if _ACK_REGISTRY is None:
        from care_ladder.channels.ack import AckRegistry

        _ACK_REGISTRY = AckRegistry(secret=os.environ.get("SESSION_SECRET") or None)
    return _ACK_REGISTRY


def _public_base_url() -> str:
    """Best-effort public base for ack links.

    PUBLIC_BASE_URL wins, then Render's RENDER_EXTERNAL_URL (set on every
    Render service), so ack links are absolute https on the live deploy.
    """
    return (
        os.environ.get("PUBLIC_BASE_URL", "")
        or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).rstrip("/")


def app_module_registry():
    """Test/diagnostic handle onto the shared ack registry."""
    return _app_ack_registry()

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


def create_app(store: AuditStore | None = None, pg_session_factory=None) -> FastAPI:
    """Build FastAPI app with injectable store (tests inject a fresh memory store).

    ``pg_session_factory`` lets tests inject a shared Postgres/sqlite session
    factory (the production path derives it from DATABASE_URL when no store
    is injected).
    """
    audit = store if store is not None else _default_store()
    application = FastAPI(
        title="Care Ladder",
        description="Incident timeline + demo trigger (reserved phones; emergency fail-closed).",
        version="0.1.0",
    )
    application.state.store = audit
    # Only when the caller did not inject a store: Render/prod uses DATABASE_URL
    # so per-tenant PostgresAuditStore instances share one DB across workers.
    application.state.pg_session_factory = (
        pg_session_factory if pg_session_factory is not None
        else (None if store is not None else _session_factory_from_env())
    )

    static_dir = Path(__file__).resolve().parent / "static"
    application.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")

    # Landing page (Task 9): GET / serves the SaaS landing (pricing + demo
    # login); the caregiver console stays at /ui/.
    from fastapi.responses import FileResponse, HTMLResponse

    from care_ladder.channels.ack import render_ack_page
    from care_ladder.channels.router import channel_active_envs

    @application.get("/", include_in_schema=False)
    def landing() -> FileResponse:
        return FileResponse(static_dir / "landing.html")

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
        """Per-tenant store when auth on.

        Memory mode (no DATABASE_URL): one AuditStore per tenant_id in-process.
        DATABASE_URL set: PostgresAuditStore per tenant sharing one session factory
        so list/get/frames and Render workers see the same incidents.
        """
        session = _require_session(request)
        if session is None:
            return application.state.store
        if not hasattr(application.state, "tenant_stores"):
            application.state.tenant_stores = {}
        stores = application.state.tenant_stores
        existing = stores.get(session.tenant_id)
        if existing is not None:
            return existing
        factory = getattr(application.state, "pg_session_factory", None)
        if factory is not None:
            from care_ladder.audit.postgres_store import PostgresAuditStore

            stores[session.tenant_id] = PostgresAuditStore(factory, session.tenant_id)
        else:
            stores[session.tenant_id] = AuditStore()
        return stores[session.tenant_id]

    # ---- billing (Task 8) ---------------------------------------------------
    _BILLING_TENANTS: dict[str, dict[str, Any]] = {
        "demo-home": {"mode": "home", "plan": "home", "status": "active"},
        "demo-facility": {"mode": "facility", "plan": "demo", "status": "demo"},
    }
    application.state.billing_tenants = _BILLING_TENANTS

    def _tenant_record(request: Request) -> dict[str, Any] | None:
        """Best-available tenant record for gating/portal.

        Postgres row when DATABASE_URL is set (authoritative after webhook
        writes), else the in-memory billing table seeded for the demo tenants.
        """
        session = _require_session(request)
        if session is None:
            return None
        factory = getattr(application.state, "pg_session_factory", None)
        if factory is not None:
            try:
                from care_ladder.db.models import Tenant as TenantRow

                with factory() as s:
                    row = s.get(TenantRow, session.tenant_id)
                    if row is not None:
                        return {
                            "mode": row.mode,
                            "plan": row.plan,
                            "status": row.subscription_status,
                            "stripe_customer_id": getattr(row, "stripe_customer_id", None),
                        }
            except Exception:
                pass  # fall through to the in-memory table
        return _BILLING_TENANTS.get(session.tenant_id)

    @application.post("/billing/checkout")
    def billing_checkout(body: CheckoutRequest, request: Request):
        from care_ladder.billing.stripe_checkout import (
            BillingError,
            create_checkout_url,
            resolve_checkout_base_url,
        )

        session = _require_session(request)
        if session is None and _auth_on():
            raise HTTPException(status_code=401, detail="authentication required")
        tenant_id = session.tenant_id if session is not None else "demo-facility"
        try:
            url = create_checkout_url(
                body.plan,
                tenant_id=tenant_id,
                base_url=resolve_checkout_base_url(request),
            )
        except BillingError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return {"url": url}

    @application.get("/billing/stub-success")
    def billing_stub_success(plan: Literal["home", "facility_starter", "facility_growth"], tenant: str = "demo-facility"):
        from care_ladder.billing.stripe_checkout import _env as env_name

        if env_name() != "demo":
            raise HTTPException(status_code=403, detail="stub checkout is demo-only")
        t = application.state.billing_tenants.setdefault(
            tenant, {"mode": "facility", "plan": "demo", "status": "demo"}
        )
        t["plan"] = plan
        t["status"] = "active"
        return {"ok": True, "plan": plan, "note": "demo stub checkout; no card was charged"}

    @application.get("/billing/success")
    def billing_success(session_id: str = ""):
        return {
            "ok": True,
            "session_id": session_id,
            "note": "checkout completed; plan activates via signed webhook",
        }

    @application.get("/billing/cancel")
    def billing_cancel():
        return {"ok": False, "note": "checkout canceled; no charge"}

    @application.post("/billing/portal")
    def billing_portal(request: Request):
        """Stripe Customer Portal session for the logged-in tenant.

        Requires a persisted stripe_customer_id (set by the verified webhook);
        without one or without STRIPE_SECRET_KEY this is an honest 503 - never
        a fabricated portal URL.
        """
        import os

        key = os.environ.get("STRIPE_SECRET_KEY", "")
        record = _tenant_record(request)
        customer = (record or {}).get("stripe_customer_id") or ""
        if not key or not customer:
            raise HTTPException(
                status_code=503,
                detail="portal unavailable: no stripe customer on file "
                "for this tenant (complete a checkout first)",
            )
        import stripe

        stripe.api_key = key
        from care_ladder.billing.stripe_checkout import resolve_checkout_base_url

        origin = resolve_checkout_base_url(request)
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer, return_url=f"{origin}/billing/success"
            )
        except stripe.StripeError as exc:
            raise HTTPException(status_code=503, detail="portal unavailable") from exc
        return {"url": session.url}

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
        # F1: persist plan/status to Postgres (authoritative tenant record)
        if result.get("applied"):
            factory = getattr(application.state, "pg_session_factory", None)
            if factory is not None:
                try:
                    from care_ladder.db.models import Tenant as TenantRow

                    tid = result["tenant_id"]
                    with factory() as dbs:
                        row = dbs.get(TenantRow, tid)
                        if row is not None:
                            row.plan = result.get("plan") or row.plan
                            row.subscription_status = result.get("status") or row.subscription_status
                            dbs.commit()
                except Exception:
                    pass  # memory table already updated; PG write is best-effort mirror

        # persist stripe customer for later portal sessions (memory table;
        # Postgres tenants get it from the Subscription row in _tenant_record)
        obj = (event.get("data") or {}).get("object") or {}
        cust = obj.get("customer")
        meta = obj.get("metadata") or {}
        tid = meta.get("tenant_id") or ""
        if cust and tid:
            if tid in application.state.billing_tenants:
                application.state.billing_tenants[tid]["stripe_customer_id"] = cust
            factory = getattr(application.state, "pg_session_factory", None)
            if factory is not None:
                try:
                    from care_ladder.db.models import Tenant as TenantRow

                    with factory() as s:
                        row = s.get(TenantRow, tid)
                        if row is not None:
                            row.stripe_customer_id = cust
                            s.commit()
                except Exception:
                    pass  # best-effort; memory record already updated
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
            "ack_channels_active": channel_active_envs(),
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
    def get_incident_frame(incident_id: str, index: int, request: Request):
        """Serve a privacy-transformed pre-event frame as PNG.

        Frames reaching this endpoint already went through blur/silhouette in
        run_incident; raw identifiable pixels never enter the store.
        """
        incident = _tenant_store(request).get(incident_id)
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
    def list_incident_frames(incident_id: str, request: Request) -> dict[str, Any]:
        incident = _tenant_store(request).get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        return {
            "privacy": incident.privacy,
            "count": len(frames),
            "frame_urls": [f"/incidents/{incident_id}/frames/{i}" for i in range(len(frames))],
        }

    # ---- caretaker acknowledgments (capability-token surface) ----------------
    #
    # /acks/{token} endpoints are intentionally unauthenticated: the signed,
    # single-use, expiring token IS the authorization (caretakers arrive from
    # Slack/Teams/WhatsApp/Telegram links without a console session). The
    # console's own Acknowledge button uses the same tokens via /acks/pending.

    @application.get("/acks/pending")
    def acks_pending(request: Request) -> list[dict[str, Any]]:
        """Live pending ack windows (console panel; session + tenant scoped)."""
        session = _require_session(request)
        if session is None and _auth_on():
            raise HTTPException(status_code=401, detail="authentication required")
        tenant_id = session.tenant_id if session is not None else None
        return _app_ack_registry().pending_list(tenant_id)

    @application.post("/acks/{token}")
    def ack_submit(token: str, body: AckRequest | None = None):
        registry = _app_ack_registry()
        outcome, reason = registry.acknowledge(
            token,
            by=(body.by if body and body.by else None),
            note=(body.note if body and body.note else None),
            channel="web",
        )
        if outcome is None:
            detail = {
                "token expired": "ack window closed",
                "already acknowledged": "already acknowledged",
            }.get(reason, "invalid acknowledgment token")
            raise HTTPException(status_code=410, detail=detail)
        # Late-ack courtesy: if the incident is still open somewhere (wait
        # raced out), the timeline still records the attempt.
        return outcome.summary()

    @application.get("/ack/{token}", response_class=HTMLResponse)
    def ack_page(token: str):
        """Mobile one-tap ack page linked from IM pages."""
        registry = _app_ack_registry()
        pending = registry.peek(token)
        note = ""
        if pending is None:
            # already acked / expired / closed → still render a honest page
            note = "This link was already used, expired, or the window closed."
        return HTMLResponse(render_ack_page(pending, status_note=note))

    @application.post("/demo/upload", response_model=DemoRunResponse)
    async def demo_upload(file: UploadFile, request: Request) -> DemoRunResponse:
        """Real video ingest: upload a clip → OpenCV decode → CueDetector → ladder.

        Returns 202 immediately with a job id; the CPU-heavy decode+DNN scan
        runs in a worker thread (a 28 MB / 100+ s clip takes minutes on a
        0.5-vCPU Fargate task — far past gateway timeouts — and would block
        the event loop if awaited inline). Poll GET /demo/upload/{job_id} for
        the resulting incident.
        """
        session = _require_session(request)
        if session is None and _auth_on():
            raise HTTPException(status_code=401, detail="authentication required")
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
                store = _tenant_store(request) if _auth_on() else application.state.store
                entry["incident_id"] = _run_upload_sync(spilled, store)
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
        elif body.fixture in (
            "facility_notify_silence",
            "facility_ack_resolved",
            "facility_ack_timeout",
            "facility_negative_reply",
            "facility_positive_reply",
        ):
            from care_ladder.billing.plans import tenant_can_use_notify

            record = _tenant_record(request)
            if record is not None and not tenant_can_use_notify(record):
                raise HTTPException(
                    status_code=403,
                    detail="facility notify requires an active facility plan "
                    "(Facility Starter or Growth); upgrade from the landing page",
                )
            if body.fixture == "facility_notify_silence":
                incident = await _run_facility_notify_silence(store)
            elif body.fixture in ("facility_negative_reply", "facility_positive_reply"):
                incident = await _run_facility_reply(store, negative=body.fixture == "facility_negative_reply")
            else:
                incident = await _run_facility_ack_scenario(store, acked=body.fixture == "facility_ack_resolved")
        else:  # pragma: no cover - guarded by SUPPORTED_FIXTURES
            raise HTTPException(status_code=400, detail="unsupported fixture")
        await _publish_cloud(incident)
        if body.fixture.startswith("facility_"):
            record = _tenant_record(request)
            if record is not None and record.get("mode") == "facility":
                record_tenant = record.get("tenant_id")
                tenant_id = record_tenant or (session.tenant_id if (session := _require_session(request)) else "demo-facility")
                _facility_after_incident(
                    tenant_id, incident, body.fixture,
                    session_factory=getattr(request.app.state, "pg_session_factory", None),
                )
        return DemoRunResponse(incident_id=incident.id)

    # ---- facility console API (Mockup H) ------------------------------------

    def _facility_ctx(request: Request):
        """401 anon; 403 home tenants; else (tenant_id, state, store)."""
        session = _require_session(request)
        if session is None and _auth_on():
            raise HTTPException(status_code=401, detail="authentication required")
        record = _tenant_record(request)
        if record is not None and record.get("mode") != "facility":
            raise HTTPException(status_code=403, detail="facility console requires a facility tenant")
        tenant_id = session.tenant_id if session is not None else "demo-facility"
        state = _facility_state(tenant_id, getattr(request.app.state, "pg_session_factory", None))
        store = _tenant_store(request) if _auth_on() else application.state.store
        return tenant_id, state, store

    def _case_out(c) -> dict:
        return {
            "id": c.id, "human_id": c.human_id, "incident_id": c.incident_id,
            "room_label": c.room_label, "title": c.title, "origin": c.origin,
            "priority": c.priority, "state": c.state, "owner_staff_id": c.owner_staff_id,
            "slack_thread_url": c.slack_thread_url, "ack_at": c.ack_at.isoformat() if c.ack_at else None,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "documentation": c.documentation,
        }

    @application.get("/facility/alerts")
    def facility_alerts(request: Request):
        tenant_id, state, store = _facility_ctx(request)
        # quiet hours from the facility plan YAML (display-only chip, S4)
        quiet = None
        try:
            plan = load_care_plan(_FACILITY_PLAN_PATH)
            qh = getattr(plan, "quiet_hours", None)
            if qh:
                quiet = {
                    "start": getattr(qh, "start", None),
                    "end": getattr(qh, "end", None),
                    "policy": getattr(qh, "policy", None),
                }
        except Exception:
            quiet = None
        # Resident-resolved derives from persisted incidents (survives restarts):
        # positive reply fixtures resolve with reply_class positive in the event detail.
        try:
            resolved_incidents = [
                i for i in store.list_incidents()
                if i.status == "resolved"
                and any(
                    e.tool == "speaker_prompt" and e.detail.get("reply_class") == "positive"
                    for e in i.events
                )
            ]
            state.resident_resolved = [
                {
                    "incident_id": i.id,
                    "room_label": "204",
                    "reply_class": "positive",
                }
                for i in resolved_incidents
            ]
        except Exception:
            pass
        queue = []
        for c in sorted(
            [c for c in state.cases.values() if c.state != "closed"],
            key=lambda c: (c.priority, c.human_id),
        ):
            inc = store.get(c.incident_id)
            queue.append(
                {
                    "incident_id": c.incident_id,
                    "case": _case_out(c),
                    "priority": c.priority,
                    "room_label": c.room_label,
                    "origin": c.origin,
                    "title": c.title,
                    "chips": [
                        chip
                        for chip, on in (
                            ("Negative response", c.origin == "from_negative_reply"),
                            ("Ladder jumped", inc is not None and any(e.tool == "jump" for e in inc.events)),
                            ("Assigned", c.owner_staff_id is not None),
                        )
                        if on
                    ],
                }
            )
        return {
            "queue": queue,
            "resident_resolved": state.resident_resolved,
            "quiet_hours": quiet,
        }

    @application.get("/facility/alerts/{incident_id}")
    def facility_alert_detail(incident_id: str, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        case = next((c for c in state.cases.values() if c.incident_id == incident_id), None)
        inc = store.get(incident_id)
        if case is None and inc is None:
            raise HTTPException(status_code=404, detail="alert not found")
        reply = None
        if inc is not None:
            for e in inc.events:
                if e.tool == "speaker_prompt":
                    reply = e.detail.get("reply_class")
        return {
            "incident_id": incident_id,
            "case": _case_out(case) if case else None,
            "reply_class": reply,
            "rungs": [e.tool for e in inc.events] if inc else [],
            "assign_candidates": [
                {"id": m.id, "display_name": m.display_name, "role": m.role, "initials": m.initials,
                 "status": m.status, "assignable": m.assignable()}
                for m in state.roster()
            ],
        }

    @application.post("/facility/alerts/{incident_id}/priority")
    def facility_priority(incident_id: str, body: dict, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        case = next((c for c in state.cases.values() if c.incident_id == incident_id), None)
        if case is None:
            raise HTTPException(status_code=404, detail="alert not found")
        priority = body.get("priority")
        if priority not in ("P1", "P2", "P3"):
            raise HTTPException(status_code=422, detail="priority must be P1|P2|P3")
        case.priority = priority
        state.log_override("priority_override", case.id)
        return {"ok": True, "priority": case.priority}

    @application.post("/facility/alerts/{incident_id}/assign")
    def facility_assign(incident_id: str, body: dict, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        case = next((c for c in state.cases.values() if c.incident_id == incident_id), None)
        if case is None:
            raise HTTPException(status_code=404, detail="alert not found")
        result = state.assign(case.id, body.get("staff_id", ""), pull_off_break=bool(body.get("pull_off_break")))
        if result is None:
            raise HTTPException(status_code=409, detail="staff member is on break; use pull_off_break to override")
        return {"ok": True, "case": _case_out(result[0])}

    @application.post("/facility/alerts/{incident_id}/override")
    def facility_override(incident_id: str, body: dict, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        case = next((c for c in state.cases.values() if c.incident_id == incident_id), None)
        if case is None:
            raise HTTPException(status_code=404, detail="alert not found")
        action = body.get("action")
        if action not in ("escalate", "deescalate", "suppress", "repage", "pull_off_break"):
            raise HTTPException(status_code=422, detail="unsupported override action")
        if action == "escalate" and case.priority != "P1":
            order = ["P3", "P2", "P1"]
            case.priority = order[min(order.index(case.priority) + 1, 2)]
        if action == "deescalate" and case.priority != "P3":
            order = ["P1", "P2", "P3"]
            case.priority = order[min(order.index(case.priority) + 1, 2)]
        if action == "repage":
            case.state = "paged"
        state.log_override(action, case.id)
        return {"ok": True, "priority": case.priority, "state": case.state}

    @application.get("/facility/cases")
    def facility_cases(request: Request):
        tenant_id, state, store = _facility_ctx(request)
        return {
            "open": [_case_out(c) for c in state.cases.values() if c.state != "closed"],
            "closed_today": [_case_out(c) for c in state.cases.values() if c.state == "closed"],
        }

    @application.post("/facility/cases/{case_id}/ack")
    def facility_case_ack(case_id: str, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        c = state.ack_case(case_id)
        if c is None:
            raise HTTPException(status_code=404, detail="case not found")
        return {"ok": True, "case": _case_out(c)}

    @application.post("/facility/cases/{case_id}/close")
    def facility_case_close(case_id: str, body: dict, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        c = state.close_case(case_id, body.get("documentation", ""))
        if c is None:
            raise HTTPException(status_code=422, detail="documentation required (min 20 chars)")
        return {"ok": True, "case": _case_out(c)}

    @application.get("/facility/staff")
    def facility_staff(request: Request):
        tenant_id, state, store = _facility_ctx(request)
        return {
            "staff": [
                {"id": m.id, "display_name": m.display_name, "role": m.role, "initials": m.initials,
                 "status": m.status, "break_until": m.break_until.isoformat() if m.break_until else None,
                 "active_case_id": m.active_case_id}
                for m in state.roster()
            ]
        }

    @application.post("/facility/staff/{staff_id}/break")
    def facility_staff_break(staff_id: str, body: dict, request: Request):
        tenant_id, state, store = _facility_ctx(request)
        m = state.set_break(staff_id, bool(body.get("on_break")), int(body.get("minutes", 30)))
        if m is None:
            raise HTTPException(status_code=404, detail="staff not found")
        return {"ok": True, "status": m.status}

    @application.get("/facility/audit/summary")
    def facility_audit(request: Request):
        tenant_id, state, store = _facility_ctx(request)
        return state.summary()

    @application.get("/facility/audit/export.csv")
    def facility_audit_csv(request: Request):
        import csv
        import io as _io

        tenant_id, state, store = _facility_ctx(request)
        buf = _io.StringIO()
        w = csv.writer(buf)
        def _sanitize(value: str) -> str:
            # CSV formula injection: prefix dangerous leading chars (OWASP)
            v = (value or "").replace("\n", " ").replace("\r", " ")
            if v.startswith(("=", "+", "-", "@", "\t")):
                return "'" + v
            return v

        w.writerow(
            ["case_id", "human_id", "incident_id", "room_label", "origin",
             "priority", "state", "owner_staff_id", "opened", "closed",
             "documentation"]
        )
        opened_times = state.case_opened_times()
        for c in state.cases.values():
            w.writerow(
                [c.id, c.human_id, c.incident_id, c.room_label, c.origin,
                 c.priority, c.state, c.owner_staff_id or "",
                 opened_times.get(c.id, ""),
                 c.closed_at.isoformat() if c.closed_at else "",
                 _sanitize(c.documentation or "")]
            )
        from fastapi.responses import Response

        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=facility-audit.csv"},
        )

    return application


# Default ASGI app for `uvicorn care_ladder.api.app:app`
app = create_app()
