# Facility-Type Models Design

**Date:** 2026-09-29  
**Repo:** `pamu512/care-ladder-saas`  
**Status:** Brainstorm approved (Galaxium). Ready for user review of this written spec, then Hermes implementation plan.  
**Implement:** Mac Hermes only (no Cursor cloud agents for code).  
**Copy rule:** No em dashes in shipped UI or this doc's user-facing examples.

## Problem

Galuxium Care Ladder SaaS today treats facility as one mode (`home | facility`) with billing plans (`facility_starter` / `facility_growth`). The live floor console (Mockup H) is built for assisted-living / memory-care style ops: spoken check-in, reply classification, cases, staff, Audit.

Buyers and demos need the same ops spine to cover:

1. Daycare (kids)
2. Assisted living
3. Rehab
4. Old-age / memory-care home

Without forking four consoles. The hard shared questions are: how does a lead manage many open incidents at once, and how do they tell one apart from another.

## Goals

1. One facility console; facility type is a **profile pack**, not a separate app.
2. Every open alert/case is distinguishable at a glance by **place + person**, with `CL-####` as the stable handle.
3. Multi-incident work is **admin-configurable** (one focus, pin/peek, multi-own).
4. Spoken check-in is **zone-based**: private/alone places keep today's ladder; designated common areas skip verbal acknowledgement and auto-escalate.
5. Daycare defaults so kids are never asked to acknowledge (classrooms are common).
6. Oct 31 ships a meaningful slice of this model (see cut line), not only a backlog note.

## Non-goals (Oct 31)

- Separate Stripe SKUs per facility type (keep `facility_starter` / `facility_growth`; type is orthogonal).
- Live Slack bot, full PDF/zip audit export (those stay polish stretch).
- Replacing PR #7 UI polish Tasks 0–6; type-model work **shares** the Hermes queue after that docs merge, and may land on the same or a follow-on branch.
- Perfect parity of every cue/KPI for daycare and rehab; thin demo packs are enough for the submit.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Architecture | Approach 1: `facility_type` on tenant + profile pack; one console |
| Types | `daycare_kids` \| `assisted_living` \| `rehab` \| `old_age_home` |
| Identity | Place + person on every row; `human_id` (`CL-####`) under the fold; `incident_id` remains system key |
| Subject fields | Add `subject_id` / `subject_display_name` (and optional `subject_kind`: child \| resident \| patient) on cases and alert DTOs; `room_label` generalized as **place** (`place_label`, keep `room_label` as alias for back-compat) |
| Multi-incident | Admin toggles: `one_focus` (always on), `pin_peek` (up to 3), `multi_own` (staff may hold >1 case). Type packs set defaults |
| Spoken check-in | Owned by **zone kind** on the care-plan map: `private` → spoken ladder; `common` → no verbal ack, auto-escalate up the ladder |
| Daycare | Classrooms / play areas default `common`; no kid acknowledgement path |
| Assisted / rehab / old-age | Private rooms use current ladder; common lounges/halls/gyms/dining use auto-escalate |
| Pack contents | Vocabulary, SLA/ladder defaults, cue allowlist, audit KPI set, staff role names / who can own a case, concurrency defaults |
| Oct 31 must ship | (A) `facility_type` on tenant (B) zone-kind check-in rule (C) place + person on rows (D) multi-incident admin UI at least one-focus + pin/peek (E) thin daycare and/or rehab demo packs |
| Copy | No em dashes |

## Current spine (baseline)

Already in repo (tip around `ae269c1` / prior Mockup H):

