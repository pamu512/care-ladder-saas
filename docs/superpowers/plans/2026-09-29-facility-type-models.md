# Facility-Type Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Oct 31 multi-type SaaS slice: `facility_type` on tenants, zone-kind check-in (common auto-escalates; private keeps spoken), place + person on alert/case rows, admin multi-incident modes (one-focus + pin/peek), and thin daycare / rehab demo packs on the shared facility console.

**Architecture:** One console. Tenant carries `facility_type` and concurrency settings. Care-plan `Zone.kind` (`private` | `common`) steers the ladder: common skips `speaker_prompt` / check-in `wait` and continues to notify rungs. Cases/alerts gain subject fields. Facility packs are YAML + a small Python loader that supplies labels, SLA defaults, cue allowlist, roles, and concurrency defaults. UI polish (Audit register, etc.) already merged via PR #8; this plan sits on current `main`.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy Tenant/CaseRow, Pydantic CarePlan/Zone, vanilla facility `index.html`, pytest + TestClient, YAML under `configs/`.

**Spec:** `docs/superpowers/specs/2026-09-29-facility-type-models-design.md`

## Global Constraints

- Repo: `pamu512/care-ladder-saas`. Not OpenCV Care Ladder; not Alexa/Fire TV.
- Baseline: current `origin/main` (UI polish merged; tip was `ae269c1` when this plan was written; re-fetch before coding).
- Implement via **Mac Hermes only** (no Cursor cloud agents for code).
- No em dashes (long dash or `\u2014`) in user-facing copy, commit subjects, or new YAML messages.
- TDD: failing test → implement → pass → commit per task.
- Do not Final-Submit Devpost.
- Prefer trailing slash `/ui/facility/` in links.
- If schedule slips: ship Tasks 1–4 before Task 6/7 packs; pin/peek can be minimal chips; `multi_own` may stay settings-flag + toast "coming soon".

## File map

| Path | Role |
|------|------|
| `src/care_ladder/db/models.py` | `Tenant.facility_type`, `Tenant.facility_settings` (JSON), `CaseRow` subject columns |
| `src/care_ladder/models.py` | `Zone.kind` |
| `src/care_ladder/facility/models.py` | `Case` subject + place fields; concurrency helpers |
| `src/care_ladder/facility/packs.py` | Load pack YAML; defaults by type |
| `src/care_ladder/facility/service.py` | Concurrency settings; multi-own gate on assign |
| `src/care_ladder/ladder/orchestrator.py` | Skip spoken check-in when zone kind is `common` |
| `src/care_ladder/api/app.py` | Tenant/facility settings routes; alert/case DTO fields; demo type picker |
| `src/care_ladder/api/static/facility/index.html` | Place+person rows; pin/peek; settings strip |
| `configs/facility_packs/*.yaml` | Pack definitions |
| `configs/demo_facility.yaml` / `demo_daycare.yaml` / `demo_rehab.yaml` | Zone kinds + demo plans |
| `tests/test_facility_packs.py`, `test_zone_kind_ladder.py`, `test_facility_concurrency.py`, extend `test_facility_api.py` / `test_facility_ui.py` | Coverage |

---

### Task 0: Land design + this plan

**Files:**
- Create: `docs/superpowers/specs/2026-09-29-facility-type-models-design.md`
- Create: `docs/superpowers/plans/2026-09-29-facility-type-models.md` (this file)

