# Care Ladder - Demo Video Production Script

**Target: 4:30–5:00.** Judging weights: Technical 30 · Innovation 20 · Impact 20 · UX 10 · Docs 10 · Cloud/responsible ops 10.
Word-for-word VO in the right column - read it verbatim or paraphrase lightly; it's paced (~135 wpm) to the on-screen action.

## Pre-record setup (do all of this BEFORE hitting record)

1. `cd ~/Documents/GitHub/opencv-care-ladder && ./scripts/run_demo.sh` - local UI at `http://localhost:8000/ui/` (use local, not AWS, for Paths A/B so timing is instant).
2. **Pre-seed the fall incident (critical):** upload `clips/kul_fall_1.avi` once via the local UI and let it finish (~2–4 min on your M-series Mac, faster than cloud). Keep that completed incident - it's your cut-in footage for the fall beat. Also have the production one ready: `https://d2u7pls4da2poz.cloudfront.net/incidents/8d528632736a4548992c7b1acb724ba1`.
3. Browser: two tabs - Tab 1 local `/ui/`, Tab 2 the pre-seeded fall incident. Editor tab with `configs/demo_home.yaml`. Terminal tab with `tests/fixtures/basketball1.png` in `open .` Finder (or just the repo open).
4. Record 1440p+, browser zoom ~125%. Full-screen the browser; hide bookmarks bar.
5. Microphone test - the VO below is ~640 words; a dry read should land at 4:45.

## Shot list + VO

| # | Time | On screen (action) | VO (read verbatim) |
| --- | --- | --- | --- |
| 1 | 0:00–0:20 | Title card / README top, scroll slightly | "Every year, one in four adults over sixty-five falls - and for people living alone, the dangerous fall is the one nobody sees. Families today choose between doing nothing and camera feeds that feel like surveillance. Care Ladder is a third path: a camera that *checks in* before it *escalates* - and proves every step." |
| 2 | 0:20–0:45 | `configs/demo_home.yaml` in editor; scroll through zones → triggers → rungs | "Everything is one care plan - one YAML file. Zones the camera watches. How long stillness lasts before it matters. Then the escalation ladder itself: look again… ask out loud… wait… call the primary caregiver… call the secondary. Emergency is fail-closed - off by default, and even enabled it can never place a real call. The behavior lives in config, not code." |
| 3 | 0:45–1:20 | Split: left `/ui/`, right `docs/eval-metrics.json` (or run `python scripts/evaluate.py --dnn` in terminal, scroll the results) | "Under the hood, OpenCV 5 does the seeing. A MediaPipe person detector runs in OpenCV's DNN module - real ONNX inference, not stock footage tricks. Background subtraction and Otsu segmentation drive the stillness and zone cues. On labeled evaluation - now including real fall footage - cue recall is one-point-zero, with zero false escalations on pets, lighting shifts, and people simply bending over." |
| 4 | 1:20–1:55 | `/ui/` → hover stats → click **"✓ Path A · verbal OK"** → watch timeline build; zoom when it lands | "Here's the core loop. The cue fires - the person hasn't moved. The ladder starts with *look again*: re-run perception, it's real. Then the speaker asks, out loud: are you okay? 'I'm fine' - and that's it. Resolved, no dial, nothing sent. Every step of that decision is in the audit timeline. This is what 'confirm before escalate' means." |
| 5 | 1:55–2:30 | Click **"↗ Path B · escalation"**; when timeline lands, mouse over the `jump` row | "Same cue. This time - silence. The ladder doesn't stall: no answer means advance. Dial the primary caregiver… logged, no answer. Dial the secondary… answered, resolved. And notice the jump event: the agent recognized the wait rung was already consumed and skipped it - and *logged the skip*. The caregiver sees not just what happened, but the reasoning. Vision started this; the replies steered it." |
| 6 | 2:30–3:05 | Click **"DNN · real photo"**; then open the incident's pre-event clip panel, step frames with ▶ | "This is a real photograph through the ONNX detector - person localized, cue tagged with the detector's name, so every incident is traceable to the model that saw it. And this is the privacy contract made visible: the caregiver's clip panel shows only silhouette frames. Blur and silhouette happen *before* anything is stored - raw pixels never leave the device path. You see the fall. You never see a face." |
| 7 | 3:05–3:55 | Switch to Tab 2: the **pre-seeded fall incident** (red distress card). Mouse across the pose chips, then the banner, then the timeline jump. | "Now the hardest problem, on real footage. This is a nursing-home fall re-enactment from the KU Leuven research dataset - a genuine fall, not a synthetic blob. Two models chained: person detection, then BlazePose body keypoints. Torso angle hits seventy degrees, the hip drops, and the *transition itself* is sudden - vertical to horizontal in under a second. That signature - not just 'person low in frame' - is what fires. And because it's a distress cue, the ladder escalates immediately, past the verbal rung. Bending over to pick something up? Gradual. It doesn't fire. A slow collapse onto a bed? The stillness path catches it minutes later. Falls escalate instantly; everything else escalates on evidence." |
| 8 | 3:55–4:20 | Show the upload happening live (start it before shot 7!): the progress bar ticking in the header; then `GET /incidents/{id}` raw JSON (curl or browser) | "The upload API is async by design - the clip analyzes in the cloud on AWS while the console stays live. And this JSON is the machine-readable truth the award judges: cue, chosen rung, tool result, jump reason - every agent decision structured, not screenshots." |
| 9 | 4:20–4:45 | `docs/agentic-workflow.html` diagram (or architecture section of README); optional quick CloudWatch/EventBridge console peek | "The whole stack runs on AWS: Fargate behind CloudFront, DynamoDB for the incident record, S3 for the privacy-filtered clips - silhouette only - and every cue published to EventBridge, with an archive rule so cues are deliverable events, not log lines. GitHub Actions runs the tests, the real-footage evaluation, builds the image, and deploys - a push to main is a verified deploy. And the honest parts are written down: no medical claims, no real telephony, failure modes documented." |
| 10 | 4:45–5:00 | README / repo root; end card with repo URL + live demo URL | "Care Ladder: OpenCV five sees, the ladder decides, and every step is on the record. Confirm before you escalate." |

## Cut-in cheatsheet (edit-time saves)

- The fall analysis takes minutes in real time - **never show it wall-clock**. Cut from "upload started" (progress bar visible) straight to the pre-seeded completed incident.
- If the local fall seed misbehaves, use the production incident `8d528632…` - verified live, full telemetry.
- Zooms: timeline sections in shots 4–5, pose chips in shot 7. 150%+ browser zoom reads better than post-zoom.
- Mistakes in 4/5/6: just re-click the button - incidents append; use the newest card, crop the older ones in edit.
- Numbers to say exactly: **recall 1.0 · zero false escalations · torso ~70° · 1-in-4 fall statistic**.

## Attribution (put in video description)

- Fall footage: KU Leuven Advise group, "High-quality fall simulation data" - nursing-home re-enactments, research use. `clips/README.md`.
- Models: OpenCV Zoo (MediaPipe person-detection + BlazePose ONNX, Apache-2.0).
- vtest pedestrian clip: OpenCV samples (Apache-2.0).
