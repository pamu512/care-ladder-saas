# PDD: Facility ops spine (cover and respond)

**Status:** Draft for Anoop. Docs only. Uncommitted. Decisions locked 2026-10-05 by Anoop. Ready for Anoop to review whether to build.

**Pairs with:** `docs/galuxium/prd-full-product-ops-spine.md`.

**Voice:** Facility first. Lean assisted living, memory care, and small residential sites. Home at $9/mo is excluded from this spine. Rehab is post-MVP.

**Live:** https://care-ladder-saas.onrender.com

**Basis (read 2026-10-05, files not modified):**

- Branch `feat/break-aware-auto-routing` at `3c6468f`. Break-aware routing on this branch is `2fcaecb`. Approximate main tip: `origin/main` `645ccd9`. Devpost draft cites `de91406` as the break-aware main commit. Those three docs and Mockup H stay as they are.
- This PDD describes deltas against the code that is in the tree. It does not add tables, routes, or copy in the product.

**Scope lock:** Dementia and memory-care facility plans on the existing care-ladder-saas app. `RoutineProfile` is named only as a CareCV / Alexa+ touchpoint and does not affect layer 2. Soft cue `fall_cls_v1.onnx` is non-clinical (file not in this repo). Confirm-first applies on the on-duty private path. CV training data, when training happens, is Kaggle fall plus CV-tag only, and only after the false-page unlock in the PRD.

## Information architecture

The facility console already has one shell. Layer 2 lives in that shell. Layer 3 does not add a second app.

Current nav (`src/care_ladder/api/static/facility/index.html`):

| View | What it is today | Layer 2 role |
| --- | --- | --- |
| Overview | Counts, including staff available of roster size | Shows live cover: on duty, on break, on call, backup. |
| Alert center | Triage, assign, overrides | Assign uses live state. Spoken confirm-first stays on the on-duty private path. A page to on-call backup is a straight page. |
| Cases | `paged`, `handling`, `wrapping`, `closed` | Handoff note sits on the open case, then on the audit. |
| Audit | Ladder rows, overrides, outcomes | Each page row names who was paged and stub vs delivered. Retention defaults to 3 years; the owner may extend it. |
| People | Derived residents (and other subjects) from seeds plus cases | Unchanged directory. Family is excluded from daily ops. |
| Places · cameras | Zones from the care plan, plus case places | Shows existing `zone_kind` (`private` or `common`). Escalation policy binds per place on that kind. |
| Staff · shifts | Roster and break toggle | Live staffing state. Only the owner or the floor lead may edit on duty, on break, on call, and backup. The word "shifts" on this tab is the current label. It is not a shift planner. |
| Channels | Slack, Teams, WhatsApp, Telegram tiles and delivery rows | Teams webhook is the preferred real path and shows here as live or stub. Voice stays stubbed until a pilot asks for dial. |
| Plan · billing | `home` / `facility_starter` / `facility_growth` | Facility Growth (`facility_growth`, $99) owns layer 2. Starter does not get layer 2 in this draft. Home is excluded. Seat, place, and camera caps stay as published. |
| Settings | Facility settings already on the tenant | Escalation policy binds per place (`Zone.kind` private vs common). No site-wide override. |

Home console stays the household path. It is not a screen in this spine.

**Term split (required):** staffing **on call** is availability on Staff · shifts. `BotThread.on_call_result` (`src/care_ladder/channels/bot.py`) is a **call outcome** (`answered` closes the family thread; other statuses climb `calling_N`). The Channels and Audit views must not label a call outcome as the staffing flag.

## Key screens and flows

Flows below are the layer 2 behavior. All four ship in parallel: live staffing state, handoff notes, private/common policy, and a real voice or Teams path. The real path prefers the Teams webhook. Voice stays stubbed until a pilot asks for dial. None of the four is scheduled ahead of the others.

### 1. Set live cover

Floor surface: Staff · shifts.

Today a member is `available`, `on_case`, or `on_break`, with `break_until` and a break API (`on_break`, `minutes`). `on_case` means they already own a case. `pick_assignee` skips `on_break` and `on_case`. A lead may `pull_off_break`; that writes `facility_override_events`.

Layer 2 adds the live words **on duty**, **on break**, **on call**, and **backup** on that same roster. `on_case` remains occupancy of a case, not a synonym for on call. Only the owner or the floor lead may edit the four live states. Backup is registered staff only (already on the facility roster). Sister-site and agency staff are not backup until they are registered staff on that roster. On call is a live availability flag. Rotations are layer 3. The screen must show the state that routing will actually use, including break time still in force.

