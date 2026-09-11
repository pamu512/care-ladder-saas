# Care Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a demoable Agentic Vision care ladder: OpenCV 5 cues for senior/recovery monitoring drive a configurable confirm → Nest/Alexa-style check-in → dial escalation workflow on AWS-friendly Python services, with privacy blur, pre-event clips, and an incident timeline.

**Architecture:** A `vision` worker analyzes frames with OpenCV 5 and emits structured cues. A `ladder` orchestrator loads a YAML care plan and runs rungs (`reperceive`, `speaker_prompt`, `wait`, `dial_contact`, `emergency`). An `audit` store + FastAPI caregiver UI show the incident timeline. Telephony and smart-speaker channels are stubbed for demo (reserved phones); live dials stay secret-gated later.

**Tech Stack:** Python 3.12+, OpenCV 5 (`opencv-python`), pydantic v2, PyYAML, FastAPI, uvicorn, pytest, httpx; local filesystem for clips; AWS deploy (ECS/S3/EventBridge) in a later task.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-11-agentic-senior-care-ladder-design.md`
- Award path: Agentic Vision — OpenCV output must change the next tool/rung (prove with audit trace)
- Spoken check-in copy: `Are you okay? Do you want me to call <Caregiver>?`
- Privacy default: blur/mosaic or silhouette before any persisted/cloud frame
- Emergency rung: `enabled: false` by default (fail-closed)
- Demo phones: reserved fiction only (`+1212555010x` / Ofcom as needed); never real 911 in tests
- No medical/accuracy marketing claims in UI copy
- TDD: failing test → implement → pass → commit per task
- Nest/Alexa for v1 hackathon: **SpeakerSimulator** UI/API (real device skill is post-demo stretch)

## File map (create)

```
care_ladder/
  pyproject.toml
  README.md
  configs/demo_home.yaml
  src/care_ladder/
    __init__.py
    models.py              # Cue, CarePlan, Rung, AuditEvent, Incident
    plan_loader.py
    privacy.py             # blur / silhouette
    clip_buffer.py         # rolling pre-event buffer
    vision/cues.py         # OpenCV cue detection
    vision/reperceive.py
    channels/speaker.py    # SpeakerSimulator (+ protocol for Nest later)
    channels/dial.py       # stub dial + no-answer
    ladder/orchestrator.py
    audit/store.py
    api/app.py             # FastAPI timeline + demo controls
  tests/
    test_plan_loader.py
    test_privacy.py
    test_clip_buffer.py
    test_cues.py
    test_speaker.py
    test_dial.py
    test_orchestrator.py
    test_api_timeline.py
    fixtures/              # synthetic frames / tiny mp4s generated in tests
```

---

### Task 1: Scaffold + care-plan loader

**Files:**
- Create: `pyproject.toml`, `src/care_ladder/__init__.py`, `src/care_ladder/models.py`, `src/care_ladder/plan_loader.py`, `configs/demo_home.yaml`, `tests/test_plan_loader.py`, `README.md`

**Interfaces:**
- Consumes: nothing
- Produces: `load_care_plan(path: Path) -> CarePlan` with pydantic models `CarePlan`, `TriggerConfig`, `Rung`, `Contact`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_loader.py
from pathlib import Path
from care_ladder.plan_loader import load_care_plan

def test_loads_demo_home_and_keeps_emergency_disabled():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    assert plan.caregiver.display_name == "Alex"
    assert plan.caregiver.phone_e164.startswith("+121255501")
    assert plan.triggers.no_movement.timeout_sec == 900
    assert plan.rungs[0].tool == "reperceive"
    ask = next(r for r in plan.rungs if r.tool == "speaker_prompt")
    assert "Are you okay?" in ask.params["text"]
    assert "Alex" in ask.params["text"]
    emergency = next(r for r in plan.rungs if r.tool == "emergency")
    assert emergency.params.get("enabled") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /path/to/opencv-care-ladder && pytest tests/test_plan_loader.py -v`  
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

`models.py`: pydantic `Contact`, `NoMovementTrigger`, `Triggers`, `Rung`, `CarePlan`.  
`plan_loader.py`: YAML load → `CarePlan.model_validate`.  
`configs/demo_home.yaml`: match spec sample (reserved `+12125550101`, prompt with Alex, emergency enabled false).  
`pyproject.toml`: package `care_ladder`, deps `pydantic`, `pyyaml`, `opencv-python`, `fastapi`, `uvicorn`, `pytest`, `httpx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plan_loader.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md configs src/care_ladder tests/test_plan_loader.py
git commit -m "feat: care plan models and demo_home loader"
```

---

### Task 2: Privacy blur / silhouette

**Files:**
- Create: `src/care_ladder/privacy.py`, `tests/test_privacy.py`

**Interfaces:**
- Consumes: BGR `numpy.ndarray` frames
- Produces: `blur_faces(frame) -> ndarray`, `to_silhouette(frame) -> ndarray` (grayscale person mask visualization)

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from care_ladder.privacy import blur_faces, to_silhouette

