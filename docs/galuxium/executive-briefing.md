# Care Ladder - Galuxium Nexus V2 Executive Briefing

Devpost-ready summary of the hosted Care Ladder SaaS. Design detail lives in
`docs/superpowers/specs/2026-09-17-galuxium-care-ladder-saas-design.md`;
shot-level demo detail in `docs/galuxium/demo-video-galuxium.md`.

## Market friction

Families and small assisted-living operators need remote eyes without a human
glued to a camera wall. Raw motion alerts are noisy, so they get ignored, and
consumer cameras feel like surveillance. Care Ladder turns vision cues into a
configurable escalation ladder that checks in before it escalates - and writes
a timestamped audit trail of every rung it considered, so the question after an
incident is "what did the system know and do", answered from records rather
than memory.

## Dual ICP

- **Home care:** family or private caregiver for an aging parent. Ladder:
  check-in by voice, wait window, call primary, optionally call secondary.
  One household, one camera, $29/mo.
- **Facility (the wedge, primary Galuxium story):** assisted-living lean ops,
  especially nights and weekends when floors are not staffed to watch monitors.
  Ladder: check-in, notify ops via Slack, escalate to the shift supervisor,
  then dial the resident's primary caregiver. The audit trail is the artifact
  facility operators and auditors already want; the price ($199/mo starter) is
  one they can approve without a procurement cycle.

## Architecture (hosted SaaS)

Browser caregiver console -> HTTPS -> FastAPI (session auth, billing webhooks,
ladder orchestrator) -> Postgres audit store (tenant id on every query) ->
notify adapters (real Slack incoming webhook, or a logged stub when unset) ->
StubDialer (reserved fictional numbers; secret-gated real telephony later) ->
Stripe Checkout + Customer Portal. Vision path: upload and fixture-driven
OpenCV analysis; no mandatory live RTSP in the Galuxium MVP. Deployed on
Render (Docker) with managed Postgres; demo tenants and schema bootstrap
idempotently on container start.

## Fiscal architecture

| Plan | Price | Includes |
| --- | --- | --- |
| Home | $29/mo per household | 1 household, 2 seats, home ladder, full audit trail |
| Facility Starter | $199/mo per site | 1 site, 10 seats, Slack notify, supervisor escalation, 7-day clip retention |
| Facility Growth | $499/mo per site | 25 seats, 30-day retention, multi-tenant admin, learning schedules with freeze controls |

Engine: Stripe Checkout for upgrade, Customer Portal for manage/cancel; the
verified webhook updates `tenant.plan` / `subscription_status`. Free judge
demo tenant, no card required. No incident-based overage metering in the MVP.
The billing webhook is fail-closed: an unset or unverified signing secret makes
every webhook reject rather than trust.

## Cohort and go-to-market wedge

Lead with facility lean-ops for Galuxium judges: two extra rungs
(notify_channel, notify_supervisor) turn a consumer product into an ops tool,
and the demo accounts show both modes side by side. Home Path A/B stays the
simpler plan tier and the demo spine - the same engine, priced for families.

## Judge access

Two seeded demo tenants, no card required: `demo@careladder.local` /
`demo-pass-home` (home mode) and `facility@careladder.local` /
`demo-pass-facility` (facility mode). Both are one click from the landing
page, and the bootstrap re-seeds them idempotently on every deploy.

## Success criteria

- Ladder correctness: Path A resolves with no dial on verbal OK; Path B
  advances through both dials and logs the wait-window jump. (Tested.)
- Tenancy: every store query tenant-scoped; cross-tenant reads impossible.
  (Tested.)
- Billing: webhook sets plan only with a valid signature; fail-closed when
  unset outside demo. (Tested.)
- Operator experience: notify and supervisor rows readable on the audit
  timeline with sound off; acknowledge closes the loop shift-aware.
- Honest ops: stub telephony and Slack-vs-stub state visible in the UI and
  docs, never hidden.

## Dual-hackathon separation

Three filings, three repos, one engine - never packaged together:

- **OpenCV AI Competition 2026:** `pamu512/opencv-care-ladder` (upstream,
  deadline Oct 26). On-device OpenCV vision story, AWS stack.
- **Galuxium Nexus V2:** this repo, `pamu512/care-ladder-saas` (deadline
  Oct 31 IST). Hosted multi-tenant SaaS, facility wedge, Stripe billing.
- **RevenueCat Shipaton:** ReadyPup - a different product in a different
  repository. Nothing from ReadyPup appears in Care Ladder filings.

## Non-goals (hard)

No medical diagnosis claims and no clinical risk scores. No live 911/EMS
product feature - emergency dialing ships disabled and stays behind a human
gate. No face recognition; frames become blur or silhouettes before storage.
No HIPAA certification claims. No ReadyPup / RevenueCat packaging here.
Hunt/Tarka integrations out of scope.
