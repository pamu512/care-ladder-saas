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
