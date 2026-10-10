# Facility Floor Console (Mockup H) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Mockup H facility floor console (Alert center / Cases / Audit) with LLM reply classification (Vertex), Postgres cases + staff/break, ladder jump on negative replies, while leaving the Home caregiver console unchanged.

**Architecture:** Vertical slices on `pamu512/care-ladder-saas`. Domain modules under `src/care_ladder/facility/`; Postgres models via existing SQLAlchemy `Base` + `create_all` bootstrap (no Alembic required this pass). Facility UI is a separate static shell served only for facility tenants. Vertex classifier is optional at runtime; fixtures and tests never require cloud credentials.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, Postgres (`DATABASE_URL`), existing session cookie auth, vanilla HTML/CSS/JS static UI (match Mockup H), Google Cloud Vertex for LLM classify (env-gated), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-facility-floor-console-mockup-h-design.md`  
**Visual:** keep a copy of Mockup H HTML in `docs/galuxium/mockup-h-break-aware-routing.html` for implementers.

## Global Constraints

- Repo: `pamu512/care-ladder-saas` (Galaxium Care Ladder SaaS). Not OpenCV Care Ladder; not Alexa/Fire TV track.
- Home tenant UI must keep Path A / Path B caregiver console behavior.
- Facility Mockup H only when tenant `mode=facility` (auth-on) or facility demo session.
- No em dashes (long dash) in user-facing copy or commit subject fluff; use periods, commas, parentheses.
- Not a medical device; dial stubs only; webhook/billing behavior unchanged.
- TDD: failing test → implement → pass → commit per task.
- Offline CI: never require Vertex; mock classifier or fixture-only path.
- Prefer `_tenant_store` / Postgres patterns already used for incidents.
- Implement on a feature branch; open PR; do not Final-Submit Devpost.
- Stretch tasks (S*) only after Task 8 green unless blocked.

---

### Task 0: Add design + mockup to repo

**Files:**
- Create: `docs/superpowers/specs/2026-09-28-facility-floor-console-mockup-h-design.md`
- Create: `docs/superpowers/plans/2026-09-28-facility-floor-console-mockup-h.md` (this file)
- Create: `docs/galuxium/mockup-h-break-aware-routing.html` (static mockup source)

- [ ] **Step 1:** Copy the approved design and this plan into the paths above from the handoff packet.
- [ ] **Step 2:** Commit

```bash
git add docs/superpowers/specs/2026-09-28-facility-floor-console-mockup-h-design.md \
  docs/superpowers/plans/2026-09-28-facility-floor-console-mockup-h.md \
  docs/galuxium/mockup-h-break-aware-routing.html
git commit -m "docs(facility): Mockup H floor console design and plan"
```

---

### Task 1: ReplyClass + rule/LLM classifier interface (offline-safe)

**Files:**
- Create: `src/care_ladder/facility/__init__.py`
- Create: `src/care_ladder/facility/reply_class.py`
- Create: `src/care_ladder/facility/classifier.py`
- Create: `tests/test_facility_reply_classifier.py`

**Interfaces:**
- Produces: `ReplyClass` Literal; `classify_reply(text: str, *, fixture_class: ReplyClass | None = None) -> ClassifyResult`
- `ClassifyResult(reply_class: ReplyClass, source: Literal["fixture","llm","fallback"], rationale: str)`

- [ ] **Step 1: Write the failing test**

```python
from care_ladder.facility.classifier import classify_reply
from care_ladder.facility.reply_class import ReplyClass

def test_fixture_override_wins():
    r = classify_reply("I am fine", fixture_class=ReplyClass.negative)
    assert r.reply_class == ReplyClass.negative
    assert r.source == "fixture"

