# Facility Console UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the shipped Mockup H facility floor console so floor leads can triage with keyboard, see owners/SLA/aging, get action errors, audit time metrics with per-case drill-down, choose break durations with countdown, and experience one product language with the home console (demo chrome quarantined).

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

### Task 1: Enrich `_case_out` + audit time metrics (API)

**Files:**
- Modify: `src/care_ladder/api/app.py` (`_case_out` and any callers that need `state`)
- Modify: `src/care_ladder/facility/service.py` (`FacilityState.summary`)
- Modify: `tests/test_facility_api.py`
- Create or modify: `tests/test_facility_domain.py` (summary medians unit test)

**Interfaces:**
- Consumes: `Case.ack_at`, `Case.closed_at`, `Case.sla_ack_sec`, `Case.sla_handling_sec`, `state.case_opened_times()`, `state.staff`
- Produces:
  - `_case_out(c, state) -> dict` with keys: existing plus `opened_at`, `owner_display_name`, `owner_initials`, `sla_ack_sec`, `sla_handling_sec`
  - `summary()` adds `median_ack_sec: int | None`, `median_handling_sec: int | None`, `pct_acked_in_sla: int | None`

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
    assert c["opened_at"]  # non-empty ISO
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
    assert s["median_ack_sec"] == 60  # opened 90s ago, ack 30s ago
    assert s["median_handling_sec"] == 30
    assert s["pct_acked_in_sla"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_facility_api.py::test_case_out_includes_owner_and_opened \
  tests/test_facility_api.py::test_audit_summary_time_metrics_after_ack_close \
  tests/test_facility_domain.py::test_summary_median_ack_and_handling -v
```

Expected: FAIL (missing keys / wrong summary fields)

- [ ] **Step 3: Implement `_case_out` and `summary`**

In `app.py`, replace `_case_out` with a state-aware version and update every caller inside the facility API block to pass `state`:

```python
def _case_out(c, state) -> dict:
    owner = state.staff.get(c.owner_staff_id) if c.owner_staff_id else None
    opened = state.case_opened_times().get(c.id)
    return {
        "id": c.id,
        "human_id": c.human_id,
        "incident_id": c.incident_id,
        "room_label": c.room_label,
        "title": c.title,
        "origin": c.origin,
        "priority": c.priority,
        "state": c.state,
        "owner_staff_id": c.owner_staff_id,
        "owner_display_name": owner.display_name if owner else None,
        "owner_initials": owner.initials if owner else None,
        "slack_thread_url": c.slack_thread_url,
        "ack_at": c.ack_at.isoformat() if c.ack_at else None,
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
        "opened_at": opened,
        "documentation": c.documentation,
        "sla_ack_sec": c.sla_ack_sec,
        "sla_handling_sec": c.sla_handling_sec,
    }
```

In `service.py`, replace `summary` with:

```python
def summary(self) -> dict[str, Any]:
    open_cases = [c for c in self.cases.values() if c.state != "closed"]
    closed_today = [c for c in self.cases.values() if c.state == "closed"]
    outcomes: dict[str, int] = {}
    for c in self.cases.values():
        key = c.origin.replace("from_", "").replace("_reply", "")
        outcomes[key] = outcomes.get(key, 0) + 1
    for _ in self.resident_resolved:
        outcomes["positive"] = outcomes.get("positive", 0) + 1

    opened_times = self.case_opened_times()

    def _parse(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None

    ack_secs: list[int] = []
    handling_secs: list[int] = []
    in_sla = 0
    ack_n = 0
    for c in self.cases.values():
        opened = _parse(opened_times.get(c.id))
        if c.ack_at is not None and opened is not None:
            ack_n += 1
            sec = int((c.ack_at - opened).total_seconds())
            if sec < 0:
                sec = 0
            ack_secs.append(sec)
            if sec <= c.sla_ack_sec:
                in_sla += 1
        if c.ack_at is not None and c.closed_at is not None:
            h = int((c.closed_at - c.ack_at).total_seconds())
            handling_secs.append(max(0, h))

    def _median(vals: list[int]) -> int | None:
        if not vals:
            return None
        s = sorted(vals)
        mid = len(s) // 2
        if len(s) % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) // 2

    return {
        "cases_open": len(open_cases),
        "cases_closed_today": len(closed_today),
        "resident_resolved_today": len(self.resident_resolved),
        "overrides_today": len(self.overrides),
        "outcomes": outcomes,
        "median_ack_sec": _median(ack_secs),
        "median_handling_sec": _median(handling_secs),
        "pct_acked_in_sla": int(round(100 * in_sla / ack_n)) if ack_n else None,
    }
```

Also include `opened_at` on alert queue items (each already embeds `case: _case_out(...)`).

- [ ] **Step 4: Run tests: PASS**

```bash
python -m pytest tests/test_facility_api.py tests/test_facility_domain.py -q
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/api/app.py src/care_ladder/facility/service.py \
  tests/test_facility_api.py tests/test_facility_domain.py
git commit -m "feat(facility): case owner names, opened_at, audit time KPIs"
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

### Task 4: Audit time KPIs, outcome labels, per-case drill-down

**Files:**
- Modify: `src/care_ladder/api/static/facility/index.html`
- Modify: `tests/test_facility_ui.py`

**Interfaces:**
- Consumes: Task 1 summary time fields; `/facility/alerts/{incident_id}` for rungs
- Produces: labeled outcomes; case list; `#audit-detail` panel

- [ ] **Step 1: Failing test**

```python
def test_facility_audit_ui_hooks(client):
    html = client.get("/ui/facility/").text
    assert "median_ack_sec" in html
    assert "audit-detail" in html
    assert "Negative reply" in html  # label map present as string
```

- [ ] **Step 2: Run: expect FAIL**

- [ ] **Step 3: Implement `renderAudit`**

```javascript
const OUTCOME_LABELS = {
  negative: "Negative reply",
  silence: "Silence",
  cue: "Cue",
  manual: "Manual",
  positive: "Positive",
};

function fmtSec(n){
  if (n === null || n === undefined) return "n/a";
  return n + "s";
}

async function renderAudit(){
  const {status, body} = await japi("/facility/audit/summary");
  if (status !== 200){ showToast((body&&body.detail)||"Audit failed", true); return; }
  const k = $("#kpi");
  const kpis = [
    ["Open cases", body.cases_open],
    ["Closed today", body.cases_closed_today],
    ["Resident-resolved", body.resident_resolved_today],
    ["Overrides", body.overrides_today],
    ["Median time-to-ack", body.median_ack_sec == null ? "n/a" : body.median_ack_sec + "s"],
    ["Median handling", body.median_handling_sec == null ? "n/a" : body.median_handling_sec + "s"],
    ["Acked in SLA", body.pct_acked_in_sla == null ? "n/a" : body.pct_acked_in_sla + "%"],
  ];
  k.innerHTML = kpis.map(([l,n]) => `<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
  // widen grid for 7 KPIs
  k.style.gridTemplateColumns = "repeat(auto-fit,minmax(140px,1fr))";

  const out = body.outcomes || {};
  const total = Object.values(out).reduce((a,b)=>a+b,0) || 1;
  $("#outcome-bars").innerHTML = Object.entries(out).map(([k2,v]) => `
    <div class="bar"><span>${OUTCOME_LABELS[k2]||k2}</span>
    <div class="track"><div class="fill" style="width:${Math.round(100*v/total)}%"></div></div>
    <span>${v}</span></div>`).join("") || '<p class="muted">No cases yet today.</p>';

  $("#overrides-line").textContent =
    `${body.overrides_today||0} logged override(s) today (priority changes, pull-off-break).`;

  // per-case list
  const all = [...(state.cases.open||[]), ...(state.cases.closed_today||[])];
  const list = $("#audit-cases");
  if (list){
    list.innerHTML = all.length ? all.map(c => `
      <button type="button" class="btn subtle" data-audit-incident="${c.incident_id}">
        ${c.human_id} · ${c.priority} · ${c.state}
      </button>`).join("") : '<p class="muted">No cases to review.</p>';
    list.querySelectorAll("[data-audit-incident]").forEach(b => b.addEventListener("click", () => openAuditDetail(b.dataset.auditIncident)));
  }
}

