# Care Ladder - Competitive Landscape Research

Researched 2026-09-15 for the OpenCV AI Competition 2026 build phase (deadline Oct 26, 2026).
Sources: vendor sites (AltumView, Aloe Care, Hero), search-indexed summaries, hackathon rules
(via archive of opencv26.devpost.com). Competitor patterns were previously locked in design
spec §14; this doc verifies and extends them with live findings.

## Hackathon requirements (verified from rules page)

- Every entry: **OpenCV 5 for substantive image/video analysis** + a **meaningful AWS component**.
- **Agentic Vision Award ($1,000)**: agent uses OpenCV 5 tools in a multi-step
  perception-decision-action loop where **visual results change the next plan/tool/action**.
  "A chatbot that only explains a fixed vision result is not enough."
- **Judging weights:** Technical execution 30% · Innovation 20% · Real-world impact 20% ·
  UX 10% · Documentation/presentation 10% · Cloud delivery/reproducibility/responsible ops 10%.
- 50 teams get a $150 compute grant; all proposal submitters may build.
- **Implication:** Care Ladder's cue→rung branching audit trace *is* the award thesis; the
  UX and responsible-ops axes (20% combined) justify the caregiver console + fail-closed rails.

## Product landscape

| Product | Approach | What they prove out | Care Ladder difference |
| --- | --- | --- | --- |
| **AltumView Sentinare** (CES 2021 honoree, B2B US/CA/AU/JP/UK/EU) | Edge AI sensor; detects falls, bed-leaving, wandering, overstays, absences; ROI + face-rec options; 2025 cloud AI for anomaly analysis | Onboard chip converts people to **stick figures before transmission** - privacy-first vision sells in bedrooms/bathrooms | Same privacy stance (blur/silhouette pre-persist); we add a **configurable escalation ladder** rather than fixed alert push |
| **Aloe Care Health** ($39–60/mo, CNET-rated) | Voice-activated Smart Hub + Care Button → 24/7 **professional emergency response center**; caregiver app with real-time updates; wearable fall detection | Human call center as escalation backbone; voice-first interaction for seniors | We replace the call center with a **transparent, family-configured ladder** (confirm → check-in → dial) - no subscription, auditable |
| **Kami Home "Fall Detect"** | Consumer cloud camera with AI fall detection on Kami cloud | Fall detection as an **add-on to a mass-market security camera** | We generalize beyond falls (stillness, absence, distress heuristic) and put **branching logic** at the center |
| **Nobi** (pattern, site unreachable this pass) | Smart *lamp* with fall detection + two-way talk; talks to the person first, escalates second | Ambient form factor; **speak-before-alert** flow | Our `speaker_prompt` rung mirrors this; ladder order is user-configurable |
| **SafelyYou** (pattern) | B2B dementia-care fall detection + clinician-reviewed video review | **Incident review workflow** for care staff | Our incident timeline UI is the direct analog, family-scale |
| **Alexa Together** (pattern; consumer era ending) | Remote caregiving service: urgent-response agents + daily check-ins | Smart-speaker as **low-friction senior check-in channel** | Our Nest/Alexa-style simulator + phone fallback mirrors its funnel |
| **Hero** ($39–60/mo, verified) | Smart pill dispenser + app, caregiver visibility, 24/7 support | Adjacent archetype: **medication adherence** with escalation-lite (alerts only, no ladder) | Not a competitor; shows families pay for "peace of mind + escalation" subscriptions |

## Cross-cutting patterns (validated)

1. **Confirm-before-escalate is rare, and that's the gap.** AltumView/Kami push alerts;
   Aloe Care routes to humans. None expose a *configurable* confirm → check-in → dial
   ladder with an auditable decision trace. That's Care Ladder's wedge.
2. **Privacy processing at the edge is table stakes** (AltumView stick figures, D-Link mosaic).
   Our blur/silhouette-before-persist matches the category's hard requirement.
3. **Voice-first for seniors wins** (Aloe, Nobi, Alexa Together) - supports the
   speaker-prompt rung being rung #2, before any dial.
4. **Subscription call centers are the incumbent revenue model** - a DIY/family ladder
   undercuts it, good "real-world impact" (20%) narrative for judges.
5. **Fall detection ≠ the whole job**: absence, bed-leaving, stillness (AltumView's
   full cue list) validate our `no_movement` / `no_visibility` / `distress_heuristic` families.

## Gaps in competitors worth exploiting in the demo

- **No incident-timeline audit trail** aimed at *families* (SafelyYou is staff-facing B2B).
- **No transparent "why did it escalate" story** - our per-rung audit events with logged
  jumps directly answer this and double as Agentic Vision evidence.
- **No config surface** - rungs/timeouts/contacts are vendor-locked; our YAML care plan
  is the differentiator to show on camera.
