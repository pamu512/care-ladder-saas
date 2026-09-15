# Care Ladder — Technical Report

**OpenCV AI Competition 2026, powered by AWS** · Agentic Vision path · Team: Care Ladder (Anoop Pamu)

## 1. What it is

Care Ladder is a remote wellness monitor for seniors and recovering people. OpenCV 5
perception emits structured cues (`no_movement`, `no_visibility`, `distress_heuristic`);
an agent walks a **configurable YAML escalation ladder** — re-perceive → smart-speaker
check-in → wait → dial primary → dial secondary → gated emergency — with **every step,
skip, and jump written to an audit trail** surfaced as a caregiver incident timeline.

**Core claim (Agentic Vision bar):** vision output *changes what the system does next*.
The same `no_movement` cue resolves with no dial when the person answers "I'm fine"
(Path A) and escalates through two dial rungs on silence (Path B). A chatbot that
explains a fixed result this is not.

**What it is not:** no clinical or accuracy claims, no real telephony (stub dialer,
reserved NANP fiction numbers), no live camera on the demo path. Failure modes are
documented in [`failure-modes.md`](failure-modes.md).

## 2. OpenCV 5 usage (substantive image/video analysis)

| Component | OpenCV 5 modules | Role |
| --- | --- | --- |
| Person detection | `cv.dnn.readNet` + MediaPipe person-detector ONNX (OpenCV Zoo), `cv.dnn.NMSBoxes`, `cv.resize`, `cv.copyMakeBorder` | Real person localization on frames; three OpenCV 5 portability fixes were required (below) |
| Presence / zones | `findContours`, `contourArea`, `moments`, `boundingRect`, `pointPolygonTest`, `THRESH_OTSU` | Otsu adaptive segmentation + contour blobs vs plan-zone polygons |
| Motion | `createBackgroundSubtractorMOG2`, `absdiff` | MOG2 foreground ratio (robust to illumination drift) with frame-diff fallback |
| Morphology | `morphologyEx` (OPEN/CLOSE), `getStructuringElement(MORPH_ELLIPSE)` | Mask cleanup for privacy + blob paths |
| Privacy | `inRange` (YCrCb skin + HSV chroma), `GaussianBlur`, `drawContours(FILLED)` | Face/person blur and silhouette transforms applied **before** any frame is persisted or served |
| Encoding | `imencode` (PNG) | Privacy-transformed pre-event frames to the caregiver console |

**OpenCV 5 portability findings** (vendored wrapper: `src/care_ladder/vision/mppersondet.py`,
adapted from OpenCV Zoo's Apache-2.0 `mp_persondet.py`):
1. `Net.getInputs()` no longer exists in OpenCV 5 — input size must be known (224×224).
2. The new DNN graph engine returns the two output blobs in swapped order vs the 4.x
   wrapper; detected by trailing dimension (scores=1, deltas=12).
3. `NMSBoxes` returns a flattened index array — reshape before fancy-indexing.

## 3. Agentic workflow (perception → decision → action)

```
frames ──▶ CueDetector ──▶ CueEvent ──▶ run_incident (orchestrator)
             │  DNN person box / contour blob         │
             │  MOG2 motion                            ├─ rung 1: reperceive (re-check)
             │  zone polygon test                      ├─ rung 2: speaker_prompt ── "ok" ─▶ resolve
             │                                         │            └ "call_caregiver" ─▶ jump to dial
             │                                         ├─ rung 3: wait (skipped if listen window consumed — jump logged)
             │                                         ├─ rung 4/5: dial_contact ── answered ─▶ resolve
             │                                         │                └ no_answer ─▶ next dial (jump logged)
             │                                         └─ rung 6: emergency — FAIL-CLOSED (audit-only even if enabled)
             └── privacy transform (blur/silhouette) ──▶ pre-event frames attached to incident
```

Branching is driven by cue kind + channel replies; every jump emits an audit event with
`from_index`/`to_index`/`reason`. Quiet hours (`soft_suppress_non_distress`) suppress
non-distress cues inside the window — suppression itself is audited.

## 4. Evaluation (labeled fixtures, reproducible)

`python scripts/evaluate.py --dnn --json docs/eval-metrics.json`

| Metric | Result |
| --- | --- |
| Cue recall (positive cases) | **1.00** (4/4: still person, leaves zone, on-floor, real photo via DNN) |
| False-escalation rate (negative cases) | **0.00** (active person, pet motion, illumination ramp) |
| Mean time-to-confirm | **3.0 s** (demo timeouts; plan timeouts are user-configured) |

The harness (`src/care_ladder/vision/eval_cases.py`) synthesizes noisy-room sequences
with textured person stand-ins and sensor-noise + light-drift backgrounds; the negative
cases encode the failure-modes doc as executable tests. Building this harness found and
fixed three real detector bugs (fixed threshold → Otsu; background-slab segmentation →
area rejection; single-frame noise arming `no_visibility` → sustained-presence gate).

## 5. AWS deployment (meaningful component)

| Service | Use | Evidence |
| --- | --- | --- |
| **ECR** | Image registry, scan-on-push | `367597235216.dkr.ecr.us-east-1.amazonaws.com/care-ladder:demo` |
| **ECS Fargate (Graviton/ARM64)** | Runs OpenCV 5 DNN + FastAPI | cluster `care-ladder-demo`, service desired=1, self-healing |
| **S3** | Pre-event clips (privacy-transformed only) | `care-ladder-demo-367597235216`, public access blocked |
| **EventBridge** | Cue bus (`CareLadderCue` detail-type) | bus `care-ladder` |
| **CloudWatch Logs** | Observability | `/ecs/care-ladder-demo` |

Task definition: `infra/task-definition.json` (0.5 vCPU / 1 GB, awsvpc, container health
check). The DNN person-detection fixture runs **inside** the Fargate task — verified live:
incident cue tagged `opencv_dnn_person_detector` from the public endpoint.

## 6. Responsible use

- Emergency rung **fail-closed** by default; even enabled it audits only — code cannot place a real emergency call.
- Demo contacts restricted to NANP reserved fiction (NPA-555-01XX); the plan loader **rejects** other numbers in demo env.
- Privacy transform enforced at attach: a non-zero pre-event frame count without blur/silhouette is refused; the caregiver API serves only transformed copies.
- No identity biometrics; no medical claims; failure modes and demo-vs-real boundaries documented.

## 7. Reproduce

```bash
python3 -m venv .venv && uv pip install -e ".[dev]"   # or pip
./scripts/download_models.sh                            # 12 MB person-detector ONNX
python -m pytest -q                                     # 46 tests
python scripts/evaluate.py --dnn --json docs/eval-metrics.json
./scripts/run_demo.sh                                   # local API + /ui/ console
```

Live: AWS Fargate endpoint (URL current as of submission; see README).