def test_blur_faces_changes_pixels_on_synthetic_skin_blob():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[40:80, 60:100] = (180, 150, 120)  # blob
    out = blur_faces(frame)
    assert out.shape == frame.shape
    assert not np.array_equal(out[40:80, 60:100], frame[40:80, 60:100])

def test_silhouette_is_single_channel_or_3_but_not_full_color_photo():
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    frame[10:50, 20:60] = 255
    sil = to_silhouette(frame)
    assert sil.ndim in (2, 3)
    # must not preserve the bright white rectangle as-is in all channels identically to input RGB photo semantics
    assert sil.dtype == np.uint8
```

- [ ] **Step 2: Run test to verify it fails**  
Run: `pytest tests/test_privacy.py -v` → FAIL

- [ ] **Step 3: Write minimal implementation**  
Use OpenCV: Haar or simple skin/threshold + `GaussianBlur` ROI for `blur_faces`; threshold + `findContours` fill for `to_silhouette`. Prefer OpenCV 5 APIs available in `opencv-python`.

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit** `feat: privacy blur and silhouette helpers`

---

### Task 3: Pre-event clip buffer

**Files:**
- Create: `src/care_ladder/clip_buffer.py`, `tests/test_clip_buffer.py`

**Interfaces:**
- Consumes: frames + timestamps
- Produces: `ClipBuffer(seconds: float)`, `.push(frame, t)`, `.snapshot() -> list[ndarray]` covering the last N seconds

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from care_ladder.clip_buffer import ClipBuffer

def test_buffer_keeps_only_last_window():
    buf = ClipBuffer(seconds=2.0)
    for i in range(10):
        buf.push(np.full((4, 4, 3), i, dtype=np.uint8), t=float(i))
    snap = buf.snapshot(now=9.0)
    assert len(snap) >= 2
    # oldest kept frame should be at t>=7.0
    assert all(f[0, 0, 0] >= 7 for f in snap)
```

- [ ] **Step 2–5:** fail → implement deque of `(t, frame)` → pass → commit `feat: rolling pre-event clip buffer`

---

### Task 4: OpenCV cue detection (`no_movement`, `no_visibility`, distress heuristic)

**Files:**
- Create: `src/care_ladder/vision/cues.py`, `src/care_ladder/vision/__init__.py`, `tests/test_cues.py`

**Interfaces:**
- Consumes: sequence of frames + `CarePlan.triggers` + zone polygon
- Produces: `CueEvent(kind: Literal['no_movement','no_visibility','distress_heuristic'], confidence: float, detail: dict)` or `None`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from care_ladder.vision.cues import CueDetector

def _blank(w=160, h=120):
    return np.zeros((h, w, 3), dtype=np.uint8)

def test_no_movement_after_timeout_with_static_person_blob():
    det = CueDetector(no_movement_timeout_sec=3.0, zone=((0, 0), (160, 0), (160, 120), (0, 120)))
    frame = _blank()
    frame[40:80, 60:100] = 200
    assert det.observe(frame, t=0.0) is None
    assert det.observe(frame, t=1.0) is None
    cue = det.observe(frame, t=3.5)
    assert cue is not None
    assert cue.kind == "no_movement"

def test_no_visibility_when_blob_leaves_zone():
    det = CueDetector(no_movement_timeout_sec=99.0, zone=((0, 0), (80, 0), (80, 120), (0, 120)))
    left = _blank(); left[40:80, 20:60] = 200
    right = _blank(); right[40:80, 100:140] = 200
    det.observe(left, t=0.0)
    cue = det.observe(right, t=1.0)
    assert cue is not None
    assert cue.kind == "no_visibility"
```

- [ ] **Step 2–5:** fail → motion/presence via frame diff + contour centroid vs polygon (`cv2.pointPolygonTest`) → pass → commit `feat: OpenCV cue detector for stillness and visibility`

Add a third test for `distress_heuristic` using a wide low blob (on-floor stand-in) sustained across frames; implement a simple aspect-ratio / y-position heuristic labeled as non-clinical.

---

### Task 5: Speaker simulator (two-way check-in)

**Files:**
- Create: `src/care_ladder/channels/speaker.py`, `tests/test_speaker.py`

**Interfaces:**
- Produces: `SpeakerChannel` protocol with `async def prompt(text: str, wait_sec: float) -> SpeakerReply`  
- `SpeakerReply(kind: Literal['ok','call_caregiver','silence'], raw: str)`  
- `SpeakerSimulator` with injectable reply queue for tests; default timeout → `silence`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from care_ladder.channels.speaker import SpeakerSimulator

def test_simulator_returns_ok_when_queued():
    sim = SpeakerSimulator(scripted=["I'm fine"])
    reply = asyncio.get_event_loop().run_until_complete(
        sim.prompt("Are you okay? Do you want me to call Alex?", wait_sec=1)
    )
    assert reply.kind == "ok"

def test_simulator_silence_on_timeout():
    sim = SpeakerSimulator(scripted=[])
    reply = asyncio.get_event_loop().run_until_complete(
        sim.prompt("Are you okay? Do you want me to call Alex?", wait_sec=0.05)
    )
    assert reply.kind == "silence"
```

