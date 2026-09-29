# Facility Console UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the shipped Mockup H facility floor console so floor leads can triage with keyboard, see owners/SLA/aging, get action errors, replace Audit with the closed-case register mock (time KPIs, expandable incident reports, lead-actions), choose break durations with countdown, and experience one product language with the home console (demo chrome quarantined).

**Architecture:** Small API enrichments on existing facility endpoints (`_case_out`, `FacilityState.summary`) plus a focused rewrite of `src/care_ladder/api/static/facility/index.html` JS/CSS. No new tables. Home console gets link/logo consistency only. Implement on a feature branch from tip `1f14a61` or later main; Mac Hermes only.

**Tech Stack:** Python 3.11+, FastAPI, existing FacilityState/Case/StaffMember, vanilla HTML/CSS/JS, pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-09-29-facility-console-ui-polish-design.md`

## Global Constraints

- Repo: `pamu512/care-ladder-saas`. Not OpenCV Care Ladder; not Alexa/Fire TV.
- Baseline tip when this plan was written: `1f14a61` (N1 auth-off facility 500 already fixed). Do not re-fix N1.
- Home Path A/B behavior unchanged except shared nav/logo if Task 6 touches `index.html`.
- No em dashes (— / `\u2014`) in user-facing copy or commit subjects that need to stay clean.
- TDD: failing test → implement → pass → commit per task.
- Offline CI: no Vertex required.
- Prefer trailing slash `/ui/facility/` in links.
- Do not Final-Submit Devpost.
- Implement via Mac Hermes only (no Cursor cloud agents for code).

---

### Task 0: Land design + this plan

**Files:**
- Create: `docs/superpowers/specs/2026-09-29-facility-console-ui-polish-design.md`
- Create: `docs/superpowers/plans/2026-09-29-facility-console-ui-polish.md` (this file)

**Interfaces:**
- Consumes: none
- Produces: approved docs on the branch

- [ ] **Step 1:** Confirm both files exist on the branch (already drafted in the docs PR handoff if present).

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-09-29-facility-console-ui-polish-design.md \
  docs/superpowers/plans/2026-09-29-facility-console-ui-polish.md
git commit -m "docs(facility): UI polish design and Hermes plan"
```

---

### Task 1: Enrich case payload + audit summary KPIs + register API

**Files:**
- Modify: `src/care_ladder/models.py` (`AuditEvent` optional `at`)
- Modify: `src/care_ladder/ladder/orchestrator.py` (stamp `at` when appending events)
- Modify: `src/care_ladder/api/app.py` (`_case_out`, summary route, new register route)
- Modify: `src/care_ladder/facility/service.py` (`FacilityState.summary`, helpers for register rows)
- Modify: `tests/test_facility_api.py`
- Modify: `tests/test_facility_domain.py`

**Interfaces:**
- Consumes: `Case.ack_at` / `closed_at` / `sla_*`, `state.case_opened_times()`, `state.staff`, `state.overrides`, `store` incidents, `state.resident_resolved`
- Produces:
  - `AuditEvent.at: datetime | None` (ISO in JSON); new events stamped at append time
  - `_case_out(c, state) -> dict` adds `opened_at`, `owner_display_name`, `owner_initials`, `sla_ack_sec`, `sla_handling_sec`
  - `summary()` adds mock KPI fields:
    - `median_ack_sec`, `median_handling_sec`, `pct_acked_in_sla`
    - `median_response_sec` (resident-resolved)
    - `resolved_by_response`, `resolved_by_response_total`
    - `group_timeouts`
  - `GET /facility/audit/register` -> `{ range: "today", rows: [RegisterRow, ...] }`
  - `GET /facility/audit/register/{incident_id}` -> drill-down payload (timeline, timing, evidence, overrides, docs)

`RegisterRow` shape:

```python
{
  "kind": "staff_case" | "resident_resolved" | "group_timeout",  # group_timeout if origin/exhausted implies missed group ack
  "incident_id": str,
  "case_id": str | None,
  "human_id": str,                 # CL-#### or short "inc ab12"
  "room_label": str,
  "title": str,
  "origin_key": "negative" | "silence" | "resident" | "timeout" | "cue" | "manual",
  "origin_label": str,             # human label for chip
  "owner_display_name": str | None,
  "owner_initials": str | None,
  "ack_sec": int | None,
  "handling_sec": int | None,
  "response_sec": int | None,      # resident-resolved only
  "missed": bool,
  "state": str | None,
  "priority": str | None,
}
```

Drill-down payload shape:

