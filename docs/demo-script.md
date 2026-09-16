# Care Ladder — Demo Script (≤5 min, timed to the judging rubric)

Judging weights: Technical 30 · Innovation 20 · Impact 20 · UX 10 · Docs 10 · Cloud/responsible ops 10.
Setup before recording: `./scripts/run_demo.sh` (or the live AWS URL), `/ui/` open in a browser tab,
`configs/demo_home.yaml` open in an editor tab. Two terminal tabs: one for curl, one for the UI.

| Time | Section | On screen | Say / show |
| --- | --- | --- | --- |
| 0:00–0:25 | Problem + thesis | Title slide or README top | "Families need remote eyes on seniors without alert floods. Care Ladder is a configurable escalation ladder: OpenCV 5 cues START the ladder, and voice/phone progress it — vision changes what the system does next." |
| 0:25–0:50 | The plan (config) | `configs/demo_home.yaml` | "One YAML: zones, trigger timeouts, ordered rungs — re-perceive, spoken check-in, wait, dial primary, dial secondary. Emergency is fail-closed, disabled. Contacts are reserved fictional numbers." |
| 0:50–1:30 | OpenCV 5 vision (Technical 30%) | `docs/eval-metrics.json` or eval run | "Two vision paths: a DNN person detector — MediaPipe ONNX running in OpenCV 5's DNN module on Graviton — plus MOG2 background subtraction and Otsu segmentation for the cue heuristics. Labeled evaluation: 1.0 recall, zero false escalations on pet-motion and light-shift negatives." |
| 1:30–2:10 | Path A: verbal OK (UX) | `/ui/` → click "Path A: verbal OK" | Cue fires → re-perceive → speaker asks "Are you okay?" → "I'm fine" → resolved, **no dial**. Show the timeline: every step audited. |
| 2:10–2:50 | Path B: silence escalates | `/ui/` → click "Path B" | Same cue, silence this time → ladder advances → dial primary (no answer, logged) → dial secondary (answered) → resolved. Point out the **jump event** in the timeline — the agent skipping the consumed wait rung, logged for audit. |
| 2:50–3:30 | DNN + privacy (Innovation) | `/ui/` → click "DNN person (real photo)" | Real photo through the ONNX detector → person localized → cue tagged with detector name. Then the **pre-event clip panel**: silhouette frames only — "the caregiver sees a silhouette, not your grandmother. Raw pixels never leave the device path." |
| 3:30–4:20 | **Real fall footage** (Technical + Impact) | `/ui/` → upload `clips/kul_fall_1.avi` | "A real nursing-home fall re-enactment from the KU Leuven dataset — not a synthetic blob." Upload returns a job instantly (async), the analyzer scans at 5 Hz in the cloud, and ~5 min later: `distress_heuristic`, pattern `sudden_vertical_to_horizontal`, source `pose_heuristics` — two ONNX models chained: person detection then BlazePose keypoints; torso angle + hip height say "fall", not "bent over". The ladder escalates straight past the verbal rung. Mention the negative control: pedestrians bending over do NOT fire (sudden-only rule), and gradual collapses escalate via stillness — two-tier. |
| 4:20–4:40 | Agentic trace (award path) | `GET /incidents/{id}` JSON | "The machine-readable trace judges the award on: cue → chosen rung → tool result → jump reason. Vision output changed every subsequent tool call in both paths — that's the Agentic Vision bar." |
| 4:40–4:55 | AWS + responsible ops | architecture diagram / ECS console | "Runs on Fargate from ECR behind CloudFront; DynamoDB incident store; S3 silhouette clips (show the bucket); EventBridge cue bus with a live archive rule — cues are deliverable events, not log lines. Reserved-phone enforcement in code, quiet hours, failure modes documented honestly — including what this demo is NOT (no medical claims, no real telephony)." |
| 4:55–5:00 | Close | README / repo | "Care Ladder: confirm before you escalate. OpenCV 5 sees, the ladder decides, every step is on the record." Link to repo + live URL. |

## Recording notes

- Record the browser at 1440p+; zoom the timeline section during Paths A/B.
- If using the live AWS URL, note the IP in the video description — it may change on redeploy.
- **Fall-clip beat timing:** start the upload EARLY (right after the DNN section at ~3:30) so the ~5-minute cloud analysis overlaps the agentic-trace section; the incident appears when the poll completes. Have the completed incident open in a second tab as backup (`/incidents/6b1206df…` pattern: distress → jump → dial ×2 → resolve).
- Clip attribution on screen: "KU Leuven Advise fall-simulation dataset — nursing-home re-enactments, research use" (see `clips/README.md`).
- Keep the failure-modes doc (`docs/failure-modes.md`) one click away; if judges ask about pets/occlusion, that's the answer.
- The competitive-landscape doc (`docs/competitive-landscape.md`) backs the "nobody does configurable confirm-before-escalate" claim.