### 2. Cue, confirm, page

1. A soft cue arrives (today: `no_movement`, `no_visibility`, `distress_heuristic`). `fall_cls_v1.onnx` is the named non-clinical cue for later training, after the false-page unlock.
2. **Private place** (`Zone.kind == private`): spoken confirm-first (`speaker_prompt`) and the wait the plan already defines, on the on-duty path. Positive resolve does not open a case.
3. **Common place** (`Zone.kind == common`): the ladder already skips the spoken check-in, writes the skip on the audit, and continues to notify. Layer 2 policy binds per place on that kind. It does not add a site-wide override.
4. If the cue still needs a person, open or reuse the case (`CL-####`, priority, place label, subject).
5. Pick from live state. On duty and assignable wins. On break is skipped unless the logged lead override runs. On call / backup is the next honest target when on-duty cover is empty. The backup target must already be registered staff on this roster. Rotations are layer 3.
6. Page through the channel path below. Prefer the Teams webhook. The audit row stores who was paged, the case id, the place, and stub vs delivered.
7. When the page target is on-call backup, confirm-first does not apply (straight page). Private-place spoken confirm-first still applies on the on-duty path.

### 3. Handoff

On the case, the caregiver leaving writes a handoff note before the next owner is assigned or before close. Today's `Case.documentation` is the close string (minimum 20 characters). It is not a mid-case handoff field. The note and the staffing state at page time are appended to the case audit (incident `audit_event_rows` and, for lead overrides, `facility_override_events`). Retention of those audit rows defaults to 3 years. The owner may extend it.

### 4. On-call page

When no on-duty member is assignable, the router may page the member marked on call or backup, if that member is registered staff on this facility roster. The page is straight: confirm-first does not run. The page text stays in the honest style `build_page_message` already uses: name, role, case human id, priority, place, subject, and a lead-override phrase when that override fired. Delivery prefers the Teams webhook (`TeamsAdapter` / `TEAMS_WEBHOOK_URL`). The row still records who was paged and stub vs delivered. A call outcome from the family bot is never written into this flag.

## Data-model deltas

Deltas against today's queue, places, and people. No new schema is settled here beyond the fields that already exist. Proposed additions are named as gaps. This PDD does not add tables or column types. Retention defaults to 3 years; the owner may extend it. Only the owner or the floor lead may edit on duty, on break, on call, and backup.

### Work queue today

There is no shift table. The queue is:

- `Case` / `facility_cases`: `human_id`, `incident_id`, `room_label`, `place_label`, `subject_display_name`, `subject_kind`, `subject_id`, `origin`, `priority`, `state`, `owner_staff_id`, stub `slack_thread_url`, `ack_at`, `closed_at`, `documentation`.
- `StaffMember` / `facility_staff`: `status` in `available | on_case | on_break`, `break_until`, `active_case_id`, `parked_case_ids`.
- `facility_override_events`: lead actions, including `pull_off_break`.
- `audit_event_rows`: incident timeline (`tool`, payload), tenant scoped.

### Places today

No place table. `build_places` (`src/care_ladder/facility/directory.py`) builds rows from care-plan `Zone` objects plus open-case labels.

`Zone` (`src/care_ladder/models.py`) has `id`, `polygon`, and `kind: private | common` (default `private`). The places view exposes that as `zone_kind`. Common zones use silhouette privacy; private zones use blur. A case place that is not a plan zone is emitted with `zone_kind: private`. That is a display default, not a stored operator choice.

**Place type exists** at zone level (`Zone.kind` / places `zone_kind`). It does not exist as a site-wide column. `Tenant.facility_type` is a different field (`assisted_living`, `old_age_home`, `daycare_kids`, `rehab`) and is not private vs common. Layer 2 escalation policy binds per place on `Zone.kind` (private vs common). There is no site-wide override. This PDD does not add a second place-type enum.

### People today

No person table. People rows are merged from facility-type seeds and from case subject fields (`subject_id`, `subject_display_name`, `subject_kind`). Memory-care subjects in the assisted-living seed are residents. Family is not a staff row. Backup must already be a staff row on this facility roster.

### Layer 2 gaps (not implemented)

| Gap | Today | Layer 2 need |
| --- | --- | --- |
| Live staffing | `available`, `on_case`, `on_break` | on duty, on break, on call, backup, without collapsing `on_case` or `on_call_result` into "on call". Editors: owner or floor lead only. On call is a live flag. |
| Handoff | Close `documentation` only | A note during handoff, copied onto the case audit. Retention defaults to 3 years; the owner may extend it. |
| Place policy | `Zone.kind` already changes spoken check-in | Escalation cover binds per place on that kind. No site-wide override. |
| Page audit | Notify payload can say stub or slack | Stable fields: who was paged, confirm-first result on the on-duty private path, adapter result (stub vs delivered). |
| On-call rotation | Absent | Layer 3. Layer 2 on call is a live availability flag only. |