def test_fallback_without_vertex_env(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    r = classify_reply("I can't get up")
    assert r.reply_class in {ReplyClass.negative, ReplyClass.unclear, ReplyClass.silence, ReplyClass.positive}
    assert r.source in {"fallback", "llm"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_facility_reply_classifier.py -v`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement**

```python
# reply_class.py
from enum import StrEnum
class ReplyClass(StrEnum):
    positive = "positive"
    negative = "negative"
    silence = "silence"
    unclear = "unclear"
```

`classify_reply`: if `fixture_class` set → return fixture. Else if Vertex env present → call `vertex_classify` (stub raising until Task 1b). Else **keyword fallback** lists for positive/negative (so offline demos still show negative jump without Vertex). Empty text → silence.

- [ ] **Step 4: Run tests: PASS**
- [ ] **Step 5: Commit** `feat(facility): reply classification interface with fixture override`

---

### Task 1b: Vertex LLM adapter (env-gated)

**Files:**
- Create: `src/care_ladder/facility/vertex_classify.py`
- Modify: `src/care_ladder/facility/classifier.py`
- Modify: `tests/test_facility_reply_classifier.py`
- Modify: `.env.example` (add `VERTEX_PROJECT`, `VERTEX_LOCATION`, `VERTEX_REPLY_MODEL`)

**Interfaces:**
- Produces: `vertex_classify(text: str) -> ClassifyResult` using Google GenAI / Vertex SDK already acceptable to repo deps; if SDK missing, skip test.

- [ ] **Step 1: Failing test** with monkeypatched HTTP/SDK returning `{"reply_class":"negative","rationale":"..."}`.
- [ ] **Step 2: Implement** thin adapter; prompt must force JSON enum only.
- [ ] **Step 3: Tests pass without real GCP** (mock).
- [ ] **Step 4: Commit** `feat(facility): Vertex reply classifier adapter (env-gated)`

---

### Task 2: Priority model + ladder jump on negative reply

**Files:**
- Create: `src/care_ladder/facility/priority.py`
- Modify: facility plan runner / `src/care_ladder/api/app.py` facility fixture path and/or `src/care_ladder/ladder/orchestrator.py` if rung skip lives there
- Create: `tests/test_facility_negative_jump.py`
- Modify: `configs/demo_facility.yaml` only if new rung markers needed

**Interfaces:**
- Produces: `Priority` enum P1/P2/P3; `apply_negative_reply(incident, classify_result) -> None` mutates events: `speaker_prompt` detail includes class; adds `jump` event skipping wait; sets `priority=P1`.

- [ ] **Step 1: Failing test**: run facility path with fixture negative reply; assert jump event present and priority P1; no wait tool after negative.
- [ ] **Step 2: Implement** fixture `facility_negative_reply` in `SUPPORTED_FIXTURES` + `_run_facility_negative_reply`.
- [ ] **Step 3: pytest PASS**
- [ ] **Step 4: Commit** `feat(facility): negative reply raises P1 and jumps wait rungs`

---

### Task 3: Postgres StaffMember + seed

**Files:**
- Modify: `src/care_ladder/db/models.py` (or create `src/care_ladder/facility/models.py` imported by Base metadata)
- Modify: `scripts/bootstrap_saas_demo.py`: seed 4 staff for demo-facility
- Create: `tests/test_facility_staff.py`

**Interfaces:**
- Produces: SQLAlchemy model `StaffMember`; `list_staff(session, tenant_id)`; `set_break(session, staff_id, on_break, minutes=15)`.

- [ ] **Step 1: Failing test** create_all → seed → list 4 → set Alex on break → status on_break with break_until.
- [ ] **Step 2: Implement model + bootstrap seed**
- [ ] **Step 3: PASS + commit** `feat(facility): staff roster and break_until in Postgres`

---

### Task 4: Postgres Case + open/ack/close APIs

**Files:**
- Create: `src/care_ladder/facility/cases.py`
- Modify: `src/care_ladder/db/models.py`
- Modify: `src/care_ladder/api/app.py`: mount routes
- Create: `tests/test_facility_cases_api.py`

**Interfaces:**
- Produces: `open_case_for_incident(...)`; `ack_case`; `close_case(documentation: str)` requiring `len(documentation) >= 20`.
- Stub: `slack_thread_url = f"https://example.invalid/care-floor-ops/thread/{case_id}"`

- [ ] **Step 1: Failing TestClient tests** auth-on facility session: negative fixture → case exists; ack; close with docs; second close 400.
- [ ] **Step 2: Implement**
- [ ] **Step 3: PASS + commit** `feat(facility): Postgres cases with stub Slack thread URLs`

---

### Task 5: Break-aware assign + overrides

**Files:**
- Create: `src/care_ladder/facility/routing.py`
- Modify: `src/care_ladder/api/app.py`
- Create: `tests/test_facility_routing.py`

**Interfaces:**
- Produces: `assign_alert(incident_id, staff_id, *, pull_off_break=False)`; raises 409 if on_break and not pull_off_break; logs audit override events.

- [ ] **Step 1: Failing tests** for skip-on-break and pull_off_break success.
- [ ] **Step 2: Implement assign + override actions** (`escalate`, `deescalate`, `suppress`, `repage`, `pull_off_break`).
- [ ] **Step 3: PASS + commit** `feat(facility): break-aware assignment and lead overrides`

---

### Task 6: Facility Alert + Audit read APIs

**Files:**
- Create: `src/care_ladder/facility/alerts.py`
- Create: `src/care_ladder/facility/audit_summary.py`
- Modify: `src/care_ladder/api/app.py`
- Create: `tests/test_facility_alerts_audit_api.py`

**Interfaces:**
- `GET /facility/alerts` returns `{open: [...], resident_resolved: [...]}` sorted P1→P3 then age.
- `GET /facility/audit/summary` returns KPI dict matching design §8.

- [ ] **Step 1–4:** TDD as above; commit `feat(facility): alerts and audit summary APIs`

---

### Task 7: Facility static UI (Mockup H shell wired to APIs)

**Files:**
- Create: `src/care_ladder/api/static/facility_console.html` (or split css/js)
- Modify: `src/care_ladder/api/app.py`: serve facility console for facility tenants on `/ui/` (Home keeps `index.html`)
- Create: `tests/test_facility_console_ui.py` (HTML contains tab labels + fetch paths)
- Modify: `docs/galuxium/demo-video-galuxium.md` facility shots to name new UI

**Requirements:**
- Visual structure matches Mockup H (tabs, triage, detail, cases, audit KPIs).
- Wire buttons to Task 4–6 APIs.
- Demo fixtures: Path facility silence, facility negative, resident OK (facility positive).
- No em dashes in visible strings.

- [ ] **Step 1: Failing UI content tests**
- [ ] **Step 2: Implement HTML/JS**
- [ ] **Step 3: Manual browser** facility login → negative fixture → P1 card + case
- [ ] **Step 4: Commit** `feat(facility): Mockup H floor console UI for facility tenants`

---

### Task 8: Gate notify with tenant_can_use_notify + regression suite

**Files:**
- Modify: `src/care_ladder/api/app.py` facility fixture entry to call `tenant_can_use_notify`
- Modify: tests as needed
- Run: full `pytest`

- [ ] **Step 1: Test** home plan cannot run facility notify fixture when auth-on.
- [ ] **Step 2: Implement gate**
- [ ] **Step 3: `python -m pytest -q` Expected: all green (skips OK)
- [ ] **Step 4: Commit** `fix(facility): gate facility notify with tenant_can_use_notify`
- [ ] **Step 5: Open PR** summarizing Tasks 1–8; include screenshots of Alert/Cases/Audit

---

### Task S1 (stretch): CSV audit export

- [ ] `GET /facility/audit/export.csv` + test + UI button.

### Task S2 (stretch): Pixel polish vs mockup

- [ ] Tighten CSS to mockup spacing/chips without new backend.

### Task S3 (stretch): Real Slack behind flag

- [ ] Only if `SLACK_BOT_TOKEN` set; default remains stub URLs.

### Task S4 (stretch): Quiet-hours chip from YAML

- [ ] Read plan config; display-only OK.

---

## Hermes handoff checklist

1. Read design + this plan + mockup HTML.
2. Branch from latest `main`.
3. Execute Tasks 0→8 in order; stop for product questions only if a locked decision conflicts.
4. Do not change Home caregiver console behavior.
5. Do not merge without CI green.
6. Do not touch Devpost Final Submit.
7. After PR: note Render env needs for Vertex (optional) and confirm bootstrap seeds staff.

## Test plan (acceptance)

| # | Action | Expected |
| --- | --- | --- |
| 1 | Home login demo | Existing Path A/B UI |
| 2 | Facility login demo | Alert / Cases / Audit tabs |
| 3 | Run facility positive reply fixture | Resident-resolved row; no case |
| 4 | Run facility negative reply fixture | P1 alert; jump; case open; stub Slack link |
| 5 | Assign to staff on break | 409 unless pull_off_break |
| 6 | Ack + close case with docs | Case closed; docs visible |
| 7 | Audit summary | Counts move with fixtures |
| 8 | pytest offline | Green without GCP |

## Self-review

- Spec coverage: classification, priority jump, staff/break, cases, alerts UI, audit, home isolation, stretch Slack/UI → tasks mapped.
- No TBD placeholders in task steps.
- Types: `ReplyClass`, `Priority`, `StaffMember`, `Case` names consistent across tasks.