**Interfaces:**
- Consumes: none
- Produces: docs on branch `docs/facility-type-models` (PR #9)

- [ ] **Step 1:** Confirm both files exist on the branch.

- [ ] **Step 2: Commit** (if not already)

```bash
git add docs/superpowers/specs/2026-09-29-facility-type-models-design.md \
  docs/superpowers/plans/2026-09-29-facility-type-models.md
git commit -m "docs(facility): type-models design and Hermes plan"
```

---

### Task 1: `facility_type` on tenant + settings JSON

**Files:**
- Modify: `src/care_ladder/db/models.py`
- Modify: `src/care_ladder/api/app.py` (tenant record helpers, billing seed, `/auth` or `/tenant/me` style payload if present)
- Create: `tests/test_facility_type_tenant.py`

**Interfaces:**
- Consumes: existing `Tenant` row / in-memory `billing_tenants`
- Produces:
  - `FacilityType = Literal["daycare_kids", "assisted_living", "rehab", "old_age_home"]`
  - `Tenant.facility_type: str` default `"assisted_living"` (or `"old_age_home"` if demo facility is memory-care branded; pick one and use everywhere)
  - `Tenant.facility_settings: dict` JSON default `{}` with shape:

```python
{
  "concurrency": {
    "one_focus": True,
    "pin_peek": False,
    "pin_limit": 3,
    "multi_own": False,
  }
}
```

  - In-memory billing dict keys mirror the same fields for auth-off demos
  - `GET /facility/settings` → `{ facility_type, concurrency, vocabulary }` (vocabulary may be empty until Task 2)
  - `PATCH /facility/settings` → body `{ facility_type?, concurrency? }` (facility mode tenants only)

- [ ] **Step 1: Write failing tests**

```python
def test_tenant_defaults_facility_type(client_facility):
    r = client_facility.get("/facility/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["facility_type"] in {
        "daycare_kids", "assisted_living", "rehab", "old_age_home"
    }
    assert "concurrency" in body
    assert body["concurrency"]["one_focus"] is True

def test_patch_facility_type(client_facility):
    r = client_facility.patch(
        "/facility/settings",
        json={"facility_type": "daycare_kids"},
    )
    assert r.status_code == 200
    assert r.json()["facility_type"] == "daycare_kids"
```

- [ ] **Step 2: Run tests (expect fail)**

```bash
pytest tests/test_facility_type_tenant.py -v
```

Expected: FAIL (route or fields missing)

- [ ] **Step 3: Implement**

Add columns on `Tenant` (nullable JSON / string with defaults). For SQLite/Postgres already used by the app, follow the same pattern as other additive columns (create_all / migrate-on-start if that is how this repo boots). Seed `demo-facility` as `assisted_living` or `old_age_home`. Wire GET/PATCH.

- [ ] **Step 4: Run tests (expect pass)**

```bash
pytest tests/test_facility_type_tenant.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/db/models.py src/care_ladder/api/app.py tests/test_facility_type_tenant.py
git commit -m "feat(facility): tenant facility_type and concurrency settings API"
```

---

### Task 2: Facility packs + `Zone.kind`

**Files:**
- Modify: `src/care_ladder/models.py` (`Zone`)
- Create: `src/care_ladder/facility/packs.py`
- Create: `configs/facility_packs/assisted_living.yaml`
- Create: `configs/facility_packs/daycare_kids.yaml`
- Create: `configs/facility_packs/rehab.yaml`
- Create: `configs/facility_packs/old_age_home.yaml`
- Modify: `configs/demo_facility.yaml` (add `kind` on zones)
- Create: `tests/test_facility_packs.py`
- Modify: `tests/test_facility_plan_loader.py` if zone validation needs updates

**Interfaces:**
- Consumes: `FacilityType` from Task 1
- Produces:

```python
# Zone
class Zone(BaseModel):
    id: str
    polygon: list[list[float]]
    kind: Literal["private", "common"] = "private"  # default private for back-compat

# packs.load(facility_type) -> FacilityPack
class FacilityPack(BaseModel):
    facility_type: str
    vocabulary: dict[str, str]  # e.g. subject=resident, place=room, lead=Floor lead
    sla_ack_sec: int
    sla_handling_sec: int
    cue_allowlist: list[str]
    roles: list[dict]  # [{id, display_name, role, initials}, ...]
    concurrency: dict[str, Any]
```

YAML example (`daycare_kids.yaml`):

```yaml
facility_type: daycare_kids
vocabulary:
  subject: child
  place: classroom
  lead: Lead teacher
sla_ack_sec: 60
sla_handling_sec: 600
cue_allowlist: [no_visibility, distress_heuristic, no_movement]
concurrency:
  one_focus: true
  pin_peek: true
  pin_limit: 3
  multi_own: false
roles:
  - { id: staff-avery, display_name: Avery Kim, role: Lead teacher, initials: AK }
```

`GET /facility/settings` merges pack vocabulary + SLA into the response after load.

- [ ] **Step 1: Failing test**

```python
from care_ladder.facility.packs import load_pack
from care_ladder.plan_loader import load_care_plan
from pathlib import Path

def test_load_daycare_pack():
    p = load_pack("daycare_kids")
    assert p.vocabulary["subject"] == "child"
    assert p.concurrency["pin_peek"] is True

def test_zone_kind_roundtrip(tmp_path):
    # minimal yaml with kind: common
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    assert all(hasattr(z, "kind") for z in plan.zones)
```

- [ ] **Step 2: Run (expect fail)** → **Step 3: Implement** → **Step 4: Pass** → **Step 5: Commit**

```bash
git add src/care_ladder/models.py src/care_ladder/facility/packs.py \
  configs/facility_packs configs/demo_facility.yaml tests/test_facility_packs.py
git commit -m "feat(facility): zone kind and facility-type packs"
```

Mark existing `demo_facility.yaml` zones: bedroom/private rooms `private`; `common_room` (and similar) `kind: common`.

---

### Task 3: Ladder skips spoken check-in in common zones

**Files:**
- Modify: `src/care_ladder/ladder/orchestrator.py`
- Modify: `src/care_ladder/vision/cues.py` and/or cue → incident wiring so the active `zone_id` / zone kind is available to the ladder
- Create: `tests/test_zone_kind_ladder.py`
- Optionally: `configs/demo_daycare.yaml` with only common zones (used fully in Task 6)

**Interfaces:**
- Consumes: `Zone.kind`, plan rungs
- Produces: When the cue's zone has `kind == "common"`, orchestrator **does not** run `speaker_prompt` (and the immediate follow-on check-in `wait` rung). It appends audit events:

```python
{"tool": "speaker_prompt", "detail": {"result": "skipped_common_zone", "zone_id": "...", "zone_kind": "common"}}
```

Then continues to `notify_*` / facility rungs. Private zones keep today's behavior.

Pass zone context into `run_ladder` (preferred: `zone_id: str | None` and resolve kind from `plan.zones`; if missing, default `private` for back-compat).

- [ ] **Step 1: Failing test**

```python
def test_common_zone_skips_speaker(plan_common, speaker, notify):
    # build plan with zone kind=common and speaker_prompt rung
    incident = run_ladder(...)  # project helpers
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools  # logged
    # detail shows skipped
    sp = next(e for e in incident.events if e.tool == "speaker_prompt")
    assert sp.detail.get("result") == "skipped_common_zone"
    # notify still ran
    assert any(e.tool.startswith("notify") for e in incident.events)

def test_private_zone_still_speaks(plan_private, speaker):
    speaker.script = ["I'm fine"]
    incident = run_ladder(...)
    sp = next(e for e in incident.events if e.tool == "speaker_prompt")
    assert sp.detail.get("result") != "skipped_common_zone"
```

Use existing fixture patterns from `tests/test_facility_fixture.py` / ladder unit tests.

- [ ] **Step 2–5:** fail → implement skip branch next to current `speaker_prompt` handling → pass → commit

```bash
git commit -m "feat(ladder): skip spoken check-in in common zones"
```

---

### Task 4: Place + person on cases and alerts

**Files:**
- Modify: `src/care_ladder/facility/models.py` (`Case`)
- Modify: `src/care_ladder/db/models.py` (`CaseRow`)
- Modify: `src/care_ladder/facility/repository.py`
- Modify: `src/care_ladder/api/app.py` (`_case_out`, alerts list/detail, open-case paths)
- Modify: `src/care_ladder/api/static/facility/index.html` (alert cards + case rows)
- Modify: `tests/test_facility_api.py`, `tests/test_facility_domain.py`, `tests/test_facility_ui.py`

**Interfaces:**
- Consumes: pack vocabulary (for empty-subject fallback label)
- Produces on Case / alert DTO:

```python
{
  "place_label": str,              # was room_label; keep room_label as alias = place_label
  "room_label": str,               # back-compat
  "subject_display_name": str | None,
  "subject_kind": "child" | "resident" | "patient" | None,
  "subject_id": str | None,
}
```

UI card title line:

```text
{place_label} · {subject_display_name or "Unknown " + vocabulary.subject}
```

plus `human_id` secondary. No raw staff ids.

When opening a case from an alert, copy subject/place from the alert/incident payload (fixtures must seed them).

- [ ] **Step 1: Failing API test**

```python
def test_alert_includes_place_and_subject(client_facility):
    # trigger or seed an open alert/case with subject
    r = client_facility.get("/facility/alerts")
    row = r.json()["alerts"][0]
    assert "place_label" in row or "room_label" in row
    assert "subject_display_name" in row
```

- [ ] **Step 2–5:** implement persistence + UI → commit

```bash
git commit -m "feat(facility): place and person on alerts and cases"
```

---

### Task 5: Multi-incident concurrency UI (one-focus + pin/peek)

**Files:**
- Modify: `src/care_ladder/facility/service.py` (`assign` respects `multi_own`)
- Modify: `src/care_ladder/api/app.py` (PATCH settings already from Task 1; optional `GET` pins are client-only)
- Modify: `src/care_ladder/api/static/facility/index.html`
- Create: `tests/test_facility_concurrency.py`
- Extend: `tests/test_facility_ui.py`

**Interfaces:**
- Consumes: `concurrency` from settings/pack
- Produces:
  - Client reads `/facility/settings` on load
  - If `pin_peek`: each alert/case row gets a Pin control; pinned ids in `sessionStorage`; side panel lists up to `pin_limit` compact cards (place · person · P# · age)
  - If `multi_own` is false: assign still clears previous owner's single `active_case_id` (today)
  - If `multi_own` is true: allow a second assign without clearing the first; track `active_case_ids: list[str]` **or** keep primary `active_case_id` plus `parked_case_ids` on staff (prefer additive JSON on StaffRow if needed). If this blows the schedule, leave `multi_own` false in UI with toast "Multi-own is not enabled for this facility yet" when toggled on without backend support
  - Admin/demo strip: checkboxes bound to PATCH `/facility/settings`

- [ ] **Step 1: Failing tests**

```python
def test_settings_pin_peek_roundtrip(client_facility):
    r = client_facility.patch(
        "/facility/settings",
        json={"concurrency": {"one_focus": True, "pin_peek": True, "pin_limit": 3, "multi_own": False}},
    )
    assert r.status_code == 200
    assert r.json()["concurrency"]["pin_peek"] is True

def test_assign_rejects_second_case_when_multi_own_off(state):
    # existing staff on_case; assign another without pull → error or no-op per today's rules
    ...
```

- [ ] **Step 2–5:** implement → commit

```bash
git commit -m "feat(facility): pin-peek concurrency and settings UI"
```

---

### Task 6: Thin daycare demo pack + fixtures

**Files:**
- Create: `configs/demo_daycare.yaml` (all zones `kind: common`; no reliance on kid speech)
- Modify: `src/care_ladder/api/app.py` (demo fixture button or `?facility_type=daycare_kids` bootstrap)
- Modify: `src/care_ladder/api/static/facility/index.html` (demo strip: "Daycare demo")
- Create/extend: `tests/test_demo_daycare.py` or fixture tests

**Interfaces:**
- Consumes: packs + zone skip from Tasks 2–3
- Produces: One-click daycare demo that:
  1. Sets tenant `facility_type=daycare_kids`
  2. Loads daycare pack roles/vocabulary
  3. Fires a cue in a common classroom zone
  4. Opens/pages a case **without** a successful spoken check-in
  5. Shows place · child on the alert row

- [ ] **Step 1: Failing test** for fixture endpoint or scripted ladder path
- [ ] **Step 2–5:** implement → commit

```bash
git commit -m "feat(facility): daycare demo pack and common-zone fixture"
```

---

### Task 7: Thin rehab demo pack

**Files:**
- Ensure `configs/facility_packs/rehab.yaml` is complete (Task 2)
- Create: `configs/demo_rehab.yaml` (mix private bay + common gym)
- Modify: demo strip + fixture similar to Task 6
- Tests mirroring daycare

**Interfaces:**
- Same as Task 6 with `facility_type=rehab`, vocabulary patient/bay, one private spoken path and one common auto-escalate path if time allows (minimum: one common gym path).

- [ ] Steps: fail → implement → pass → commit

```bash
git commit -m "feat(facility): rehab demo pack and fixture"
```

---

### Task 8: Smoke + copy sweep

**Files:** touched UI/YAML from prior tasks

- [ ] **Step 1:** Grep for em dashes in new/changed user-facing strings:

```bash
rg -n $'\u2014' src/care_ladder/api/static/facility configs/facility_packs configs/demo_daycare.yaml configs/demo_rehab.yaml || true
```

Expected: no matches in those paths (fix any you introduced).

- [ ] **Step 2:** Full facility-related pytest:

```bash
pytest tests/test_facility_*.py tests/test_zone_kind_ladder.py tests/test_facility_packs.py tests/test_facility_type_tenant.py tests/test_facility_concurrency.py -q
```

Expected: pass

- [ ] **Step 3:** Manual smoke on Mac: `/ui/facility/` with assisted, daycare, rehab demos; confirm common vs private ladder; pin two alerts; place · person visible.

- [ ] **Step 4: Commit** any copy fixes; open/merge implementation PR (Hermes); do not Final-Submit Devpost.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `facility_type` on tenant | 1 |
| Zone kind private/common | 2, 3 |
| Spoken only private; common auto-escalate | 3 |
| Daycare classrooms common / no kid ack | 2, 3, 6 |
| Place + person identity | 4 |
| Admin concurrency one_focus / pin_peek / multi_own | 1, 5 |
| Four packs | 2, 6, 7 |
| Oct 31 A–E | 1–7 |
| No em dashes; Mac Hermes | Global + 8 |

## Execution order

After PR #9 docs merge: Hermes implements Tasks 1→8 on a feature branch from latest `main`. Prefer merging type-model work in reviewable PRs (API/packs first, then ladder, then UI, then demos).
