# Design: Facility Floor Console (Mockup H)

**Date:** 2026-09-28  
**Repo:** `pamu512/care-ladder-saas`  
**Status:** Approved direction (Approach 1 vertical slices; 2–3 stretch)  
**Visual source:** Mockup H static HTML (`mockup-h-break-aware-routing.html`) — Alert center / Cases / Audit with break-aware routing  
**Owner for implement:** Mac Hermes (Cursor cloud or local Mac worker on this repo)  
**Product owner:** Galaxium - Care ladder agent / Anoop

---

## 1. Problem

The live facility console is still the single-pane demo UI (`/ui/`): fixture buttons + incident cards. Mockup H defines a **floor-lead ops console** for assisted-living: triage by priority, cases with documentation, staff break-aware assignment, and audit KPIs. Home stays the caregiver / Fire-TV-style web console (unchanged in this project).

## 2. Decisions (locked)

| Decision | Choice |
| --- | --- |
| Scope this pass | **Full Mockup H**: Alert center, Cases, Audit, response jump, break routing, staff roster |
| Delivery method | **Approach 1**: vertical slices with green tests each merge |
| Stretch (if time) | Approach 2 UI shell polish extras; Approach 3 real Slack bot (explicitly optional) |
| Home UI | **Unchanged**. Facility tenants only get Mockup H console |
| Cases backend | **Postgres** case rows; **stub** Slack thread URLs; ack/close/docs via console APIs; **no live Slack bot** |
| Reply classification | **LLM via Google Cloud / Vertex**; **fixture override** when no LLM credentials (CI + offline demo) |
| Staff / break | **Postgres** `StaffMember` + `break_until`; seed demo roster; console toggle + API |
| Auth | Only when `CARE_LADDER_AUTH=on` (Render). Auth-off local demos keep existing behavior unless noted |
| Honesty | Not a medical device; telephony stubbed; privacy blur before persist; no em dashes in user-facing copy |

## 3. Personas and surfaces

### 3.1 Home caregiver (out of scope for UI rewrite)

- Existing `/ui/` Path A / Path B console.
- Fire-TV-adjacent mental model: check-in → OK / silence → dial.
- Do **not** replace with Alert/Cases/Audit.

### 3.2 Facility floor lead (in scope)

- New facility console (same `/ui/` route when tenant `mode=facility`, or dedicated `/ui/facility` if cleaner — implementer chooses; must not break Home).
- Tabs: **Alert center**, **Cases**, **Audit**.
- Can assign, reprioritize, escalate/de-escalate, pull staff off break (logged).

### 3.3 Facility staff (light)

- Appear on roster; break toggle (self or lead); acknowledge / close cases from console (chat is stub).

## 4. Domain model

### 4.1 Reply classification

```text
ReplyClass = positive | negative | silence | unclear
```

- **LLM path (default when configured):** Vertex / Google Cloud agent classifies speaker reply text → `ReplyClass` + short rationale (stored on event detail).
- **Fixture override:** demo fixtures set `reply_kind` / `reply_class` explicitly; classifier must not override fixtures.
- **Fallback when no credentials:** treat as today’s behavior (scripted OK / silence) and never call network; tests must pass offline.

**Ladder effects (facility plans):**

| Class | Effect |
| --- | --- |
| positive | Resolve incident; **do not** open case; appear under “Resolved by resident response” |
| negative | Auto-raise priority (default P2→P1); **skip wait rungs**; page group / notify path immediately; open Case |
| silence | Existing facility path: notify_channel → notify_supervisor → dial as plan YAML defines |
| unclear | Treat as silence for routing; log classification |

### 4.2 Priority

```text
Priority = P1 | P2 | P3
```

- Default by cue / classification (document mapping in code constants).
- Negative response auto-raises to P1.
- Lead can override; every change → audit event `priority_override`.

### 4.3 Staff

```text
StaffMember {
  id, tenant_id, display_name, role, initials,
  status: available | on_case | on_break,
  break_until: datetime | null,
  active_case_id: str | null
}
```

- Auto-routing and manual assign **skip** `on_break` unless lead override `pull_off_break`.
- Seed for `demo-facility`: Maria G. (RN), Alex R. (CNA), Jamie D. (CNA), Floor Lead (You).

### 4.4 Case

```text
Case {
  id: CL-#### human id + uuid,
  tenant_id, incident_id,
  room_label, title, origin,   # e.g. from_negative_reply | from_silence | from_cue
  priority, state: paged | handling | wrapping | closed,
  owner_staff_id | null,
  slack_thread_url: stub URL string,
  ack_at, closed_at,
  documentation: text | null,
  sla_ack_sec target, sla_handling_sec target (constants OK for MVP)
}
```