### Layer 3 gaps (not in the MVP model)

Shifts, open slots, rotation rows, swap requests, overtime caps, compliance records, BAA, and the staffing-ratio engine. Do not add them to `facility_staff` in the layer 2 work. Home $9 is excluded from this spine.

## Channel and voice integration

Current notify adapter used by break-aware assign: **`NotifyChannelAdapter`** in `src/care_ladder/channels/notify.py`, called from `page_assignee` / `assign_and_page` / `auto_route` / `repage_case`.

| Path | Live when | Otherwise |
| --- | --- | --- |
| `NotifyChannelAdapter` | `SLACK_WEBHOOK_URL` set; result `adapter: slack` | `adapter: stub`, `delivered: true` on the stub payload (honest stub, not a claim of Slack) |
| `TeamsAdapter` (`src/care_ladder/channels/router.py`) | `TEAMS_WEBHOOK_URL` set | Stub via the webhook adapter base |
| `PageRouter` | Also constructs Slack, Teams, Telegram, WhatsApp adapters for plan-routed pages | Unknown channel ids stub |
| `StubDialer` (`src/care_ladder/channels/dial.py`) | Never a carrier call | Scripted dial result only |
| Family `BotThread` | Chat FSM; voice hops reuse the dial stub | `on_call_result` is the call outcome, not staffing |

Routing's page path today is `NotifyChannelAdapter`, not `TeamsAdapter` and not `StubDialer`. Teams and WhatsApp appear on the Channels screen through `channel_active_envs()`. A case `slack_thread_url` is still a stub URL (`example.invalid` in `Case.open_from_incident`).

**Layer 2 delivery boundary:** prefer the Teams webhook first (`TeamsAdapter` / `TEAMS_WEBHOOK_URL`). The Facility Growth tenant admin (owner) owns that webhook, not Galuxium. Voice (`StubDialer`) stays stubbed until a pilot asks for dial. The audit row records (1) who was paged, (2) that spoken confirm-first ran on the on-duty private path, and that a page to on-call backup was a straight page, (3) the adapter id and delivered or stub. That is the whole boundary. Missing `TEAMS_WEBHOOK_URL` means stub. This PDD does not retarget today's `NotifyChannelAdapter` call in product code.

Out of this boundary: a PBX, a Teams app package, a second notification product, and any new bot whose job is only paging.

## How it sits on existing care-ladder-saas

One FastAPI app, session auth, Postgres, tenant id on facility rows and audit queries. Render host above. Stripe plan ids `home`, `facility_starter`, `facility_growth`. Facility notify stays behind `tenant_can_use_notify` (plan `home` does not notify). Home is excluded from this spine.

Layer 2 is a change in meaning on objects that already exist, packaged on `facility_growth` ($99). `facility_starter` does not get layer 2 in this draft. Seat, place, and camera caps stay as published.

- Staff roster and `assign_and_page` gain live state and still skip break without a logged override. Editors are the owner or the floor lead.
- Cases gain a handoff the audit can show next to close documentation. Audit retention defaults to 3 years; the owner may extend it.
- Places already expose `zone_kind`; cover policy binds per place on it. No site-wide override.
- The preferred real send is `TeamsAdapter` when the owner has set `TEAMS_WEBHOOK_URL`. Channels already distinguish live env vs stub.
- Overview, Alert center, Cases, Audit, and Staff · shifts are the screens. No new console.

Demo honesty stays: seeded tenants, fixture cues, stub when secrets are unset. Layer 1 false-page measurement is a pilot readout, not a new model drop. `fall_cls_v1.onnx` is not shipped in this repo. Further training waits on the false-page unlock (7-night one-wing pilot, ≥200 soft cues, false-page rate above 15%, or the floor lead says noise is the top complaint) and uses Kaggle fall plus CV-tag only.

Published prices ($9 / $49 / $99) and the briefing's seat and retention lines stay packaging. Layer 2 is assigned to `facility_growth` only.

## RoutineProfile touchpoints

`RoutineProfile` does not exist in this repository (no type, table, or config key). The only touchpoint this PDD names is the shared name with **CareCV** and **Alexa+** for dementia and memory-care plans.

Locked 2026-10-05: `RoutineProfile` does not affect layer 2. No fields, no storage, no escalation input. Routing, confirm-first, and audit do not read a routine profile.