async function openAuditDetail(incidentId){
  const panel = $("#audit-detail");
  const {status, body} = await japi(`/facility/alerts/${incidentId}`);
  if (status !== 200){ showToast("Could not load case story", true); return; }
  const c = body.case || {};
  panel.hidden = false;
  panel.innerHTML = `
    <h3>Incident report · ${c.human_id||incidentId}</h3>
    <p class="small">Reply: <strong>${body.reply_class||"n/a"}</strong> · Origin: ${c.origin||"-"}</p>
    <p class="small">${slaLine(c)}</p>
    <ol class="small">${(body.rungs||[]).map(r => `<li>${r}</li>`).join("") || "<li>No ladder events</li>"}</ol>
    <p class="small muted">${c.documentation ? ("Close notes: " + c.documentation) : "Still open or no docs."}</p>
    <button type="button" class="btn subtle" id="audit-detail-close">Close</button>`;
  $("#audit-detail-close").onclick = () => { panel.hidden = true; };
}
```

Add to Audit section HTML:

```html
<div class="card" style="margin-top:12px">
  <h3>Cases</h3>
  <div id="audit-cases"></div>
  <div id="audit-detail" class="card" hidden style="margin-top:10px"></div>
</div>
```

Do not use an em dash character anywhere in new copy (use `n/a` or `-`).

- [ ] **Step 4: PASS + commit**

```bash
python -m pytest tests/test_facility_ui.py -q
git add src/care_ladder/api/static/facility/index.html tests/test_facility_ui.py
git commit -m "feat(facility): audit time KPIs and per-case incident report"
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
| 5 | Ack + close with 20+ chars | Audit medians non-null; outcome "Negative reply" |
| 6 | Audit case button | Ladder list + reply class visible |
| 7 | Break 30m on Jamie | Countdown `on break · Nm left` |
| 8 | Collapse demo strip | Floor UI remains; empty copy has no demo pointer |
| 9 | Compare home vs facility logo | Same ladder mark; teal accent on facility |
| 10 | `pytest -q` | Green offline |

## Self-review

- Spec coverage: ARIA/selection/form preserve, owner+errors+SLA, audit times+drill-down, break UX, visual/demo/loading/nav → Tasks 2–6 (+ Task 1 API). Aging chips in Task 2.
- No TBD placeholders; concrete code in each implement step.
- Types/names: `_case_out(c, state)`, `median_ack_sec`, `owner_display_name`, `detailDirty`, `demo-strip` consistent.
- N1 explicitly excluded (already fixed).