```python
{
  "row": RegisterRow,
  "case": dict | None,             # _case_out
  "timeline": [
    {"tool": str, "label": str, "detail": str, "quote": str | None,
     "at": str | None, "delta_sec": int | None, "kind": "normal"|"key"|"stop"|"jump"}
  ],
  "documentation": str | None,
  "documentation_meta": {"owner_display_name": str | None, "closed_at": str | None, "via": "console"},
  "timing": {
    "ack_sec": int | None, "ack_target_sec": int,
    "handling_sec": int | None, "handling_target_sec": int,
    "cue_to_page_sec": int | None, "nudges": int, "nudge_response_sec": int | None
  },
  "evidence": {"frame_count": int, "privacy": str | None, "frame_urls": list[str], "slack_thread_url": str | None},
  "overrides": list[dict],         # filtered state.overrides for this case_id
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_facility_api.py`:

```python
def test_case_out_includes_owner_and_opened(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    staff = client.get("/facility/staff").json()["staff"]
    maria = next(s for s in staff if "Maria" in s["display_name"])
    assert client.post(f"/facility/alerts/{iid}/assign", json={"staff_id": maria["id"]}).status_code == 200
    cases = client.get("/facility/cases").json()
    c = next(x for x in cases["open"] if x["incident_id"] == iid)
    assert c["owner_display_name"] == maria["display_name"]
    assert c["owner_initials"] == maria["initials"]
    assert c["opened_at"]
    assert c["sla_ack_sec"] == 120
    assert c["sla_handling_sec"] == 900


def test_audit_summary_time_metrics_after_ack_close(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    assert client.post(f"/facility/cases/{case['id']}/ack", json={}).status_code == 200
    assert client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Resident assisted back to bed safely."},
    ).status_code == 200
    s = client.get("/facility/audit/summary").json()
    assert s["median_ack_sec"] is not None and s["median_ack_sec"] >= 0
    assert s["median_handling_sec"] is not None and s["median_handling_sec"] >= 0
    assert s["pct_acked_in_sla"] is not None
    assert 0 <= s["pct_acked_in_sla"] <= 100
    assert "resolved_by_response" in s and "resolved_by_response_total" in s
    assert "group_timeouts" in s
    assert "median_response_sec" in s  # may be null until a positive fixture


def test_audit_register_lists_closed_and_resident(client):
    _facility_login(client)
    neg = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == neg)
    client.post(f"/facility/cases/{case['id']}/ack", json={})
    client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Checked room; resident OK after assist."},
    )
    pos = _run(client, "facility_positive_reply")
    reg = client.get("/facility/audit/register").json()
    assert reg["range"] == "today"
    kinds = {r["incident_id"]: r["kind"] for r in reg["rows"]}
    assert kinds[neg] == "staff_case"
    assert kinds[pos] == "resident_resolved"
    staff_row = next(r for r in reg["rows"] if r["incident_id"] == neg)
    assert staff_row["owner_display_name"] is None or isinstance(staff_row["owner_display_name"], str)
    assert staff_row["ack_sec"] is not None
    assert "staff -" not in (staff_row.get("owner_display_name") or "")


def test_audit_register_detail_has_timeline_and_timing(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    client.post(f"/facility/cases/{case['id']}/ack", json={})
    client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Resident assisted back to bed safely."},
    )
    d = client.get(f"/facility/audit/register/{iid}").json()
    assert d["timeline"] and any(x["tool"] for x in d["timeline"])
    assert "timing" in d and "ack_target_sec" in d["timing"]
    assert "evidence" in d and "frame_count" in d["evidence"]
    assert "overrides" in d
    assert d.get("documentation")
```

Add unit test in `tests/test_facility_domain.py`:

```python
from datetime import datetime, timedelta, timezone
from care_ladder.facility.models import Case
from care_ladder.facility.service import FacilityState

def test_summary_median_ack_and_handling():
    state = FacilityState()
    now = datetime.now(timezone.utc)
    c = Case.open_from_incident(
        incident_id="i1", tenant_id="demo-facility", room_label="204",
        origin="from_negative_reply", priority="P1", human_id="CL-0001",
    )
    c.ack_at = now - timedelta(seconds=30)
    c.closed_at = now
    c.state = "closed"
    state.cases[c.id] = c
    state._opened_times[c.id] = (now - timedelta(seconds=90)).isoformat()
    s = state.summary()
    assert s["median_ack_sec"] == 60
    assert s["median_handling_sec"] == 30
    assert s["pct_acked_in_sla"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_facility_api.py::test_case_out_includes_owner_and_opened \
  tests/test_facility_api.py::test_audit_summary_time_metrics_after_ack_close \
  tests/test_facility_api.py::test_audit_register_lists_closed_and_resident \
  tests/test_facility_api.py::test_audit_register_detail_has_timeline_and_timing \
  tests/test_facility_domain.py::test_summary_median_ack_and_handling -v
```

Expected: FAIL (missing keys / routes)

- [ ] **Step 3: Implement**

