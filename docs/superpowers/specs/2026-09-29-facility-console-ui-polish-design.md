# Facility Console UI Polish Design

**Date:** 2026-09-29  
**Repo:** `pamu512/care-ladder-saas` (tip baseline `1f14a61`)  
**Status:** Approved backlog from Galaxium UI/UX review (items 2–6). Auth-off facility 500 (N1) is already fixed; this design covers polish only.

## Problem

Mockup H facility console shipped at `/ui/facility/` with cases, staff, breaks, reply classification, CSV export, Vertex option, and quiet-hours chip. The backend remediation waves landed. The console still reads as a dark prototype next to the teal home caregiver console, and several Mockup H affordances never made it into the live UI:

- Alert cards are mouse-only (no keyboard/ARIA/selection).
- Detail and case forms rebuild on every `refresh()`, wiping in-progress edits.
- Owner shows as a raw id fragment (`staff -maria`); close/ack/assign failures are silent.
- Audit KPIs are counts only; outcome keys are raw enums; no per-case ladder story.
- Break is a fixed 15m toggle; `break_until` is returned by the API but never shown.
- Demo fixture buttons sit above real floor UI; empty/loading states point at demos.

## Goals

1. A floor lead can triage alerts with keyboard, see selection, and keep half-typed assign/close state across refreshes.
2. Owners, SLA aging, and action errors are visible without leaking DB ids or enum names.
3. Audit shows time metrics and lets a lead open the cue → reply → page → ack → close story for one case.
4. Break UX supports duration choice and a live countdown from `break_until`.
5. Facility and home consoles share enough tokens and header navigation to feel like one product; demo chrome is quarantined.

## Non-goals

- Live Slack bot (stub thread URLs stay).
- Changing Path A/B home behavior beyond a clearer facility ↔ home link.
- New auth/billing work.
- Auto-polling alerts every N seconds (tip only ticks the clock; keep that unless product asks).
- Pixel-perfect clone of Mockup H HTML; match structure and affordances, not every CSS pixel.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Scope | Facility console primary; home gets shared header link + logo mark only if Task 6 needs it |
| Aging timers | Client computes from `opened_at` ISO on each alert/case; SLA targets stay `sla_ack_sec` / `sla_handling_sec` (defaults 120 / 900) |
| Owner display | API includes `owner_display_name` + `owner_initials` resolved from roster; UI never shows raw `owner_staff_id` |
| Error surface | `japi` callers show `#toast` or inline `.form-error` on non-2xx; close shows live char count |
| Audit times | Extend `FacilityState.summary()` with median time-to-ack, median handling, pct acked in SLA, median resident-response time, group_timeouts count, resolved_by_response fraction |
| Incident drill-down | Replace the simple case-button list with the **closed-case register** mock (`docs/galuxium/mockup-audit-drill-down.html`): expandable rows, outcome filters (Today only for MVP), full ladder transcript + timing rail + evidence + per-case overrides |
| Break durations | Buttons for 15 / 30 / 60 minutes; show `on break · Xm left` from `break_until` |
| Demo chrome | Move fixture buttons into a collapsible `.demo-strip` below the header (default expanded in demo auth-off / demo tenants) |
| Visual unify | Facility adopts shared CSS variables for accent teal + ladder logo SVG from home; keep dark facility surface (floor ops) but same mark, type scale, and chip language |
| Copy | No em dashes (—) in user-facing strings |
| Implement | Mac Hermes only (no Cursor cloud agents for code) |

## API additions (small)

1. `_case_out(c, state)` adds:
   - `opened_at` from `state.case_opened_times().get(c.id)`
   - `owner_display_name`, `owner_initials` from `state.staff.get(c.owner_staff_id)`
   - `sla_ack_sec`, `sla_handling_sec` from the Case model
2. `FacilityState.summary()` adds (match audit mock KPI row):
   - `median_ack_sec`, `median_handling_sec`, `pct_acked_in_sla` (0-100 int)
   - `median_response_sec` (resident-resolved cue→positive reply; null if none)
   - `resolved_by_response` / `resolved_by_response_total` (e.g. 6 of 11)
   - `group_timeouts` (count of cases/incidents with group/ack timeout origin or exhausted paging)
   - `outcomes` stays machine keys; UI maps labels
3. New read endpoint `GET /facility/audit/register` returns today's register rows for the UI:
   - Staff-handled closed cases + resident-resolved incidents (no case)
   - Each row: `kind` (`staff_case`|`resident_resolved`|`group_timeout`), ids, room, title, origin label key, owner display, `ack_sec`, `handling_sec`, `response_sec`, `missed` bool