- `Incident` + audit events; facility `Case` with `incident_id`, `room_label`, `human_id`, priority, owner, `ack_at` / `closed_at`
- Staff with single `active_case_id`
- Alert Center, Cases, Audit (count KPIs today; register mock in PR #7)
- Tenant: `mode` home\|facility, `plan` billing string; **no** `facility_type`

## Design

### 1. Identity (place + person)

Alert list and case rows render:

```
[P1] Classroom B · Maya Chen          CL-0012 · 2m ago
[P2] Room 12 · Mr. Patel              CL-0013 · handling · Maria
```

- **Place** first, then **person**.
- Missing subject: show place + "Unknown subject" (or type-specific "Unidentified child/resident/patient"), never invent a name.
- Daycare uses the same shape even though there is no spoken check-in.

API: extend case/alert payloads with `place_label`, `subject_display_name`, `subject_kind`. Persist on `CaseRow` (and incident payload or a thin subject join later). Fixtures seed plausible subjects.

### 2. Multi-incident admin

Tenant (or facility settings) JSON, e.g.:

```json
{
  "concurrency": {
    "one_focus": true,
    "pin_peek": true,
    "pin_limit": 3,
    "multi_own": false
  }
}
```

- **One focus:** current UX; list + one detail.
- **Pin/peek:** lead pins up to `pin_limit` open incidents for a compact side panel while assigning.
- **Multi-own:** when true, staff may have multiple `active_case_ids` (primary + parked); when false, keep today's one-case cap.

UI: Admin (or demo settings strip) toggles these. Type packs supply defaults (e.g. daycare: pin_peek on; old_age: one_focus default, pin_peek optional).

### 3. Zone kind and the ladder

Care-plan zones gain `kind: private | common` (YAML key `kind`; store on zone config).

| Zone kind | Behavior |
|-----------|----------|
| `private` | Current ladder: spoken check-in → classify → positive resolve / negative or silence → case |
| `common` | Skip spoken check-in; on cue, open/escalate case (page staff / supervisor per pack) |

Daycare pack: all default zones `common`.  
Other packs: bedrooms/private rooms `private`; lounge, hallway, dining, therapy gym `common`.

Demo fixtures: at least one private-room path and one common-area auto-escalate path for assisted/old-age; daycare fixture only common.

### 4. Facility-type packs

| Pack | Vocabulary | Check-in default | Notes |
|------|------------|------------------|-------|
| `daycare_kids` | child, classroom, teacher | Zones common → auto-escalate | No kid ack |
| `assisted_living` | resident, room, floor lead | Mix private/common | Closest to Mockup H today |
| `rehab` | patient, bay/room, therapist | Mix; clinical role names | Thin demo OK for Oct 31 |
| `old_age_home` | resident, room, floor lead | Mix; memory-care cues | Oct 31 primary demo |

Pack file shape (illustrative): `configs/facility_packs/<type>.yaml` or Python constants loaded at tenant bootstrap. Fields: labels, `sla_ack_sec` / `sla_handling_sec`, cue allowlist, audit KPI keys, role roster template, concurrency defaults.

Signup / demo sign-in: choose facility type (or demo buttons per type). Persist on `Tenant.facility_type`.

### 5. Oct 31 cut line (aggressive)

Must land for submit narrative:

1. `Tenant.facility_type` (+ API + demo picker)
2. Zone `kind` respected in ladder (common auto-escalate; private spoken)
3. Place + person on Alert/Case rows (API + UI)
4. Concurrency settings: one_focus + pin/peek wired; multi_own if schedule allows else flag + toast
5. Thin **daycare** pack and/or **rehab** pack demo (at least one besides assisted/old-age)

Priority if time slips: **2 and 3 before 5**; **1** is cheap and should land early; **4** pin/peek can be minimal (pin chips, not full split panes).

UI polish PR #7 (Audit register, ARIA, breaks, visual) remains critical path; coordinate Hermes so type-model tasks do not block Audit.

## Relationship to other docs

- `2026-09-28-facility-floor-console-mockup-h-design.md`: floor console spine
- `2026-09-29-facility-console-ui-polish-design.md` + plan + Audit mock: polish Tasks 0–6
- This doc: multi-type SaaS layer on that spine

## Open questions (non-blocking)

1. Exact YAML key for zone kind (`kind` vs `occupancy` vs `check_in: spoken|none`).
2. Whether `multi_own` ships behind a flag for Oct 31 if pin/peek slips.
3. Whether daycare and rehab both get thin packs or only daycare plus assisted/old-age.