1. `AuditEvent` in `models.py`: add `at: datetime | None = None`.
2. Where orchestrator (and facility reply helpers) append `AuditEvent(...)`, set `at=datetime.now(timezone.utc)`. Existing stored incidents without `at` remain valid (null).
3. `_case_out(c, state)` as previously specified (owner join + opened_at + sla fields). Update all facility callers.
4. Expand `FacilityState.summary()` with the KPI fields above. For `median_response_sec` / resolved counts, use `resident_resolved` entries joined to incident events (`speaker_prompt` with `reply_class=positive`) when store is available from the route layer (prefer computing in the route if store is required).
5. Implement `build_register(state, store) -> list[dict]` and `build_register_detail(state, store, incident_id) -> dict` in `service.py` (or `facility/audit_register.py`). Timeline humanization map:

```python
TOOL_LABELS = {
  "cue": "Cue",
  "speaker_prompt": "Voice check-in",
  "notify_supervisor": "Page group",
  "wait": "Wait",
  "jump": "Ladder jump",
  "resolve": "Resolved",
}
```

Color `kind`: `notify_*` / page -> `key`; case open/close / resolve -> `stop`; `jump` / SLA nudge -> `jump`; else `normal`.

Deltas: prefer `event.at` differences; for ack/close lines fall back to case `opened_at`/`ack_at`/`closed_at` when event `at` is null.

6. Mount:

```python
@application.get("/facility/audit/register")
def facility_audit_register(request: Request):
    tenant_id, state, store = _facility_ctx(request)
    return {"range": "today", "rows": build_register(state, store)}

@application.get("/facility/audit/register/{incident_id}")
def facility_audit_register_detail(incident_id: str, request: Request):
    tenant_id, state, store = _facility_ctx(request)
    detail = build_register_detail(state, store, incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="register row not found")
    return detail
```

Keep existing `GET /facility/audit/summary` and CSV export.

**Honest gap vs the mock prose:** `AuditEvent` did not previously carry wall clocks; stamping `at` on new events is a thin write-path fix so the register can show timestamps. Case `ack_at`/`closed_at`/`created_at` already exist and drive KPI medians even when older events lack `at`. Do **not** invent fake clocks for historical events; omit `at` / show sequence-only until stamped data exists.

- [ ] **Step 4: Run tests: PASS**

```bash
python -m pytest tests/test_facility_api.py tests/test_facility_domain.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/models.py src/care_ladder/ladder/orchestrator.py \
  src/care_ladder/api/app.py src/care_ladder/facility/service.py \
  src/care_ladder/facility/audit_register.py \
  tests/test_facility_api.py tests/test_facility_domain.py
git commit -m "feat(facility): audit register API, owner join, time KPIs"
```

---

### Task 2: Alert keyboard/ARIA, selection, preserve detail form

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `tests/test_facility_ui.py`

**Interfaces:**
- Consumes: Task 1 `opened_at` on alert.case
- Produces: selectable alert cards; `state.detailDirty` + `state.detailDraft`; selected styling

- [ ] **Step 1: Write the failing UI content tests**

```python
def test_facility_alerts_have_aria_hooks(client):
    r = client.get("/ui/facility/")
    html = r.text
    assert 'role="button"' in html or "role=\\\"button\\\"" in html or "setAttribute(\"role\"" in html
    assert "aria-selected" in html
    assert "detailDirty" in html or "detailDraft" in html
    assert "keydown" in html
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_facility_ui.py::test_facility_alerts_have_aria_hooks -v
```

Expected: FAIL

- [ ] **Step 3: Implement alert interaction + form preserve**

In `facility/index.html`:

1. Extend state:

```javascript
const state = {
  alerts: [], resident: [], cases: {open: [], closed_today: []}, staff: [],
  selected: null, detailDirty: false, detailDraft: null, loading: false,
};
```

2. CSS additions:

```css
.alert.selected{outline:2px solid var(--accent); outline-offset:2px; border-color:var(--accent)}
.alert:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
```

3. Replace `renderAlerts` card markup so each alert is:

```javascript
el.innerHTML = state.alerts.map(a => {
  const opened = a.case && a.case.opened_at ? new Date(a.case.opened_at) : null;
  const ageMin = opened ? Math.max(0, Math.floor((Date.now()-opened.getTime())/60000)) : null;
  const sla = (a.case && a.case.sla_ack_sec) || 120;
  const leftMin = opened ? Math.max(0, Math.ceil((sla*1000 - (Date.now()-opened.getTime()))/60000)) : null;
  const selected = state.selected === a.incident_id;
  return `<div class="alert ${a.priority}${selected?" selected":""}" data-incident="${a.incident_id}"
    role="button" tabindex="0" aria-selected="${selected}">
    <div class="row1">
      <span class="pri ${a.priority}">${a.priority}</span>
      <strong>${a.title}</strong>
      <span class="chip">room ${a.room_label}</span>
      <span class="chip">${a.case.human_id}</span>
      ${ageMin!==null?`<span class="chip">aging ${ageMin}m</span>`:""}
      ${leftMin!==null?`<span class="chip">${leftMin}m to ack target</span>`:""}
    </div>
    ${(a.chips||[]).map(c=>`<span class="chip">${c}</span>`).join("")}
  </div>`;
}).join("");
el.querySelectorAll(".alert").forEach(x => {
  const activate = () => loadDetail(x.dataset.incident);
  x.addEventListener("click", activate);
  x.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
  });
});
```