## Non-goals

- Full HRIS.
- Clinical scoring, diagnosis, or medical-device behavior. No HIPAA certification claim.
- Face recognition.
- Rehab in this MVP.
- Layer 3 planner (shifts, slots, rotations, swaps, overtime, compliance) before one site is sticky on layer 2 (30 nights meeting the cover metrics). BAA and the staffing-ratio engine stay out until layer 3.
- PBX, Teams app package, or a second notification product.
- An invented `RoutineProfile` schema, or any layer 2 effect from that name.
- Family inside the daily facility loop. Home $9 is excluded from this spine.
- Treating `on_call_result` as staffing state.
- A named pilot site. Thresholds are the PRD success metrics.
- Sister-site or agency backup for anyone who is not registered staff on that roster.
- A site-wide override of per-place policy.
- Changing seat, place, or camera caps in this draft.
- Live voice before a pilot asks for dial. `StubDialer` stays stubbed until then.

## Phased rollout

1. **One site, 30 nights, layer 2.** All four in parallel: live cover and the on-call flag, handoff on the case audit, per-place policy using existing `Zone.kind`, and a Teams webhook send (`TeamsAdapter` / `TEAMS_WEBHOOK_URL`) with who-paged plus stub vs delivered. Confirm-first stays on the on-duty private path. On-call backup is a straight page. Voice stays stubbed unless that pilot asks for dial. Editors are the owner or the floor lead. Backup is registered staff on that roster. Do not train further fall cues in this phase.
2. **Same site, sticky.** Hold until the cover metrics say layer 2 is in daily use: median time-to-ack ≤ 3 min on pages that land on on-duty cover, uncovered nights (no on-duty and no on-call set at 22:00 local) = 0, ≥80% of open cases get a handoff note before owner change or close, and stub vs delivered labeled correctly on 100% of audit page rows.
3. **Layer 3 on that site.** Shifts, open slots, on-call rotations, swap requests, overtime caps, compliance records. BAA and the staffing-ratio engine stay out until this phase.
4. **Further fall cues.** Only after the false-page unlock: 7-night one-wing pilot, then ≥200 soft cues with false-page rate (cue → page → closed as not needed / resident fine) above 15%, or the floor lead says noise is the top complaint. Measure: cues, pages, ack time, close reason. Data: Kaggle fall plus CV-tag only.

Home $9 and the family console are excluded from this spine. They are not a phase of this rollout.

## Resolved decisions (locked 2026-10-05 by Anoop)

Same lock as the PRD.

1. **Layer 2 ships all four in parallel:** live staffing state, handoff notes, private/common policy, and a real voice or Teams path. No first-cut vs fast-follow split.
2. **On call** is a live availability flag only. Rotations are layer 3.
3. **Packaging:** layer 2 is Facility Growth ($99). This draft does not change seat, place, or camera caps.
4. **Home $9** is excluded from this spine.
5. **Editor:** only the owner or the floor lead may edit on duty, on break, on call, and backup.
6. **Backup** is registered staff only (already on the facility roster). No sister-site or agency backup until that person is registered staff on that roster.
7. **Audit retention** defaults to 3 years. The owner may extend it.
8. **Escalation policy** binds per place (`Zone.kind` private vs common). Not a site-wide override.
9. **False-page unlock:** 7-night one-wing pilot. More `fall_cls_v1.onnx` training only after ≥200 soft cues with false-page rate (cue → page → closed as not needed / resident fine) above 15%, or the floor lead says noise is the top complaint. Measure: cues, pages, ack time, close reason. Dataset: Kaggle fall + CV-tag only.
10. **`RoutineProfile`** does not affect layer 2.
11. **Confirm-first** does not apply when paging on-call backup (straight page). Private-place spoken confirm-first still applies on the on-duty path.
12. **Channel:** prefer the Teams webhook first (`TeamsAdapter` / `TEAMS_WEBHOOK_URL`). Voice (`StubDialer`) stays stubbed until a pilot asks for dial. The webhook is owned by the Facility Growth tenant admin (owner), not Galuxium.
13. **BAA and the staffing-ratio engine** stay out until layer 3. Care Ladder is not a medical device. No HIPAA certification claim.
14. **Layer 2 pilot success** (one site, 30 nights): median time-to-ack ≤ 3 min on pages that land on on-duty cover; uncovered nights (no on-duty and no on-call set at 22:00 local) = 0; ≥80% of open cases get a handoff note before owner change or close; stub vs delivered labeled correctly on 100% of audit page rows. The false-page unlock remains decision 9.

### Still open

None.