- Opened when staff must act (silence page or negative jump).
- Closed with required documentation string (min length enforced).
- “Open chat thread” button → stub URL (`https://example.invalid/care-floor-ops/thread/{case_id}` or similar); never call Slack API this pass.

### 4.5 Alert (view model, not separate table required)

- Derived from open incidents + case state for Alert center list.
- Includes chips: Negative response, Ladder jumped, Assigned, Escalated, Calm, Quiet hours (quiet hours may be display-only stub if not in plan YAML yet).

## 5. API surface (facility, auth-on)

All under existing FastAPI app; session cookie auth.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/facility/alerts` | Triage queue + resident-resolved today |
| GET | `/facility/alerts/{incident_id}` | Detail: reply, ladder mini-rung, assign candidates |
| POST | `/facility/alerts/{incident_id}/priority` | `{priority}` lead override |
| POST | `/facility/alerts/{incident_id}/assign` | `{staff_id, pull_off_break?: bool}` |
| POST | `/facility/alerts/{incident_id}/override` | `{action: escalate\|deescalate\|suppress\|repage\|pull_off_break}` |
| GET | `/facility/cases` | Open + closed-today |
| POST | `/facility/cases/{case_id}/ack` | Owner ack |
| POST | `/facility/cases/{case_id}/close` | `{documentation}` |
| GET | `/facility/staff` | Roster + break |
| POST | `/facility/staff/{staff_id}/break` | `{on_break: bool, minutes?: int}` |
| GET | `/facility/audit/summary` | KPIs + outcome mix + overrides today |
| GET | `/facility/audit/export.csv` | CSV export (stretch if time-boxed) |

Existing: `/demo/run` fixtures extended with **negative response** facility fixture.

## 6. UI requirements (match Mockup H)

- Sticky header: Care Ladder floor console, tenant/plan, clock, Scenarios / Upload optional (demo).
- Tabs with badges: Alert center (open count), Cases (open count), Audit.
- Alert center: response banner (resident answers first); priority-ordered cards; detail pane (response, ladder, reprioritize, assign, overrides); resident-resolved section.
- Cases: open cards with SLA string; closed with documentation; shift capacity sidebar + break toggle.
- Audit: KPI strip; outcome bars or simpler counts OK if bars are ambiguous; filters; expandable reports; exports.
- No em dashes in copy. Honesty footer retained.
- Responsive: single column under ~1020px.

## 7. Non-goals (this pass)

- Live Slack bot / slash commands (stretch Approach 3).
- Replacing Home `/ui`.
- Real telephony / emergency calling.
- Medical claims.
- Full quiet-hours engine (chip may be stub).
- PDF export (CSV first; PDF stretch).

## 8. Success criteria

1. Facility demo login shows Mockup H tabs; Home demo login shows unchanged Path A/B console.
2. Fixture **facility_negative_reply** produces P1 card, jump event, open Case, stub Slack URL.
3. Fixture positive reply appears only under resident-resolved (no case).
4. Staff on break cannot be assigned without `pull_off_break`; override logged.
5. Ack + close with documentation works via API and Cases tab.
6. Audit summary returns counts consistent with fixtures run in session.
7. Full pytest suite green offline (LLM mocked / fixture path).
8. Live Render still boots with `create_all` / bootstrap seed including staff.

## 9. Stretch goals (Approach 2 / 3)

- **S1:** Static HTML polish pass mirroring mockup pixel-closer (Approach 2 leftovers).
- **S2:** Real Slack posting + thread URL real (Approach 3) behind env flag.
- **S3:** PDF per-incident export.
- **S4:** Quiet hours from plan YAML.

## 10. Reference files in repo today

- `src/care_ladder/api/app.py` — create_app, fixtures, billing, `_require_session`, `_tenant_store`
- `src/care_ladder/api/static/index.html` — current console
- `src/care_ladder/billing/plans.py` — `tenant_can_use_notify`
- `src/care_ladder/channels/notify.py`, speaker/dial
- `scripts/bootstrap_saas_demo.py` — create_all + demo tenants
- `docs/galuxium/demo-video-galuxium.md` — update facility shots after UI lands
- Plan history: `docs/superpowers/plans/2026-09-17-galuxium-care-ladder-saas.md` (do not re-check its boxes; new plan owns this work)