Map phrases: contains fine/ok/yes I'm → `ok`; contains call/yes call → `call_caregiver`; else after wait → `silence`.

- [ ] **Step 2–5:** fail → implement → pass → commit `feat: speaker simulator for Nest/Alexa-style check-in`

---

### Task 6: Dial stub + no-answer escalation helper

**Files:**
- Create: `src/care_ladder/channels/dial.py`, `tests/test_dial.py`

**Interfaces:**
- Produces: `DialResult(status: Literal['answered','no_answer','skipped'], contact_id: str)`  
- `StubDialer.dial(contact, ring_sec) -> DialResult`  
- `next_rung_after_no_answer(plan, current_index) -> int | None`

- [ ] **Step 1: Write the failing test**

```python
from care_ladder.channels.dial import StubDialer, next_rung_after_no_answer
from care_ladder.plan_loader import load_care_plan
from pathlib import Path

def test_stub_no_answer_then_escalate_index():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    assert dialer.dial(plan.caregiver, ring_sec=1).status == "no_answer"
    idx = next(i for i, r in enumerate(plan.rungs) if r.tool == "dial_contact" and r.params.get("contact") == "caregiver")
    nxt = next_rung_after_no_answer(plan, idx)
    assert plan.rungs[nxt].params.get("contact") in {"secondary", "caregiver"} or plan.rungs[nxt].tool in {"dial_contact", "emergency"}
```

Ensure emergency is never selected when `enabled: false`.

- [ ] **Step 2–5:** fail → implement → pass → commit `feat: stub dialer and no-answer escalation`

---

### Task 7: Ladder orchestrator (agentic loop + audit)

**Files:**
- Create: `src/care_ladder/ladder/orchestrator.py`, `src/care_ladder/audit/store.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `CarePlan`, `CueEvent`, `SpeakerChannel`, `StubDialer`, `ClipBuffer`
- Produces: `run_incident(cue, plan, ...) -> Incident` with ordered `AuditEvent`s proving cue → rung tools

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.channels.dial import StubDialer
from pathlib import Path

def test_silence_escalates_to_dial_and_writes_trace():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.get_event_loop().run_until_complete(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"}),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" in tools
    assert incident.events[0].cue_kind == "no_movement"
```

- [ ] **Step 2–5:** implement rung loop: on `ok` resolve; on `call_caregiver` jump to dial primary; on silence continue; skip emergency if disabled → commit `feat: care ladder orchestrator with audit trail`

---

### Task 8: FastAPI incident timeline + demo trigger

**Files:**
- Create: `src/care_ladder/api/app.py`, `tests/test_api_timeline.py`

**Interfaces:**
- `GET /incidents/{id}` → timeline JSON  
- `GET /incidents` → list  
- `POST /demo/run` with `{fixture: "no_movement_silence"}` runs orchestrator and returns incident id

- [ ] **Step 1: Write the failing test** using `TestClient`  
Assert timeline includes ordered steps and prompt text contains caregiver name.

- [ ] **Step 2–5:** implement in-memory `AuditStore` → pass → commit `feat: FastAPI incident timeline and demo run`

---

### Task 9: End-to-end demo path + README

**Files:**
- Modify: `README.md`  
- Create: `scripts/run_demo.sh`, optional `tests/test_e2e_demo.py`

- [ ] Wire `uvicorn care_ladder.api.app:app`  
- [ ] Document: how OpenCV cue changes rungs; privacy; reserved phones; how to show timeline for judges  
- [ ] One e2e test: demo fixture → incident has ≥3 audit events  
- [ ] Commit `docs: demo runbook for OpenCV Agentic Vision submission`

---

### Task 10: AWS deploy sketch (minimal meaningful AWS)

**Files:**
- Create: `infra/README.md`, `infra/ecs-task-outline.md` (or CDK/terraform light)  
- Optional: Dockerfile for vision+API

- [ ] Document S3 clip upload (blurred only), ECS/Fargate service, EventBridge cue bus  
- [ ] Dockerfile builds runnable API  
- [ ] Commit `chore: AWS deployment outline for OpenCV/AWS requirement`

Do **not** block demo on live AWS if local FastAPI works; judges need a working endpoint or screen-share — prefer deploy if credentials available.

---

## Spec coverage checklist

| Spec item | Task |
| --- | --- |
| OpenCV cues no_movement / no_visibility / distress | Task 4 |
| Configurable YAML ladder | Task 1, 7 |
| Nest/Alexa-style prompt copy + two-way | Task 5 |
| No-answer escalation | Task 6–7 |
| Privacy blur/silhouette | Task 2 |
| Pre-event clip | Task 3, 7 |
| Incident timeline UI/API | Task 8 |
| Emergency fail-closed | Task 1, 6–7 |
| AWS meaningful component | Task 10 |
| Agentic Vision trace | Task 7–8 |

## Placeholder scan

None intentional. Speaker real-device integration deferred explicitly to simulator in Global Constraints.
