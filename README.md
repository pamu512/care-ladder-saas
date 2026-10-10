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
  session needed (the token is the capability)), `POST /acks/{token}` record endpoint,
  `GET /acks/pending` live panel in the caregiver console with an Acknowledge button
- Stripe Checkout + webhook for Home ($9/mo), Facility Starter ($49/mo), and
  Facility Growth ($99/mo)
- Landing page with pricing and judge demo login; public HTTPS deploy (Render + managed Postgres)
- Home Path A/B demo fixtures unchanged from upstream

## Design docs

- Spec: `docs/superpowers/specs/2026-09-17-galuxium-care-ladder-saas-design.md`
- Implementation plan (TDD, task-by-task): `docs/superpowers/plans/2026-09-17-galuxium-care-ladder-saas.md`

## Upstream

- `upstream` remote: https://github.com/pamu512/opencv-care-ladder (OpenCV submission, deadline Oct 26)
- Sync policy: this fork moves independently after the fork point; no merges back during either
  submission window. OpenCV-critical fixes go upstream first, then cherry-pick here.
- Sibling consume: `models/fall_cls_v1.onnx` + `models/MODEL_CARD.md` are the versioned
  edge classifier from `opencv-care-ladder` tip `a7357c0` (SHA256
  `549721e2b29cad10776fde2cb6186cf19383f982050f37e9335096c1aaadb608`). OpenCV cues still
  drive the ladder; the ONNX is an optional soft score on `distress_heuristic` only
  (`CARE_LADDER_FALL_CLS=0` to disable). Not a diagnosis.

## Pricing (fiscal architecture)

| Tier | Price | Scope |
| --- | --- | --- |
| Home | $9/mo | 1 household, 1 camera, voice check-in ladder, caregiver notify, full audit trail |
| Facility Starter | $49/mo | Up to 10 rooms, Slack supervisor queue, shift-aware acknowledge, audit export |
| Facility Growth | $99/mo | Unlimited rooms, multi-tenant admin, learning schedules with freeze controls, priority support |

Stripe Checkout (test mode for the hackathon) gates plan upgrades; the
billing webhook is fail-closed - an unset signing secret rejects every
webhook unless `CARE_LADDER_ALLOW_UNSIGNED_WEBHOOKS=1` is set explicitly
(local opt-in). `CARE_LADDER_ENV=demo` still enables stub checkout URLs;
it does not accept unsigned webhooks. On Render, set `STRIPE_WEBHOOK_SECRET`.

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

- Home: `demo@careladder.local`
- Facility: `facility@careladder.local`

Passwords are not published here: they are seeded by the bootstrap and
pre-filled by the landing page's demo sign-in buttons, so the buttons are the
intended entry point. Hand off judge credentials privately.

Facility demo fixtures (console buttons):

- `facility_notify_silence`: silence → page ops → (bounded wait) → supervisor → dial
- `facility_ack_resolved`: page goes out, caretaker acknowledges inside the window,
  escalation stops, incident resolves with `reason: caretaker_ack`
- `facility_ack_timeout`: nobody acknowledges → `ack_timeout` logged, ladder
  escalates to supervisor + dial (the delayed/no-response path)

Ack-link env:

- `PUBLIC_BASE_URL`: base for ack links embedded in pages (defaults to empty;
  set to your deployed origin, e.g. `https://careladder.example`)

## Family chat P1 (Telegram)

The family runtime is the Telegram thread, not the web console. P1 ships the
conversation FSM (`BotThread`) and Telegram adapter v2 (inline buttons +
numbered replies + the existing `GET /ack/{token}` fallback). WhatsApp
templates (P2), the console re-roll (P3), and `/status` commands (P4) are
not in this phase.

Env (Render dashboard → Environment, or `.env` locally):

| Variable | Required for live send | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token. Unset = honest stub, no outbound HTTP |
| `TELEGRAM_CHAT_ID` | yes | Household chat/group id. Unset = stub |
| `TELEGRAM_MODE` | no | `poll` (default, demo) or `hook` |
| `TELEGRAM_HOOK_URL` | hook mode | e.g. `https://<service>.onrender.com/telegram/webhook` |
| `TELEGRAM_WEBHOOK_SECRET` | hook mode (live) | Shared with Telegram `setWebhook(secret_token=...)`. Required once `TELEGRAM_BOT_TOKEN` is set; `POST /telegram/webhook` checks `X-Telegram-Bot-Api-Secret-Token` (fail closed). |
| `FAMILY_PLAN_PATH` | no | defaults to `configs/demo_family.yaml` |
| `PUBLIC_BASE_URL` | for ack-link | origin embedded in the fallback link |

Smoke a live Telegram demo on Render:

1. Create a bot with BotFather, add it to the family chat, copy the token and chat id.
2. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_MODE=poll` (or `hook` + `TELEGRAM_HOOK_URL`).
3. Set `PUBLIC_BASE_URL` to the public `https://` origin so ack-link fallbacks work.
4. Redeploy / restart the web service.
5. `POST /demo/run` with `{"fixture":"family_telegram_page"}` (home demo login if auth is on).
6. In Telegram: tap **I'm on it. I'll call her myself** (or reply `1`). First tap wins; the ack-link in the card is the same window.
7. `GET /incidents/{id}` should show `bot` events with `at` timestamps and `resolve.reason: caretaker_ack`. If nobody taps within ~20s the stub dial rung still runs.


Webhook auth: when the bot token is set, forged updates without a matching `X-Telegram-Bot-Api-Secret-Token` are rejected (`ok: false`) without applying an ack. Set `TELEGRAM_WEBHOOK_SECRET` on Render for live hook mode.
Without token/chat_id the fixture still runs: the audit trail records `adapter: stub` and never claims a Telegram delivery.

## Honesty notes

- `DialerChannel` is a stub: numbers dialed are reserved fictional
  (`(555) 010-xxxx`); Slack notify is a real incoming webhook when
  `SLACK_WEBHOOK_URL` is set, otherwise a logged stub.
- Multi-channel pages (Teams / WhatsApp / Telegram) follow the same convention:
  real HTTP delivery only when that channel's env credentials are set
  (`TEAMS_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`,
  `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_TO`); otherwise the
  audit trail records `adapter: stub` and delivery is simulated. WhatsApp uses
  the Cloud API text endpoint. Production business-initiated messaging needs
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