4. New drill-down route `GET /facility/audit/register/{incident_id}` assembles timeline from the incident + case + overrides + frames.
5. Add optional `AuditEvent.at` and stamp it when new events are appended (backward compatible). Case `ack_at`/`closed_at`/`created_at` already drive KPI medians; do not invent clocks for old unstamped events.
6. Staff `break_until` already returned; client computes countdown.
7. **Stretch (not blocking):** PDF/zip exports, 7-day / shift range queries, richer nudge analytics.

## UI structure changes

**Alert center**

- Cards: `role="button"`, `tabindex="0"`, `aria-selected`, Enter/Space activates, `.alert.selected` style.
- Show aging chip: `aging Xm` and, if under SLA window, `Ym to ack target`.
- `refresh()` / `loadDetail()`: preserve `#assign-select` value, `#pull_off_break` checked, and priority only re-apply server truth without rebuilding the whole form if the same incident is selected and the user has dirty local state (`state.detailDirty`).

**Cases**

- Owner: `MG · Maria G.` (initials + name) or `unassigned`.
- Live SLA line: time since open; if `ack_at`, time-to-ack vs target; if closed, handling duration.
- Close textarea: `n/20` counter; on 422 show message under the field.
- Ack/assign failures toast.

**Staff**

- Break control: `15m` / `30m` / `60m` when available; `End break` when on break.
- Status chip: `on break · 18m left` when `break_until` is in the future.

**Audit** (visual source: `docs/galuxium/mockup-audit-drill-down.html`)

- KPI row: 6 boxes matching the mock (resolved-by-response fraction, median response, median ack, % acked in window, median handling, group timeouts) with good/warn/bad/vio coloring heuristics.
- Closed-case **register** (not a flat button list): expandable `.reg` rows with caret, human id, room/title, origin chip, owner, ack/handling mono times.
- Filter chips (client-side for Today MVP): All / Staff-handled / Resolved by response / Negative replies. Range chips Today (on) / 7 days / Shift are visible but only Today is wired; others show toast "Coming soon" unless stretch lands.
- Expanded body: two columns. Left = Care Ladder incident report (ordered events from `/incidents/{id}`, humanized tool names, reply quotes from detail, documentation block). Right rail = Timing (vs SLA targets), Evidence (frame count + stub chat link), Overrides on this case, actions (Open chat thread stub; Export PDF stretch).
- Lead actions card: today's override ledger (from `state.overrides`) + Export audit CSV (existing). Per-shift PDF and zip are stretch buttons (disabled or toast).
- Ship **no em dashes** even if the static mock contains them.

**Chrome**

- Header: Facility floor console ↔ Caregiver console both first-class.
- Prefer `/ui/facility/` (trailing slash) in all links.
- Demo strip collapsible; empty alert copy: `Floor clear. No open alerts.` (no demo pointer).
- Soft loading: opacity/skeleton on queue while first `refresh()` in flight.

## Acceptance (manual)

1. Tab to an alert, Enter selects it; selected card has visible ring.
2. Start typing close docs, click Acknowledge on another case's button path that triggers refresh: selected alert's assign select still holds previous choice if dirty.
3. Assign Maria: owner reads `MG · Maria G.`, not `staff -maria`.
4. Close with 10 chars: inline error; with 20+: case closes.
5. Audit KPIs show median ack after ack+close; register lists the closed case; expanding it shows ladder transcript + timing rail + docs.
6. Filter chip "Resolved by response" hides staff cases after a positive fixture.
7. Put Jamie on break 30m: countdown visible and ticks with the header clock.
8. Side-by-side home vs facility: same logo glyph and teal accent; facility stays dark.

## Out of scope follow-ups

- Full light-theme facility option.
- Real SLA config per tenant YAML.
- Screen-reader live regions for new P1 arrivals.


## Audit tab replacement (from review mock)

The Audit tab is not a KPI strip plus a flat case list. It becomes the management review surface:

1. **Time-metric KPIs** (presentation over persisted `ack_at` / `closed_at` / response timing): median time-to-ack, % acked in window, median handling, median resident-response time, group timeouts, resolved-by-response fraction.
2. **Closed-case register**: filterable expandable rows (id, room + outcome chip, owner display name, ack + handling at a glance). Resident-resolved incidents are first-class violet rows ("no staff action").
3. **Drill-down**: full ladder transcript (timestamps/deltas when available), documentation + signature, timing rail vs SLA targets, evidence (frames + chat stub), per-case overrides, export actions.
4. **Lead-actions** card: today's overrides + CSV export (PDF/zip stretch).

Visual: `docs/galuxium/mockup-audit-drill-down.html`.
