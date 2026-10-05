# PRD: Facility ops spine (cover and respond)

**Status:** Draft for Anoop. Docs only. Uncommitted. Decisions locked 2026-10-05 by Anoop. Ready for Anoop to review whether to build.

**Voice:** Facility first. Lean assisted living, memory care, and small residential sites. Home at $9/mo is excluded from this spine. Rehab is post-MVP.

**Live:** https://care-ladder-saas.onrender.com

**Basis (read 2026-10-05, files not modified):**

- Working branch `feat/break-aware-auto-routing` at `3c6468f` (`3c6468fd60ecf1551db511be01dfacdd1d5d5ed2`, test alignment on top of break-aware routing commit `2fcaecb`).
- `origin/main` ref `645ccd9` (`645ccd99cf802057ce9b3e84d820184fdeea27fa`), treated as the approximate main tip.
- `docs/galuxium/devpost-draft.md` names `de91406` as the break-aware commit on main (PR #24). This PRD does not rewrite that draft, `docs/galuxium/executive-briefing.md`, or Mockup H.
- Code read: `StaffMember` / `Case` in `src/care_ladder/facility/models.py`, break-aware assign in `src/care_ladder/facility/routing.py`, tables in `src/care_ladder/db/models.py`, plan ids in `src/care_ladder/billing/plans.py`, `on_call_result` in `src/care_ladder/channels/bot.py`, routing tests in `tests/test_facility_routing.py`.

**Scope lock:** Dementia and memory-care facility plans. `RoutineProfile` is a shared touchpoint with CareCV and Alexa+ (the name is absent from this repo; no schema is specified here). It does not affect layer 2. Soft cue `fall_cls_v1.onnx` is non-clinical. Confirm-first applies on the on-duty private path. That filename is not in this repo. Any CV training uses Kaggle fall plus CV-tag data only, and only after the false-page unlock below.

## Problem

A small memory-care or assisted-living floor cannot keep a person on a camera wall through nights and weekends. Raw motion is noisy. A page that nobody can cover is also noise.

Layer 1 is largely already in the hosted product. A cue can run a confirm-first check-in, open a case, page an on-duty assignee, skip staff on break unless a lead logs `pull_off_break`, and write an audit row. The roster statuses that exist today are `available`, `on_case`, and `on_break`.

The gap is cover. The floor cannot record, in the product, who is on duty right now, who is the on-call backup, or what the person leaving the case needs the next person to know. When everyone assignable is on break or already on a case, auto-route stops. The lead override and a stub notify are the honest leftovers. Planning shifts, rotations, and overtime before that live cover works would schedule a floor the product still cannot see.

## Users

Daily facility ops has four roles. Family is excluded from this spine.

| Role | Job on this spine |
| --- | --- |
| Owner-operator | Holds the site plan, checks that tonight has cover, reads the audit after an incident. May edit on duty, on break, on call, and backup. May extend audit retention past the 3-year default. Owns the Facility Growth Teams webhook. |
| Floor lead | Sees who can take a page now. May edit on duty, on break, on call, and backup. Uses the logged pull-off-break override when that is the only honest assign. Reads handoff notes. |
| On-duty caregiver | Receives the page, confirms on the private-place path, handles the case, leaves the handoff. |
| On-call backup | Registered staff already on this facility roster. The ladder may straight-page them when on-duty cover is not assignable. |

Family stays off the daily facility loop. The floor does not depend on a family member to close cover. Only the owner or the floor lead may edit on duty, on break, on call, and backup. Backup is registered staff only: the person must already be on the facility roster. Sister-site and agency staff are not backup until they are registered staff on that roster.

## Goals and non-goals

### Three layers (locked)

1. **Detect and escalate (mostly exists).** Camera soft cues, confirm-first check-in on the private path, break-aware paging, cases, audit. More fall-cue training waits on the false-page unlock (7-night one-wing pilot, then ≥200 soft cues with a false-page rate above 15%, or the floor lead says noise is the top complaint).
2. **Cover and respond (MVP).** All four ship in parallel: live staffing state (on duty, on break, on call, backup), handoff notes, private/common policy bound per place, and a real voice or Teams path. Prefer the Teams webhook first (`TeamsAdapter` / `TEAMS_WEBHOOK_URL`). Confirm-first is still required on the on-duty private path. A page whose target is on-call backup is a straight page. The audit row names who was paged.
3. **Plan the cover (later).** Shifts, open slots, on-call rotations, swap requests, overtime caps, compliance. BAA and the staffing-ratio engine stay out until this layer. Starts only after layer 2 is sticky at one site (30 nights meeting the cover metrics).

### Goals

- Keep layer 1 behavior that already ships: break-aware `pick_assignee` / `assign_and_page`, case states `paged | handling | wrapping | closed`, close documentation, tenant-scoped audit.
- Add layer 2 live cover on the existing facility console (Mockup H surfaces already in the app: Overview, Alert center, Cases, Audit, People, Places · cameras, Staff · shifts, Channels, Plan · billing, Settings).
- Keep the soft fall cue non-clinical. Spoken confirm-first stays on the on-duty private-place path. A page to on-call backup does not wait for confirm-first.
- Keep delivery honest. Prefer Teams webhook first. Stub stays labeled stub until that webhook delivers. Voice (`StubDialer`) stays stubbed until a pilot asks for dial.
- Keep staffing language and phone-call language apart (see below).

### Non-goals

- Layer 3 inside the MVP. BAA and the staffing-ratio engine stay out until layer 3.
- A full HRIS (payroll, credentials, hiring).
- Clinical scores, diagnosis, or medical-device claims. No HIPAA certification claim.
- Face recognition.
- Rehab workflows in this MVP. A rehab demo pack exists in the repo; it is outside this spine.
- A PBX, a Microsoft Teams app package, or a second notification product.
- A `RoutineProfile` schema, or any effect of that touchpoint on layer 2.
- Family as a daily facility rung. Home $9 is excluded from this spine.
- A named pilot site. Layer 2 success is one site for 30 nights.
- Sister-site or agency backup for anyone who is not registered staff on that facility roster.
- A site-wide override of per-place escalation policy.
- Changing seat, place, or camera caps in this draft.

### Staffing "on call" and `on_call_result`

These are different records.

- **Staffing state `on call`** is a live availability flag for layer 2 cover: this person can be paged as backup. It does not exist on `StaffMember.status` today. Rotations are layer 3.
- **`BotThread.on_call_result`** in `src/care_ladder/channels/bot.py` is a **call outcome** on the family bot thread. Status `answered` closes the thread. Any other status climbs `calling_1` / `calling_2` / `calling_3`. It does not mean the person is the facility on-call backup.

`on_case` today means the staff member already owns a case. `pick_assignee` skips `on_case` and `on_break`. That occupancy flag stays a case fact. It is not the new on-call flag.

## Success metrics

Layer 2 pilot: one site, 30 nights. Thresholds below are locked (2026-10-05).

| Metric | What it watches | Threshold |
| --- | --- | --- |
| Time-to-ack | Median time-to-ack on pages that land on on-duty cover | ≤ 3 min |
| Uncovered nights | Nights with no on-duty and no on-call set at 22:00 local | 0 |
| Handoff present | Open cases that get a handoff note before owner change or close | ≥80% |
| Honest delivery | Audit page rows labeled stub vs delivered correctly | 100% |
| Layer 2 sticky | One site on live cover | 30 nights meeting the four cover metrics above |
| False-page unlock | More training of `fall_cls_v1.onnx` | 7-night one-wing pilot. Further training only after ≥200 soft cues with false-page rate (cue → page → closed as not needed / resident fine) above 15%, or the floor lead says noise is the top complaint. Measure: cues, pages, ack time, close reason. Dataset: Kaggle fall + CV-tag only. |

## MVP: layer 2 only

Layer 2 is the MVP. All four ship in parallel: live staffing state, handoff notes, private/common policy, and a real voice or Teams path. There is no split that ships some of them later.

### Already in the product (layer 1)

- Cues in code: `no_movement`, `no_visibility`, `distress_heuristic`. Vision path is upload and fixture-driven analysis. ONNX weights referenced by the app are MediaPipe person detection and pose (`person_detection_mediapipe_2023mar.onnx`, `pose_estimation_mediapipe_2023mar.onnx`). `fall_cls_v1.onnx` is the named future soft cue, not a file in this tree.
- Private zones run spoken check-in (`speaker_prompt`). Common zones skip that spoken check-in and continue up the ladder (`Zone.kind`).
- Break-aware auto-route pages through `NotifyChannelAdapter` (Slack incoming webhook when `SLACK_WEBHOOK_URL` is set; otherwise `adapter: stub`).
- Lead `pull_off_break` is logged on `facility_override_events`.
- Cases require a documentation string of at least 20 characters to close.
- Telephony is `StubDialer`. Facility case thread URLs are stub links. Teams is a channel catalog entry plus `TeamsAdapter` (`TEAMS_WEBHOOK_URL`); unset means stub.
- People and places are derived console views, not their own tables.

### Layer 2 adds

- Live staffing state the floor can set and the router can read: **on duty, on break, on call, backup**. Only the owner or the floor lead may edit those four. On call is a live availability flag. Backup is registered staff already on the facility roster. Rotations are layer 3.
- Handoff notes a receiving caregiver can read, stored with the case audit. Audit retention defaults to 3 years. The owner may extend it.
- Escalation policy bound per place, using `Zone.kind` (`private` vs `common`). There is no site-wide override.
- One real delivery boundary, Teams webhook first: `TeamsAdapter` when `TEAMS_WEBHOOK_URL` is set. The Facility Growth tenant admin (owner) owns that webhook, not Galuxium. Voice (`StubDialer`) stays stubbed until a pilot asks for dial. Confirm-first still runs on the on-duty private-place path. A page to on-call backup is a straight page. The audit names who was paged and records delivered or stub. No new notification product.

More fall-cue training is not part of the MVP. It waits on the false-page unlock in Success metrics.

Packaging for this layer is Facility Growth (`facility_growth`, $99/mo per site). See Pricing fit.

## Layer 3 later

After layer 2 is sticky at one site (30 nights meeting the cover metrics), the same console can grow planning:

- Shifts and open slots
- On-call rotations (layer 2 on call stays a live availability flag only)
- Swap requests
- Overtime caps
- Compliance records. BAA and the staffing-ratio engine stay out until this layer

The current **Staff · shifts** screen is a roster and break toggle. It is not this planner. Building the planner first would put a schedule on top of statuses that still cannot say on call or backup.

## Pricing fit

Code plan ids: `home`, `facility_starter`, `facility_growth` (and `demo` for the judge tenant). Checkout prices named in the Devpost draft and executive briefing:

| Plan id | Published price | Published inclusion (briefing) |
| --- | --- | --- |
| `home` | $9/mo per household | 1 household, 2 seats, home ladder, full audit trail |
| `facility_starter` | $49/mo per site | 1 site, 10 seats, Slack notify, supervisor escalation, 7-day clip retention |
| `facility_growth` | $99/mo per site | 25 seats, 30-day retention, multi-tenant admin, learning schedules with freeze controls |

`tenant_can_use_notify` refuses facility notify on plan `home`. Seat, place, and camera caps appear in the briefing. `src/care_ladder/billing/plans.py` does not enforce those caps. This draft does not change those caps.

Layer 2 sits on `facility_growth` ($99/mo per site). `facility_starter` does not get layer 2 in this draft. `home` ($9/mo) is excluded from this spine.

## Compliance and privacy

- Care Ladder coordinates a human check. It is not a medical device and does not emit a clinical score.
- No face recognition. Frames already go to blur (private zones) or silhouette (common zones) before storage.
- The executive briefing states no HIPAA certification claim. This spine does not add one.
- BAA and the staffing-ratio engine stay out until layer 3.
- Audit retention defaults to 3 years. The owner may extend it.
- Emergency dialing stays behind the existing human gate. This spine does not add a 911 or EMS feature.
- The soft cue `fall_cls_v1.onnx` is a non-clinical signal. Spoken confirm-first applies on the on-duty private path. Training data for any CV work is Kaggle fall plus CV-tag only, and only after the false-page unlock.

## Risks

- A reader treats staffing `on call` as `on_call_result` and pages the wrong meaning into the family bot.
- Stub Slack, stub Teams, and `StubDialer` get described as live cover. The audit has to keep saying stub until a real send exists. Voice stays stubbed until a pilot asks for dial. The preferred real path is the Teams webhook owned by the Facility Growth tenant admin (owner).
- Fall-cue training starts before the unlock (7-night one-wing pilot, ≥200 soft cues, false-page rate above 15%, or the floor lead says noise is the top complaint), and the floor gets more pages from an unmeasured model.
- Backup includes someone who is not registered staff on that facility roster (sister site or agency), and the page leaves the roster.
- Place policy follows the display default. Case-only places that are not care-plan zones are shown as `zone_kind: private` in `build_places`. That default is not an operator choice. Policy binds per place via `Zone.kind`, so a wrong kind binds the wrong rule. There is no site-wide override.
- Home $9 or Facility Starter is sold as layer 2 cover. Layer 2 sits on Facility Growth ($99) only. Home is excluded from this spine. Starter does not get layer 2 in this draft.
- Confirm-first is applied to an on-call backup page, or skipped on the on-duty private path. Backup pages are straight pages. Spoken confirm-first still applies on the on-duty private path.
- Layer 3 scheduling, a BAA, or a staffing-ratio engine ships inside the layer 2 MVP. On call in layer 2 is a live flag only. Rotations, BAA, and the staffing-ratio engine are layer 3.

## Resolved decisions (locked 2026-10-05 by Anoop)

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
