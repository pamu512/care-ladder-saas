# Care Ladder — Failure Modes and Limitations

Required by the design spec (§11 Responsible use, §12 Deliverables): document known
failure modes honestly for judges. The vision layer is a **heuristic demo**, not a
clinical or safety-certified system.

## Vision failure modes (CueDetector)

| Mode | What happens | Ladder consequence |
| --- | --- | --- |
| **Occlusion** (furniture, blanket, partially out of frame) | Person-like blob shrinks or vanishes → may read as `no_visibility` or reduce motion area below threshold | False escalate (check-in prompt, possibly stub dial) — annoying, not dangerous; verbal OK clears |
| **Pets / moving objects** | Fan, curtain, pet motion keeps motion_mean above stillness threshold | **False negative**: `no_movement` may never fire while a real stillness event occurs. Timeout tuning + zone polygons mitigate |
| **Camera angle / lighting** | Strong daylight shifts or auto-exposure churn inflate frame-diff motion | False negatives (never still); night IR washout can fragment the blob → false `no_visibility` |
| **Blob ≠ person** | Detector is frame-diff + contour stand-in, no identity or pose model | Anything large and still (laundry pile, box) can trigger `no_movement` |
| `distress_heuristic` (pose path) | Two-ONNX chain (person-detector + BlazePose) computes torso angle / hip height; only the **sudden** vertical→horizontal signature fires. Gradual transitions (lying down deliberately, crouching) are deliberately **not** cue-worthy — verified: OpenCV vtest pedestrian bend-overs stay silent. Pose keypoints flicker unreliable on a motionless lying person, so gradual collapses (verified: KU Leuven gradual bed-fall clip) do **not** fire the fast path — they escalate via `no_movement` stillness at the plan timeout (two-tier escalation) |
| `distress_heuristic` (shape fallback) | Aspect-ratio / y-position stand-in used only when pose models are absent | Explicitly **not** a medical assessment |

## Real-footage validation (KU Leuven Advise fall-simulation dataset)

Clips fetched by `scripts/download_clips.sh` (attribution in `clips/README.md`); results are reproducible via the clip eval cases (`clip_real_fall_1`, `clip_fall_2_two_tier`, `clip_pedestrians_negative`):

| Clip | Ground truth | System behavior | Result |
| --- | --- | --- | --- |
| `kul_fall_1.avi` | Hard fall to floor | `distress_heuristic` sudden_vertical_to_horizontal at t=100.7s | ✅ instant escalation |
| `kul_fall_2.avi` | Gradual collapse onto bed | Pose fast path silent (pose unreliable on motionless subject); `no_movement` stillness fires at plan timeout (t=99s @30s timeout) | ✅ two-tier escalation |
| `vtest.avi` | Pedestrians walking, bending | No cue of any kind | ✅ negative control holds |

## Ladder / channel failure modes

- **Speaker simulator** is scripted; a real Nest/Alexa skill adds ASR errors ("fine" vs "not fine") the simulator does not model.
- **StubDialer** returns scripted outcomes; real telephony adds carrier failure modes out of scope.
- **Quiet hours** (`soft_suppress_non_distress`) can suppress a genuine non-distress cue window; distress cues still run.
- **Emergency rung is fail-closed** (`enabled: false` by default). Enabling it does **not** place real calls — audit-only.

## Honest scope statements (submission copy)

- Demo/simulator stack: no live camera, stub telephony, scripted speaker.
- No medical claims; not a substitute for 911 or professional monitoring.
- Privacy: frames are blurred/silhouette before persistence; raw identifiable video never leaves the device path.
- Metrics claims limited to labeled synthetic fixtures (time-to-confirm, audit-trace completeness); no "99.x% accurate" claims.

## Mitigations implemented

- Zone polygons + per-plan `timeout_sec` tuning (reduces pet/occlusion false fires).
- Confirm-before-escalate ladder: a verbal OK at rung 2 clears without any dial.
- Every skip/jump is audited; suppressed incidents are recorded, not dropped.
- Reserved NANP fiction phones only in demo plans; emergency fail-closed in plan **and** code.
