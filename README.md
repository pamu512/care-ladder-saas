# Care Ladder SaaS (Galuxium Nexus V2)

Multi-tenant hosted SaaS build of [Care Ladder](https://github.com/pamu512/opencv-care-ladder) for the
[Galuxium Nexus V2](https://galuxium-nexus-v2-29411.devpost.com/) hackathon (deadline Oct 31, 2026 IST).

Forked from the OpenCV AI Competition 2026 build at commit `87b6f3e`. The upstream repo remains the
OpenCV submission; this repo diverges here with tenancy, facility workflows, and billing.

## What this fork adds (per spec)

- Multi-tenant Postgres (`Tenant`/`User`/`IncidentRow`/`AuditEventRow`/`Subscription`) behind a
  `PostgresAuditStore` that preserves the `AuditStore` surface
- Session-cookie auth with `tenant_id` on every query; home vs facility tenant modes
- Facility care plan (`configs/demo_facility.yaml`): `notify_channel` (Slack webhook, stubbed when
  unset) and `notify_supervisor` rungs between check-in and dial
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
uv pip install -e .
uvicorn care_ladder.api.app:app --port 8000
open http://localhost:8000/           # landing + demo logins
```

Demo accounts (seeded by the bootstrap, also live in auth-less demo mode):

- Home: `demo@careladder.local` / `demo-pass-home`
- Facility: `facility@careladder.local` / `demo-pass-facility`

## Honesty notes

- `DialerChannel` is a stub: numbers dialed are reserved fictional
  (`(555) 010-xxxx`); Slack notify is a real incoming webhook when
  `SLACK_WEBHOOK_URL` is set, otherwise a logged stub.
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