4. Empty state (no demo pointer):

```javascript
if (!state.alerts.length){
  el.innerHTML = '<p class="muted">Floor clear. No open alerts.</p>';
  return;
}
```

5. In `loadDetail`, before rebuilding, if `state.detailDirty && state.selected === incidentId && state.detailDraft`, re-apply draft after render:

```javascript
async function loadDetail(incidentId, {force=false} = {}){
  if (!force && state.detailDirty && state.selected === incidentId && state.detailDraft) {
    // still refresh server fields but keep draft controls
  }
  state.selected = incidentId;
  renderAlerts(); // refresh selected class
  const {status, body} = await japi(`/facility/alerts/${incidentId}`);
  if (status !== 200){ showToast((body&&body.detail)||"Could not load alert"); return; }
  const d = $("#alert-detail");
  const c = body.case || {};
  // ... build markup as today ...
  // after wiring listeners:
  const sel = $("#assign-select");
  const pull = $("#pull_off_break");
  if (state.detailDirty && state.detailDraft && state.detailDraft.incidentId === incidentId) {
    if (sel && state.detailDraft.staff_id) sel.value = state.detailDraft.staff_id;
    if (pull) pull.checked = !!state.detailDraft.pull_off_break;
  }
  const markDirty = () => {
    state.detailDirty = true;
    state.detailDraft = {
      incidentId,
      staff_id: sel ? sel.value : null,
      pull_off_break: pull ? pull.checked : false,
    };
  };
  if (sel) sel.addEventListener("change", markDirty);
  if (pull) pull.addEventListener("change", markDirty);
  // on successful assign/priority: state.detailDirty = false; state.detailDraft = null; then refresh()
}
```

6. Change assign/priority handlers to check `japi` status and only clear dirty on success (see Task 3 toast helper; can stub `showToast` here).

- [ ] **Step 4: Tests PASS + commit**

```bash
python -m pytest tests/test_facility_ui.py -q
git add src/care_ladder/api/static/facility/index.html tests/test_facility_ui.py
git commit -m "feat(facility): alert ARIA selection and preserve detail draft"
```

---

### Task 3: Owner rendering, close char count, action error surfaces

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `tests/test_facility_ui.py`

**Interfaces:**
- Consumes: `owner_display_name`, `owner_initials`, close 422 detail
- Produces: `#toast`, `.form-error`, char counter, human owner labels

- [ ] **Step 1: Failing UI tests**

```python
def test_facility_ui_has_toast_and_owner_fields(client):
    html = client.get("/ui/facility/").text
    assert 'id="toast"' in html
    assert "owner_display_name" in html
    assert "data-doc-count" in html or "doc-count" in html
```

- [ ] **Step 2: Run: expect FAIL**

- [ ] **Step 3: Implement**

Add to HTML body (near footer):

```html
<div id="toast" hidden role="status" aria-live="polite"></div>
```

CSS:

```css
#toast{position:fixed;bottom:20px;right:20px;background:var(--card);border:1px solid var(--border);padding:10px 14px;border-radius:10px;z-index:20;max-width:320px}
#toast.err{border-color:var(--p1)}
.form-error{color:var(--p1);font-size:12px;margin-top:6px}
.doc-count{font-size:11px;color:var(--muted);margin-top:4px}
```

JS helpers:

```javascript
function showToast(msg, err=false){
  const t = $("#toast");
  t.hidden = false; t.textContent = msg; t.className = err ? "err" : "";
  clearTimeout(showToast._t);
  showToast._t = setTimeout(()=>{ t.hidden = true; }, 4000);
}

function ownerLabel(c){
  if (c.owner_display_name){
    return (c.owner_initials ? c.owner_initials + " · " : "") + c.owner_display_name;
  }
  return "unassigned";
}

function slaLine(c){
  const opened = c.opened_at ? new Date(c.opened_at) : null;
  if (!opened) return "SLA ack " + (c.sla_ack_sec||120) + "s / handling " + (c.sla_handling_sec||900) + "s";
  const age = Math.floor((Date.now()-opened.getTime())/1000);
  let line = "open " + age + "s";
  if (c.ack_at){
    const ackSec = Math.floor((new Date(c.ack_at)-opened)/1000);
    line += " · ack " + ackSec + "s (target " + (c.sla_ack_sec||120) + "s)";
  }
  if (c.ack_at && c.closed_at){
    const h = Math.floor((new Date(c.closed_at)-new Date(c.ack_at))/1000);
    line += " · handled " + h + "s";
  }
  return line;
}
```

In `renderCases`, replace owner fragment:

```javascript
owner ${ownerLabel(c)}
```

and SLA line with `slaLine(c)`.

Close button wiring:

```javascript
open.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", async () => {
  const ta = open.querySelector(`[data-doc="${b.dataset.close}"]`);
  const err = open.querySelector(`[data-doc-err="${b.dataset.close}"]`);
  const {status, body} = await japi(`/facility/cases/${b.dataset.close}/close`, {
    method: "POST", body: JSON.stringify({documentation: ta.value})
  });
  if (status !== 200){
    if (err) err.textContent = (body && body.detail) || "Close failed (documentation min 20 chars)";
    showToast((body && body.detail) || "Close failed", true);
    return;
  }
  if (err) err.textContent = "";
  refresh();
}));
open.querySelectorAll("textarea[data-doc]").forEach(ta => {
  const counter = open.querySelector(`[data-doc-count="${ta.dataset.doc}"]`);
  const sync = () => { if (counter) counter.textContent = ta.value.trim().length + "/20"; };
  ta.addEventListener("input", sync); sync();
});
```

Case card close block markup:

```html
<textarea data-doc="${c.id}" placeholder="Closing notes (min 20 chars)"></textarea>
<div class="doc-count" data-doc-count="${c.id}">0/20</div>
<div class="form-error" data-doc-err="${c.id}"></div>
<button class="btn mini" data-close="${c.id}">Close with docs</button>
```

Same status checks for ack and assign/priority.

- [ ] **Step 4: PASS + commit**

```bash
python -m pytest tests/test_facility_ui.py -q
git add src/care_ladder/api/static/facility/index.html tests/test_facility_ui.py
git commit -m "feat(facility): owner labels, close counter, action toasts"
```

---

### Task 4: Replace Audit tab with closed-case register (mock)

**Visual source:** `docs/galuxium/mockup-audit-drill-down.html` (committed with this plan). Reuse the existing Audit tab shell; replace the KPI + outcome-bars + flat case list with the mock structure.

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `tests/test_facility_ui.py`
- Reference (do not serve as live UI): `docs/galuxium/mockup-audit-drill-down.html`

**Interfaces:**
- Consumes: Task 1 `GET /facility/audit/summary`, `GET /facility/audit/register`, `GET /facility/audit/register/{incident_id}`, existing CSV export
- Produces: Audit tab matching the mock: 6 KPIs, filterable expandable register, drill-down transcript + rails, lead-actions card

