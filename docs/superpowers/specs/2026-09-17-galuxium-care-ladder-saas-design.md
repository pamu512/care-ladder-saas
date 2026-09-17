# Care Ladder Hosted SaaS — Galuxium Nexus V2 Design Spec

**Date:** 2026-09-17  
**Hackathon:** Galuxium Nexus V2 — [galuxium-nexus-v2-29411.devpost.com](https://galuxium-nexus-v2-29411.devpost.com/)  
**Deadline:** 2026-10-31 17:00 IST (~19:30 HKT)  
**Approach lock:** A — Care Ladder hosted SaaS (not Tarka Hunt)  
**Related:** OpenCV Care Ladder product (`opencv-care-ladder`); RevenueCat Shipaton uses **ReadyPup**, not this filing.

## 1. Problem and buyer (approved)

Families and facilities need remote eyes without a human glued to camera walls. Raw motion alerts are noisy. Care Ladder turns vision cues into a **configurable escalation ladder** that **confirms before escalating**.

### Dual ICP

| Mode | Buyer | Ladder shape | Value |
| --- | --- | --- | --- |
| **Home-care** | Family / private caregiver | Check-in → call primary (optional secondary) | Peace of mind without staffing |
| **Facility (enterprise)** | Assisted living / care home ops (DON, floor lead) | Check-in → Slack/Teams notify → escalate to **supervisor** → call primary caregiver | Run **leaner** floors/nights: vision+ladder opens incidents so staff are not screen-glued |

Primary Galuxium story: **facility tier** (enterprise angle + monetization). Home-care remains the simpler plan and keeps Path A/B demo spine.

### Non-goals (hard)

- Medical diagnosis or clinical accuracy claims  
- Live 911 / EMS dispatch as a product feature  
- Face recognition / identity biometrics  
- Replacing professional monitoring or nurse call systems  
- Claiming AWS “live” if only sketched  

Fail-closed: `emergency.enabled: false` by default; demo telephony is stub + reserved `+1XX55501XX` phones; production live dials are secret-gated and never emergency by default.

### One-liner

Vision spots the moment; the ladder picks the next human-safe step with an operator in the loop.

## 2. Architecture

### 2.1 Deployed shape (Galuxium MVP)

```
[Browser caregiver console]
        |
   HTTPS (public URL)
        v
[API: FastAPI Care Ladder + auth + billing webhooks]
   |            |              |
   v            v              v
[Orchestrator] [Audit store] [Notify adapters]
   |            (Postgres)     Slack/Teams stub→real
   v
[Vision path: fixtures / upload / optional edge worker]
[Dial: StubDialer in demo; gated provider later]
[Billing: Stripe Checkout + Customer Portal]
```

- **Public cloud host** required (Fly.io, Railway, Render, or AWS ECS). Single region OK for MVP.  
- **Postgres** for tenants, users, care plans, incidents, audit events (replace process-local `AuditStore`).  
- **Object storage** (S3-compatible) for privacy-transformed clip frames only (blur/silhouette), never raw faces by default.  
- **Auth:** email magic-link or password + session cookie; tenant_id on every row.  
- **Modes:** `tenant.mode ∈ {home, facility}` selects default care-plan template and which notify/dial rungs are allowed.

### 2.2 Care-plan deltas for facility

Extend YAML/plan model (additive, home plans unchanged):

```yaml
mode: facility   # or home
supervisor:
  display_name: Floor Lead
  slack_user_id: "U0DEMO"      # or teams_user_id
  phone_e164: "+12125550103"   # reserved in demo
notifications:
  slack:
    enabled: true
    webhook_env: SLACK_WEBHOOK_URL   # or bot token + channel
  teams:
    enabled: false
rungs:
  # ... ask_ok, wait_reply ...
  - id: notify_ops
    tool: notify_channel
    params: { channel: slack, template: incident_open }
  - id: escalate_supervisor
    tool: notify_supervisor
    params: { contact: supervisor }
  - id: dial_primary
    tool: dial_contact
    params: { contact: caregiver }
  - id: emergency
    tool: emergency
    params: { enabled: false }
```

Home mode: no `notify_channel` / `notify_supervisor` rungs in the default template.

### 2.3 Channel adapters

| Tool | Home | Facility | MVP honesty |
| --- | --- | --- | --- |
| `speaker_prompt` | yes | yes | Simulator (scripted OK / silence) |
| `dial_contact` | primary (+ secondary) | primary caregiver | StubDialer + reserved phones in demo; real provider gated |
| `notify_channel` | no | Slack and/or Teams | Real webhook when env set; else **logged stub** with audit `adapter=stub` |
| `notify_supervisor` | no | yes | Slack DM / Teams chat or stub; audit always |

### 2.4 OpenCV / Agentic Vision

Keep existing cue detector + privacy + orchestrator. Galuxium MVP may run **fixture + upload** path on the hosted API (no mandatory live RTSP). OpenCV Competition filing can continue to emphasize vision; Galuxium filing emphasizes **hosted SaaS + monetization + facility workflow**.

## 3. Monetization (fiscal architecture)

| Plan | Price (indicative) | Includes |
| --- | --- | --- |
| **Home** | $29/mo per household | 1 household, 2 seats, home ladder, stub/demo dial honesty |
| **Facility Starter** | $199/mo per site | 1 site, 10 seats, Slack/Teams notify, supervisor escalate, clip retention 7d |
| **Facility Growth** | $499/mo per site | 25 seats, 30d retention, priority support placeholder |

- **Engine:** Stripe Checkout (subscription) + Customer Portal; webhook updates `tenant.plan` / `subscription_status`.  
- **Metering (optional later):** per-incident overage — **out of Galuxium MVP** (YAGNI).  
- Free **judge demo tenant** with fixture buttons, no card required.  
- Document fiscal design in README + Devpost “Fiscal Architecture” section.

## 4. MVP scope (ship by Oct 31)

### In scope

1. Multi-tenant Postgres + auth + `tenant.mode`  
2. Home + facility default care plans  
3. `notify_channel` + `notify_supervisor` tools (real Slack webhook when configured; stub otherwise)  
4. Facility UI: incident timeline already exists; add mode badge, supervisor/notify events visible  
5. Stripe subscription checkout for Home + Facility Starter  
6. Public HTTPS deploy + professional README (architecture, schema, local run)  
7. Landing page: problem → facility lean-ops wedge → pricing → demo login  
8. 2–5 min demo video (prefer UI-first v2 cut + facility notify beat)  
9. Executive briefing copy for Devpost (market friction, architecture, cohort, fiscal)

### Out of scope (explicit)

- Live Nest/Alexa hardware  
- Real PSTN without secret gate  
- Teams full Graph bot (Teams can be stub-only if Slack is real)  
- GNN / deep Hunt / Tarka packaging  
- HIPAA certification claims  
- Mobile native apps  

## 5. Galuxium submission checklist

1. Live demo URL (stable)  
2. Public GitHub repo + README  
3. Working MVP workflows (Path A/B + facility notify → supervisor)  
4. Executive briefing (Devpost About)  
5. Fiscal architecture (pricing + Stripe proof in demo)  
6. Demo video 2–5 min (required)  
7. **Tarka-circle pre-submit review** before filing (standing Devt rule)

## 6. Dual-hackathon note

| Hackathon | Project | Do not mix |
| --- | --- | --- |
| RevenueCat Shipaton (Oct 1) | **ReadyPup** | Not Care Ladder |
| OpenCV AI 2026 (Oct 27) | Care Ladder vision track | Emphasize OpenCV + AWS sketch |
| Galuxium Nexus V2 (Oct 31) | Care Ladder **hosted SaaS** | Emphasize tenancy, facility ladder, payments |

Same codebase may power OpenCV + Galuxium; packaging and claims differ.

## 7. Success criteria

- Judge can open live URL, run Path A and Path B without setup.  
- Facility demo shows Slack (or stub) notify + supervisor escalate on the timeline.  
- Stripe test-mode checkout completes and unlocks Facility Starter features.  
- No clinical / live-911 claims in UI, VO, or Devpost copy.  
- Video mute-test: cue → rung → notify/dial → resolve readable without VO.
