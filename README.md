# Care Ladder

Agentic Vision care ladder for the **OpenCV AI Competition 2026** (Agentic Vision track).

OpenCV cues drive a configurable **confirm → Nest/Alexa-style check-in → dial escalation** workflow, with privacy blur/silhouette, pre-event clips, and an incident timeline API for judges.

This is a **demo / simulator** stack: telephony is a stub dialer, the smart speaker is a scripted simulator, and there is **no live camera** on the demo path. It does **not** claim clinical diagnosis.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## How OpenCV cues change rungs

1. **Vision (`CueDetector`)** watches frames in a plan zone and may emit a structured `CueEvent`:
   - `no_movement` - person-like blob still past `triggers.no_movement.timeout_sec`
   - `no_visibility` - monitored person leaves / cannot be seen in zone
   - `distress_heuristic` - simple motion/pose heuristic (not a medical assessment)
2. **Orchestrator (`run_incident`)** starts an incident from that cue and walks `configs/demo_home.yaml` **rungs** in order, appending an audit event per step:
   - `reperceive` → confirm / stub re-check
   - `speaker_prompt` → Nest/Alexa-style “Are you okay?” (simulator)
   - `wait` → listen / settle window (bounded in demo)
   - `dial_contact` → stub dial caregiver / secondary
   - `emergency` → **fail-closed** unless `params.enabled: true` (demo YAML keeps it `false`; even if enabled, code audits only and **never** places a real 911 call)
3. **Branching from cue + replies** (what judges see in the timeline):
   - Speaker **`ok`** → resolve (no dial)
   - Speaker **`call_caregiver`** → jump to primary dial (skipped rungs logged)
   - Speaker **`silence`** → continue down the ladder (demo fixture path)
   - Dial **`answered`** → resolve
   - Dial **`no_answer`** → escalate to next dial / skip non-dial rungs (logged jumps)

Demo fixtures:
- `no_movement_ok` - injects a `no_movement` cue with a verbal **"I'm fine"** speaker reply (spec §10 Path A): incident resolves at the check-in rung, no dial, no emergency.
- `no_movement_silence` - injects a `no_movement` cue with an empty speaker script (silence) so the ladder escalates through dial stubs.
- `opencv_stillness` - feeds **synthetic numpy frames** through `CueDetector.observe` (OpenCV), then `run_incident`; audit cue is tagged `source: opencv_cue_detector`.
- `opencv_dnn_person` - feeds a **real photo** through the **MediaPipe person-detection ONNX via OpenCV 5 DNN** (`models/`, run `scripts/download_models.sh` once), then the ladder; audit cue is tagged `source: opencv_dnn_person_detector` with detector name. Frames attach as silhouettes.

## Privacy (blur / silhouette)

Before clips or caregiver views leave the device path, use:

- `care_ladder.privacy.blur_faces(frame)` - Gaussian-blur person/face-like ROIs
- `care_ladder.privacy.to_silhouette(frame)` - filled grayscale person mask (not a full-color photo)

**Enforced at attach:** `run_incident(..., pre_event_frames=...)` maps frames through blur (default) or silhouette **before** setting `pre_event_frame_count`. Audit cue `detail` includes `privacy: "blur"` / `"silhouette"`; a non-zero attach count is refused without that flag. Do not ship raw identifiable video in demos.

## Reserved phones & emergency policy

- Demo contacts use **NANP reserved fiction** numbers only: **NPA-555-01XX**  
  (`+12125550101` caregiver Alex, `+12125550102` secondary Sam in `configs/demo_home.yaml`).
- When `CARE_LADDER_ENV=demo` (default), `load_care_plan` **rejects** non-reserved and emergency-like phones (`911`, `112`, etc.).
- **Never** configure or dial real 911 / real personal numbers in this repo.
- Emergency rung is **disabled by default** (`enabled: false`) - fail-closed in plan and in code.
- **`StubDialer`** returns scripted outcomes only; it does not open a PSTN/VoIP session.

## Quiet hours

`quiet_hours` with `policy: soft_suppress_non_distress` is **enforced** in `run_incident`: non-distress cues (`no_movement`, `no_visibility`) during the window get an audit `suppress` event and status `suppressed` (distress still runs). Demo API fixtures pin a midday clock so judge demos always walk the ladder.

## Judge demo: show the incident timeline

App entrypoint: `care_ladder.api.app:app`

### 1. Start the API

```bash
./scripts/run_demo.sh
# equivalent: uvicorn care_ladder.api.app:app --host 127.0.0.1 --port 8000
```

### 2. Run the demo fixture

```bash
# Injected cue (silence → dial stubs)
curl -s -X POST http://127.0.0.1:8000/demo/run \
  -H 'Content-Type: application/json' \
  -d '{"fixture":"no_movement_silence"}'

# OpenCV path: synthetic frames → CueDetector → ladder
curl -s -X POST http://127.0.0.1:8000/demo/run \
  -H 'Content-Type: application/json' \
  -d '{"fixture":"opencv_stillness"}'
```

Returns `{"incident_id":"<id>"}`.

### 2b. Or use the caregiver console UI

Open **http://127.0.0.1:8000/ui/** - SafelyYou-style incident timeline with one-click
demo fixtures:

- **Path A: verbal OK** (`no_movement_ok`) - check-in clears, no dial.
- **Path B: silence → escalate** (`no_movement_silence`) - dials walk stubs, jumps logged.
- **OpenCV stillness** (`opencv_stillness`) - synthetic frames through `CueDetector`.

Why this design (cited research): [`docs/research-brief.md`](docs/research-brief.md).
Known failure modes and limitations: [`docs/failure-modes.md`](docs/failure-modes.md).
Competitive landscape: [`docs/competitive-landscape.md`](docs/competitive-landscape.md).

### 3. Fetch the timeline

```bash
# list
curl -s http://127.0.0.1:8000/incidents | python3 -m json.tool

# full ordered audit trail for one incident
curl -s http://127.0.0.1:8000/incidents/<incident_id> | python3 -m json.tool
```

Expect ordered `events` with tools such as `cue` → `reperceive` → `speaker_prompt` → `wait` → `dial_contact` → … → `resolve` (or jumps), **≥3 audit events**. Interactive docs: http://127.0.0.1:8000/docs

## Demo care plan

See `configs/demo_home.yaml`. Emergency rung is **disabled by default** (fail-closed). Phones are reserved fiction (`+1212555010x`). Speaker and dial channels are **simulators/stubs**, not live Nest/Alexa or carrier dial.

## Tests

```bash
.venv/bin/pytest tests/ -v
```

E2E demo path: `tests/test_e2e_demo.py` (fixture → incident has ≥3 audit events).

## AWS deployment sketch (OpenCV / AWS meaningful component)

Live AWS deploy is **not** required for the judge demo. For the competition’s AWS path see:

- [`infra/README.md`](infra/README.md) - S3 (blurred/silhouette clips only), ECS/Fargate service, EventBridge cue bus; how this meets the “meaningful AWS” bar
- [`infra/ecs-task-outline.md`](infra/ecs-task-outline.md) - task/service outline (not live IaC)
- Root [`Dockerfile`](Dockerfile) - builds a runnable API image (`uvicorn care_ladder.api.app:app`)

The OpenCV/AWS compute grant proposal was submitted separately; this repo only sketches the same architecture. Do not assume a public URL unless you have actually deployed.
