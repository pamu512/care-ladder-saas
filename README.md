# Care Ladder SaaS (Galuxium Nexus V2)

Multi-tenant hosted SaaS build of [Care Ladder](https://github.com/pamu512/opencv-care-ladder) for the
[Galuxium Nexus V2](https://galuxium-nexus-v2-29411.devpost.com/) hackathon (deadline Oct 31, 2026 IST).

Forked from the OpenCV AI Competition 2026 build at commit `87b6f3e`. The upstream repo remains the
OpenCV submission; this repo diverges here with tenancy, facility workflows, and billing.

## What this fork adds (per spec)

- Multi-tenant Postgres (`Tenant`/`User`/`IncidentRow`/`AuditEventRow`/`Subscription`) behind a
  `PostgresAuditStore` that preserves the `AuditStore` surface
- Session-cookie auth with `tenant_id` on every query; home vs facility tenant modes
- Facility care plan (`configs/demo_facility.yaml`): `notify_and_await_ack` rung pages
  caretakers over Slack / Teams / WhatsApp / Telegram and pauses escalation for a
  signed, single-use acknowledgment link; no ack inside the window → supervisor rung
  + dial (escalation on delayed/no response is the default behavior)
- Caretaker acknowledgment surface: `GET /ack/{token}` one-tap mobile page (no console
  session needed — the token is the capability), `POST /acks/{token}` record endpoint,
  `GET /acks/pending` live panel in the caregiver console with an Acknowledge button
- Stripe Checkout + webhook for Home ($29/mo) and Facility Starter ($199/mo)
- Landing page with pricing and judge demo login; public HTTPS deploy (Render + managed Postgres)
- Home Path A/B demo fixtures unchanged from upstream

## Design docs

- Spec: `docs/superpowers/specs/2026-09-17-galuxium-care-ladder-saas-design.md`
- Implementation plan (TDD, task-by-task): `docs/superpowers/plans/2026-09-17-galuxium-care-ladder-saas.md`

## Upstream

- `upstream` remote: https://github.com/pamu512/opencv-care-ladder (OpenCV submission, deadline Oct 26)
- Sync policy: this fork moves independently after the fork point; no merges back during either
  submission window. OpenCV-critical fixes go upstream first, then cherry-pick here.

## Pricing (fiscal architecture)

| Tier | Price | Scope |
| --- | --- | --- |
| Home | $29/mo | 1 household, 1 camera, voice check-in ladder, caregiver notify, full audit trail |
| Facility Starter | $199/mo | Up to 10 rooms, Slack supervisor queue, shift-aware acknowledge, audit export |
| Facility Growth | $499/mo | Unlimited rooms, multi-tenant admin, learning schedules with freeze controls, priority support |

Stripe Checkout (test mode for the hackathon) gates plan upgrades; the
billing webhook is fail-closed - an unset signing secret in a non-demo
environment makes every webhook reject rather than trust.

## Deploy (Render)

Primary target: Render web service + managed Postgres via `render.yaml`
(blueprint deploy). The image is built from `Dockerfile.saas` (never the
upstream `Dockerfile`): on boot it runs the idempotent demo bootstrap
(`scripts/bootstrap_saas_demo.py` - creates schema + demo tenants/users,
safe on every restart) and then uvicorn. Health probe: `GET /demo/context`
(kept unauthenticated on purpose for platform probes).

Local run:

```bash
python -m venv .venv && . .venv/bin/activate
uv pip install -e .                   # includes psycopg[binary] for Render Postgres
uvicorn care_ladder.api.app:app --port 8000
open http://localhost:8000/           # landing + demo logins
```

Demo accounts (seeded by the bootstrap, also live in auth-less demo mode):

- Home: `demo@careladder.local` / `demo-pass-home`
- Facility: `facility@careladder.local` / `demo-pass-facility`

Facility demo fixtures (console buttons):

- `facility_notify_silence` — silence → page ops → (bounded wait) → supervisor → dial
- `facility_ack_resolved` — page goes out, caretaker acknowledges inside the window,
  escalation stops, incident resolves with `reason: caretaker_ack`
- `facility_ack_timeout` — nobody acknowledges → `ack_timeout` logged, ladder
  escalates to supervisor + dial (the delayed/no-response path)

Ack-link env:

- `PUBLIC_BASE_URL` — base for ack links embedded in pages (defaults to empty;
  set to your deployed origin, e.g. `https://careladder.example`)

## Honesty notes

- `DialerChannel` is a stub: numbers dialed are reserved fictional
  (`(555) 010-xxxx`); Slack notify is a real incoming webhook when
  `SLACK_WEBHOOK_URL` is set, otherwise a logged stub.
- Multi-channel pages (Teams / WhatsApp / Telegram) follow the same convention:
  real HTTP delivery only when that channel's env credentials are set
  (`TEAMS_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`,
  `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_TO`); otherwise the
  audit trail records `adapter: stub` and delivery is simulated. WhatsApp uses
  the Cloud API text endpoint — production business-initiated messaging needs
  an approved template; Telegram uses the Bot API.
- Acknowledgment tokens are signed with `SESSION_SECRET` (random per-process
  secret when unset), single-use, and expire with the rung's ack window (+60s
  grace). The ack registry is process-local like the upload-job map: a restart
  clears pending windows and stale links fail closed.
- The upload-job status map is process-local: a redeploy mid-analysis
  orphans that job (single-instance MVP on Render starter).
- Emergency dialing ships disabled and stays behind a human gate - Care
  Ladder never calls emergency services on its own.
- Not a medical device: no diagnosis, no clinical risk scores.

## Dual-hackathon note

The RevenueCat Shipaton filing uses **ReadyPup** - a different product in a
different repo. This repo is the Galuxium Nexus V2 filing only. The OpenCV
AI Competition 2026 filing is the upstream `opencv-care-ladder` repo. The
three share the Care Ladder engine but are submitted separately and never
mixed.
