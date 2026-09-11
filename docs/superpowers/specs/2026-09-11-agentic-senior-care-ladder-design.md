# Agentic Senior Care Ladder — Design Spec

**Date:** 2026-09-11  
**Hackathon:** OpenCV AI Competition 2026 (AWS) — [opencv26.devpost.com](https://opencv26.devpost.com/)  
**Award path:** Agentic Vision (primary). COOL optional later, not required for v1.  
**Working title:** Care Ladder (remote wellness monitor for seniors / recovering people)

## 1. Problem

Families and caregivers need remote eyes on a senior or recovering person without staffing a nurse on site. Raw alert floods are noisy and stressful. They need a **configurable escalation ladder** that **confirms before escalating**, using vision to start the ladder and voice/smart-speaker/phone to progress it.

## 2. Users

| Role | Needs |
| --- | --- |
| Household caregiver | Configure triggers, rungs, contacts; receive calls/notifications; review **incident timeline** + pre-event clips |
| Monitored person | Low-friction check-in (“Are you okay?”); optional consent to monitoring |
| Judges / reviewers | Clear OpenCV → decision → action trace proving Agentic Vision |

## 3. Goals and non-goals

### Goals (v1)

- Substantive **OpenCV 5** image/video analysis on a meaningful **AWS** path.
- **Agentic** loop: OpenCV output **changes** the next tool call / plan / rung (not caption-only chat).
- Configurable care workflow (YAML/JSON): confirm → verbal response → wait → dial primary → … → optional emergency.
- Privacy-safe default: pose/motion/zones; **blur / mosaic / silhouette** before cloud persistence where frames leave the device.
- Demo mode with reserved fictional phones; live dials secret-gated (CALL-E-style destination bind).
- Competitor-inspired product bar locked for v1 (see §14): no-answer escalation, privacy path, pre-event clip, incident timeline, two-way speaker check-in.

### Non-goals (v1)

- Medical diagnosis or clinical claims.
- Continuous face recognition / identity biometrics.
- Auto-calling emergency services without an **explicitly enabled** rung plus fail-closed safeguards.
- Replacing professional monitoring or emergency response systems.

## 4. Core loop

1. Ingest camera frame(s) (live demo clip or RTSP/file for hackathon).
2. **OpenCV 5** emits a structured cue (see §5).
3. Agent loads the household **care plan** and selects the next **rung**.
4. Execute rung tools (`reperceive`, `speaker_prompt`, `wait`, `dial_contact`, `notify_caregiver`, optional `emergency`).
5. Append an **audit event** (and attach a **pre-event clip** buffer) so judges and caregivers see perception changing action; surface events in an **incident timeline** UI.
6. Clear / resolve when the monitored person confirms OK or a caregiver acknowledges.

## 5. OpenCV cue families

| Cue | Meaning | Notes |
| --- | --- | --- |
| `no_movement` | Stillness in a configured zone longer than timeout | Timeout configurable per plan |
| `no_visibility` | Person expected in frame but missing / left zone | Escalates especially when combined with no response on check-in |
| `distress_heuristic` | Coarse pose/motion heuristics (e.g. prolonged on-floor posture) | Not a diagnosis; same ladder as other cues |

Implementation sketch (not final APIs): person/pose detection or motion masks, zone polygons, temporal state machine. Prefer silhouette/pose over identifiable faces for the hot path.

## 6. Check-in channel and copy

**Preferred:** Amazon Alexa / Google Nest (or equivalent) when linked — low friction for seniors.  
**Fallback:** Phone TTS / CALL-E-style voice call.

**Default spoken prompt:**

> Are you okay? Do you want me to call 〈Caregiver〉?

- Affirmative / “I’m fine” / cancel keyword → clear rung, log resolution.  
- Request to call caregiver → jump to `dial_primary`.  
- Silence / no response within wait window → advance ladder.

## 7. Care-plan model

Per-household document (YAML or JSON), versioned:

```yaml
household_id: demo-home-1
caregiver:
  display_name: Alex
  phone_e164: "+12125550101"   # reserved fiction in demos
monitored:
  display_name: Pat
zones:
  - id: living_room
    polygon: [[...], ...]
triggers:
  no_movement:
    enabled: true
    timeout_sec: 900
  no_visibility:
    enabled: true
  distress_heuristic:
    enabled: true
rungs:
  - id: repreceive
    tool: repreceive
    params: { roi: auto }
  - id: ask_ok
    tool: speaker_prompt
    params:
      text: "Are you okay? Do you want me to call Alex?"
      channel: nest_or_alexa_then_phone
  - id: wait_reply
    tool: wait
    params: { sec: 120 }
  - id: dial_primary
    tool: dial_contact
    params: { contact: caregiver }
  - id: dial_secondary
    tool: dial_contact
    params: { contact: secondary }
  - id: emergency
    tool: emergency
    params: { enabled: false }   # fail-closed unless explicitly true
quiet_hours:
  start: "22:00"
  end: "07:00"
  policy: soft_suppress_non_distress
```

Rungs are ordered; the agent may skip or jump based on cue severity and user replies, but jumps must be logged.

## 8. Architecture (AWS)

```
Camera / demo video
    → (optional edge blur)
    → S3 or Kinesis Video
    → OpenCV 5 worker (ECS on Graviton or container)
    → cue events → EventBridge / SQS
    → Care Ladder agent (orchestrator)
         tools: repreceive | speaker_prompt | wait | dial_contact | notify | emergency
    → CALL-E-like telephony (demo stub / live grant)
    → DynamoDB audit trail + caregiver web console
```

**Meaningful AWS components:** ingest + compute for OpenCV, event bus, durable audit store, optional Step Functions for long waits, Secrets Manager for live dial credentials.

**Agentic Vision evidence:** store a machine-readable trace showing `opencv_cue` → `chosen_rung` → `tool_result` for at least one happy path and one escalate path.

## 9. Telephony and safety rails

- Reuse patterns from Fraud Ops Caller / CALL-E: plan-first where useful, **destination-bound live grant**, operator secret, reserved NANP/Ofcom fiction in fixtures.
- Emergency rung **disabled by default**; when enabled, require explicit config + (recommended) caregiver confirmation gate for v1 hackathon demos.
- No secrets in git; demo path never places real emergency calls.

## 10. Evaluation and demo

**Demo script (≤5 min video):**

1. Show care-plan YAML (timeouts + prompt with caregiver name).  
2. Simulate `no_movement` → repreceive → Nest/Alexa-style prompt.  
3. Path A: verbal OK → clear.  
4. Path B: silence → dial primary (stub) → show audit trace.  
5. Call out OpenCV 5 ops + AWS deployment + responsible-use limits.

**Metrics (lightweight):** time-to-confirm, false-escalation rate on labeled clips, rung completion rate, trace completeness.

## 11. Responsible use

- Consent of monitored adult (or lawful caregiver authority) required before real deployment.  
- Not a medical device; not a substitute for 911 / local emergency services.  
- Minimize retention of identifiable video; prefer blurred frames and short clip buffers.  
- Document failure modes (occlusion, pets, camera angle) in the technical report.

## 12. Deliverables (hackathon)

- Technical report, architecture diagram, repo with pinned deps, working demo endpoint or screen-share, ≤5 min video, evaluation evidence + failure cases, Agentic Vision workflow diagram + action trace.

## 14. Competitor-inspired v1 features (locked)

Borrow product patterns, not vendor stacks or accuracy claims. All are in scope for v1:

| Feature | Inspired by (pattern) | Care Ladder behavior |
| --- | --- | --- |
| No-answer escalation | Kami / medical-alert ladders | If check-in silent and/or primary dial unanswered, advance to secondary; emergency only if rung `enabled: true` + fail-closed gates |
| Privacy silhouette / blur | AltumView stick-figure; D-Link mosaic | Default pipeline: face mosaic or pose/silhouette export before cloud; raw identifiable frames stay local/demo-only |
| Pre-event clip | Kami incident context | Keep a rolling 15–60s buffer; on cue, attach clip (blurred) to the incident record |
| Incident timeline UI | SafelyYou-style review | Caregiver console shows ordered story: cue → repreceive → ask → waits → dials → resolve |
| Two-way speaker check-in | Nobi / Alexa Together patterns | Prompt: “Are you okay? Do you want me to call 〈Caregiver〉?” with listen-back; Nest/Alexa first, phone fallback |

**Explicitly out of v1 marketing:** unverifiable “99.x% accurate” claims; real 911 without gated config; facility EHR integrations (SafelyYou-class B2B).

## 15. Open questions (post-spec, non-blocking for plan)

- Exact Nest/Alexa integration path for hackathon (skill + companion app vs simulated speaker UI).  
- Whether to pursue COOL on Graviton as a stretch after Agentic Vision bar is met.  
- Edge vs cloud-only OpenCV for the submission video.
