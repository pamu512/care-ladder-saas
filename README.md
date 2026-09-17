# Care Ladder - Development

Non-SaaS development branch of [Care Ladder](https://github.com/pamu512/opencv-care-ladder).
Forked from the OpenCV AI Competition 2026 build at commit `87b6f3e` (repo name predates the
repurpose). This is the playground for anything that is NOT the OpenCV submission and NOT the
Galuxium SaaS filing: experiments, vision work, tooling, spikes.

The upstream `opencv-care-ladder` repo stays the clean, deployed OpenCV submission (deadline
Oct 26). The Galuxium SaaS plan (`docs/superpowers/plans/2026-09-17-galuxium-care-ladder-saas.md`)
is parked here for reference but is NOT being executed in this repo.

## Development notes (originally the SaaS fork scope, kept for reference)

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