**In scope (MVP / today range):**
1. Time-metric KPIs (not just counts): resolved-by-response `N of M`, median response, median time-to-ack, % acked in window, median handling, group timeouts. Color classes: `vio` / `good` / `warn` / `bad` per mock heuristics (e.g. handling over target -> warn/bad).
2. Closed-case register: expandable `.reg` rows with case/incident id, room + title, origin chip (`resolved by response` / `negative reply` / `group timeout` / silence), owner **display name**, ack time, handling (or response time / "no staff action" for resident rows).
3. Filters (client-side on today's register payload): All outcomes / Staff-handled / Resolved by response / Negative replies. Date-range chips: **Today wired**; `7 days` and `Shift…` visible but toast "Range not available yet" (stretch).
4. Drill-down body (two columns):
   - Left: Care Ladder incident report from register detail `timeline` (color `kind` classes), documentation block + signature meta.
   - Right rail: Timing vs targets (ack target use case `sla_ack_sec`, default display as m:ss), Evidence (frame count + privacy + Open chat stub URL), Overrides list or "None · fully auto-routed", actions: Open chat thread (stub); Export PDF button toast "PDF export coming soon" (stretch).
5. Lead-actions card: list today's overrides (from summary or register aggregate / `state.overrides` via summary extension `overrides_recent: [...]` if needed). Export: keep working **Export audit CSV**; PDF + zip buttons are stretch (toast).

**Out of scope / stretch (label in UI, do not block):**
- Per-shift PDF, case-file zip, true 7-day/shift queries
- Pixel-perfect copy of every mock demo sentence
- Em dashes: strip; use commas or periods in all shipped strings

- [ ] **Step 1: Failing UI tests**

```python
def test_facility_audit_register_hooks(client):
    html = client.get("/ui/facility/").text
    assert "audit/register" in html
    assert "Closed-case register" in html or "closed-case register" in html.lower() or "id=\"audit-register\"" in html
    assert "Resolved by response" in html or "resolved by response" in html
    assert "lead-actions" in html or "Lead actions" in html
    assert "\u2014" not in html
```

- [ ] **Step 2: Run: expect FAIL**

- [ ] **Step 3: Implement Audit section HTML/CSS/JS**

Port structure and CSS classes from `docs/galuxium/mockup-audit-drill-down.html` into the Audit `<section id="sec-audit">` of `facility/index.html` (keep dark theme; Task 6 may retint accent later).

Key JS:

```javascript
const ORIGIN_CHIP = {
  resident: ["origin-chip resident", "resolved by response"],
  negative: ["origin-chip negative", "negative reply"],
  timeout: ["origin-chip timeout", "group timeout"],
  silence: ["origin-chip timeout", "silence"],
};

function fmtDur(sec){
  if (sec == null) return "n/a";
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec/60), s = sec % 60;
  return m + "m " + String(s).padStart(2,"0") + "s";
}

async function renderAudit(){
  const [sum, reg] = await Promise.all([
    japi("/facility/audit/summary"),
    japi("/facility/audit/register"),
  ]);
  if (sum.status !== 200){ showToast((sum.body&&sum.body.detail)||"Audit failed", true); return; }
  const b = sum.body;
  const total = b.resolved_by_response_total || ((b.cases_closed_today||0)+(b.resident_resolved_today||0)) || 0;
  $("#kpi").innerHTML = [
    kpiBox("vio", `${b.resolved_by_response??0} <small>of ${total||0}</small>`, "Resolved by response"),
    kpiBox("vio", b.median_response_sec==null?"n/a":fmtDur(b.median_response_sec), "Median response time"),
    kpiBox("good", b.median_ack_sec==null?"n/a":fmtDur(b.median_ack_sec), "Median time-to-ack"),
    kpiBox("good", b.pct_acked_in_sla==null?"n/a":(b.pct_acked_in_sla+"%"), "Acked in window"),
    kpiBox("good", b.median_handling_sec==null?"n/a":fmtDur(b.median_handling_sec), "Median handling"),
    kpiBox("bad", String(b.group_timeouts??0), "Group timeouts"),
  ].join("");

  state.auditRows = (reg.status===200 ? (reg.body.rows||[]) : []);
  state.auditFilter = state.auditFilter || "all";
  renderAuditFilters();
  renderAuditRegister();
  renderLeadActions(b);
}

function renderAuditRegister(){
  const rows = (state.auditRows||[]).filter(r => {
    if (state.auditFilter === "staff") return r.kind === "staff_case";
    if (state.auditFilter === "resident") return r.kind === "resident_resolved";
    if (state.auditFilter === "negative") return r.origin_key === "negative";
    return true;
  });
  const root = $("#audit-register");
  if (!rows.length){ root.innerHTML = '<p class="muted">No closed cases or resident resolutions today.</p>'; return; }
  root.innerHTML = rows.map(r => auditRowShell(r)).join("");
  root.querySelectorAll(".reg-head").forEach(h => h.addEventListener("click", async () => {
    const reg = h.parentElement;
    const open = !reg.classList.contains("open");
    // accordion: close others
    root.querySelectorAll(".reg.open").forEach(x => { if (x!==reg){ x.classList.remove("open"); x.querySelector(".reg-body")?.remove(); }});
    if (!open){ reg.classList.remove("open"); reg.querySelector(".reg-body")?.remove(); return; }
    reg.classList.add("open");
    h.setAttribute("aria-expanded","true");
    const {status, body} = await japi(`/facility/audit/register/${reg.dataset.incident}`);
    if (status !== 200){ showToast("Could not load incident report", true); return; }
    let bodyEl = reg.querySelector(".reg-body");
    if (!bodyEl){ bodyEl = document.createElement("div"); bodyEl.className = "reg-body"; reg.appendChild(bodyEl); }
    bodyEl.innerHTML = renderDrillDown(body);
    wireDrillActions(bodyEl, body);
  }));
}

function renderDrillDown(d){
  const lines = (d.timeline||[]).map(e => `
    <div class="r-line ${e.kind||""}">
      <span class="nm">${e.label||e.tool}</span>
      <span class="ds">${e.detail||""}${e.quote?` <span class="quote">"${e.quote}"</span>`:""}${e.delta_sec!=null?`<span class="delta">Δ ${fmtDur(e.delta_sec)}</span>`:""}</span>
      <span class="ts">${e.at ? new Date(e.at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"}) : ""}</span>
    </div>`).join("");
  const t = d.timing||{};
  const ov = (d.overrides&&d.overrides.length)
    ? d.overrides.map(o => `<div class="ov-item"><b>${o.action}</b> <span class="t">${o.at||""}</span></div>`).join("")
    : '<div class="ov-item">None · fully auto-routed</div>';
  const doc = d.documentation
    ? `<div class="doc-block"><h6>Submitted documentation</h6><p>${escapeHtml(d.documentation)}</p>
         <div class="sig">${(d.documentation_meta&&d.documentation_meta.owner_display_name)||"staff"} · via console · ${(d.documentation_meta&&d.documentation_meta.closed_at)||""}</div></div>`
    : "";
  return `
    <div class="report">
      <h5>Care Ladder incident report</h5>
      <span class="inc-link">inc ${d.row.incident_id} · ${(d.row&&d.row.title)||""}</span>
      ${lines}${doc}
    </div>
    <aside class="rail">
      <div class="box"><h6>Timing</h6>
        <div class="metric"><span class="k">Time-to-ack</span><span class="v">${fmtDur(t.ack_sec)} / ${fmtDur(t.ack_target_sec)}</span></div>
        <div class="metric"><span class="k">Handling time</span><span class="v">${fmtDur(t.handling_sec)} / ${fmtDur(t.handling_target_sec)}</span></div>
        <div class="metric"><span class="k">Cue to first page</span><span class="v">${fmtDur(t.cue_to_page_sec)}</span></div>
        <div class="metric"><span class="k">Nudges</span><span class="v">${t.nudges||0}</span></div>
      </div>
      <div class="box"><h6>Evidence</h6>
        <div class="clip-ref">${(d.evidence&&d.evidence.frame_count)||0} frames · ${(d.evidence&&d.evidence.privacy)||"n/a"}</div>
        <div class="clip-ref">chat thread · stub</div>
      </div>
      <div class="box"><h6>Overrides on this case</h6>${ov}</div>
      <div class="box actions">
        <button type="button" class="btn small" data-act="pdf">Export PDF</button>
        <a class="btn small" href="${(d.evidence&&d.evidence.slack_thread_url)||"#"}" target="_blank" rel="noopener">Open chat thread</a>
      </div>
    </aside>`;
}
```

Wire filter chips and lead-actions CSV button to `/facility/audit/export.csv`. PDF/zip -> `showToast("Coming soon", false)`.

Include `escapeHtml` helper. Never ship `\u2014`.

- [ ] **Step 4: PASS + commit**

```bash
python -m pytest tests/test_facility_ui.py tests/test_facility_api.py -q
git add src/care_ladder/api/static/facility/index.html tests/test_facility_ui.py \
  docs/galuxium/mockup-audit-drill-down.html
git commit -m "feat(facility): Audit tab closed-case register and drill-down"
```

---

### Task 5: Break durations + `break_until` countdown

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `tests/test_facility_ui.py`
- Optionally strengthen: `tests/test_facility_api.py` (minutes=30 already supported)

**Interfaces:**
- Consumes: `POST /facility/staff/{id}/break` body `{on_break, minutes}`; staff `break_until`
- Produces: 15/30/60 controls; live `Xm left` label updated on clock tick

- [ ] **Step 1: Failing test**

```python
def test_facility_break_duration_hooks(client):
    html = client.get("/ui/facility/").text
    assert "data-minutes=\"15\"" in html or "data-minutes='15'" in html or 'minutes:15' in html
    assert "break_until" in html
    assert "m left" in html
```

- [ ] **Step 2: Run: expect FAIL**

- [ ] **Step 3: Implement `renderRoster`**

```javascript
function breakLeftLabel(s){
  if (s.status !== "on_break" || !s.break_until) return s.status.replace("_"," ");
  const ms = new Date(s.break_until).getTime() - Date.now();
  if (ms <= 0) return "break ended";
  const m = Math.ceil(ms/60000);
  return "on break · " + m + "m left";
}

function renderRoster(){
  $("#staff-roster").innerHTML = state.staff.map(s => `
    <div class="staff">
      <div class="avatar">${s.initials}</div>
      <div style="flex:1">
        <div>${s.display_name} <span class="muted small">${s.role}</span></div>
        <div class="status ${s.status}">${breakLeftLabel(s)}</div>
      </div>
      ${s.status === "on_break"
        ? `<button class="btn mini" data-break="${s.id}" data-to="off">End break</button>`
        : `<span class="break-group">
             <button class="btn mini" data-break="${s.id}" data-to="on" data-minutes="15">15m</button>
             <button class="btn mini" data-break="${s.id}" data-to="on" data-minutes="30">30m</button>
             <button class="btn mini" data-break="${s.id}" data-to="on" data-minutes="60">60m</button>
           </span>`}
    </div>`).join("");
  $("#staff-roster").querySelectorAll("[data-break]").forEach(b => b.addEventListener("click", async () => {
    const on = b.dataset.to === "on";
    const minutes = parseInt(b.dataset.minutes || "15", 10);
    const {status, body} = await japi(`/facility/staff/${b.dataset.break}/break`, {
      method: "POST", body: JSON.stringify({on_break: on, minutes})
    });
    if (status !== 200){ showToast((body&&body.detail)||"Break update failed", true); return; }
    refresh();
  }));
}
```

Update `tick()` to also re-render roster labels without full refresh:

```javascript
function tick(){
  const n = new Date();
  $("#clock").textContent = n.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  if (state.staff && state.staff.length) renderRoster();
  if (state.alerts && state.alerts.length) renderAlerts(); // refresh aging chips
}
```

- [ ] **Step 4: PASS + commit**

```bash
python -m pytest tests/test_facility_ui.py tests/test_facility_api.py -q
git add src/care_ladder/api/static/facility/index.html tests/test_facility_ui.py
git commit -m "feat(facility): break duration choices and countdown"
```

---

### Task 6: Visual unification, demo quarantine, loading + nav

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `src/care_ladder/api/static/index.html` (link text + trailing slash only if needed)
- Modify: `tests/test_facility_ui.py`
- Modify: `tests/test_ui_facility_mode.py` if it asserts link href

**Interfaces:**
- Consumes: home logo SVG path (copy into facility header)
- Produces: shared accent tokens, collapsible demo strip, loading state, first-class Caregiver console link

- [ ] **Step 1: Failing tests**

```python
def test_facility_demo_strip_and_loading(client):
    html = client.get("/ui/facility/").text
    assert "demo-strip" in html
    assert "loading" in html
    assert "/ui/facility/" in client.get("/ui/").text or "/ui/facility/" in html
    assert "\u2014" not in html
```

- [ ] **Step 2: Run: expect FAIL**

- [ ] **Step 3: Implement chrome**

Facility CSS token bridge (keep dark bg, borrow teal accent):

```css
:root{
  --bg:#0b0f14; --card:#121820; --card2:#0e141b; --border:#1f2a36; --text:#e8eef4; --muted:#8b9bab;
  --accent:#0e7490; /* match home teal */
  --accent-ink:#e8eef4;
  --ok:#34c98e; --warn:#f5b544; --p1:#f4574d; --p2:#f5a044; --p3:#5b8def;
  --radius:12px;
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}
.demo-strip{border:1px dashed #345; border-radius:var(--radius); padding:10px 12px; background:#0d1520}
.demo-strip summary{cursor:pointer; color:var(--muted); font-size:12px; margin-bottom:8px}
.loading .alert-queue, .loading #open-cases{opacity:.45; pointer-events:none}
```

Header logo: copy the SVG ladder mark from `static/index.html` into `.logo-mark` (replace list glyph).

Wrap demo buttons:

```html
<details class="demo-strip" open>
  <summary>Demo scenarios (judge / local only)</summary>
  <div class="demo-actions"> ... existing three buttons ... </div>
</details>
```

Move reply banner below the strip; add dismiss button on banner:

```javascript
banner.innerHTML = `<span>${text}</span> <button type="button" class="btn subtle" id="banner-dismiss">Dismiss</button>`;
$("#banner-dismiss").onclick = () => { banner.hidden = true; };
```

`refresh` loading:

```javascript
async function refresh(){
  state.loading = true;
  document.body.classList.add("loading");
  try {
    // existing Promise.all ...
  } finally {
    state.loading = false;
    document.body.classList.remove("loading");
  }
}
```

Ensure Caregiver console link is `href="/ui/"` with visible label next to Sign out; home console Facility link is `href="/ui/facility/"`.

- [ ] **Step 4: Full suite + commit**

```bash
python -m pytest -q
git add src/care_ladder/api/static/facility/index.html \
  src/care_ladder/api/static/index.html \
  tests/test_facility_ui.py tests/test_ui_facility_mode.py
git commit -m "feat(facility): unify chrome, quarantine demo strip, loading state"
```

- [ ] **Step 5: Open PR**

Title: `feat(facility): console UI polish (ARIA, SLA, audit, breaks, chrome)`  
Body: checklist Tasks 1–6, screenshots of Alert/Cases/Audit, note baseline after `1f14a61`, Mac Hermes implement.

---

## Hermes handoff checklist

1. Read design + this plan.
2. Branch from latest `main` (at/after `1f14a61`).
3. Execute Tasks 0→6 in order.
4. Do not reopen N1 / billing remediations unless a regression appears.
5. Do not change Home Path A/B fixtures.
6. Do not merge without `python -m pytest -q` green.
7. Do not touch Devpost Final Submit.
8. After merge: smoke https://care-ladder-saas.onrender.com `/ui/facility/` (auth-off demo) and facility login path.

## Test plan (acceptance)

| # | Action | Expected |
| --- | --- | --- |
| 1 | Tab to alert, Enter | Selected ring; detail loads |
| 2 | Change assign select, trigger refresh via priority | Draft select preserved while dirty |
| 3 | Assign Maria | Owner `MG · Maria G.` |
| 4 | Close with 10 chars | Inline error + toast; case stays open |
| 5 | Ack + close with 20+ chars | Audit KPIs show median ack/handling; register lists closed case |
| 6 | Expand register row | Ladder transcript + timing rail + docs; owner is a display name |
| 7 | Positive fixture | Resident-resolved row with violet chip; filter hides staff cases |
| 8 | Break 30m on Jamie | Countdown `on break · Nm left` |
| 9 | Collapse demo strip | Floor UI remains; empty copy has no demo pointer |
| 10 | Compare home vs facility logo | Same ladder mark; teal accent on facility |
| 11 | `pytest -q` | Green offline |

## Self-review

- Spec coverage: ARIA/selection/form preserve, owner+errors+SLA, audit register mock (KPIs + expandable drill-down + lead actions), break UX, visual/demo/loading/nav → Tasks 2–6 (+ Task 1 API/register). Aging chips in Task 2.
- No TBD placeholders; concrete code in each implement step.
- Types/names: `_case_out(c, state)`, `median_ack_sec`, `owner_display_name`, `detailDirty`, `demo-strip` consistent.
- N1 explicitly excluded (already fixed).
