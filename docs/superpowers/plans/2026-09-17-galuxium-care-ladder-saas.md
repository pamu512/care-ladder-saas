# Care Ladder Galuxium SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Care Ladder as a multi-tenant hosted SaaS for Galuxium Nexus V2: Postgres tenancy with home/facility modes, Slack notify + supervisor escalate tools, Stripe Checkout for Home / Facility Starter, public HTTPS deploy, landing + demo login, and judge-ready Path A/B plus facility notify demos.

**Architecture:** Keep the existing FastAPI + orchestrator + OpenCV fixture/upload spine. Add SQLAlchemy Postgres models (`Tenant`, `User`, `IncidentRow`, `AuditEventRow`, `Subscription`; care plans remain YAML templates keyed by tenant mode) behind a `PostgresAuditStore` that preserves the `AuditStore.save/get/list_incidents` surface. Auth is password + signed session cookie with `tenant_id` on every query. Facility mode loads `configs/demo_facility.yaml` and runs new channel tools `notify_channel` / `notify_supervisor` (real Slack webhook when `SLACK_WEBHOOK_URL` is set, else audit `adapter=stub`). Billing uses Stripe Checkout + webhook to set `tenant.plan` / `subscription_status`; plan gating unlocks facility notify UI. Deploy on Fly.io or Render with Dockerfile + managed Postgres.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, pydantic v2, SQLAlchemy 2.x + psycopg (v3), Alembic, itsdangerous (session), passlib[bcrypt] or bcrypt, httpx, Stripe Python SDK, PyYAML, OpenCV 5 (existing), pytest, httpx ASGI test client; Fly.io or Render + Postgres; optional S3-compatible clip storage via existing `CloudSinks`.

## Global Constraints

- Spec (authoritative): `docs/superpowers/specs/2026-09-17-galuxium-care-ladder-saas-design.md`
- No clinical / medical diagnosis claims in UI or copy
- `emergency.enabled` false by default; never live 911 in demo
- Demo phones reserved `+1XX55501XX` under `CARE_LADDER_ENV=demo`
- Privacy: blur/silhouette before persisting frames
- StubDialer unless secret-gated real provider
- notify adapters: real Slack webhook when env set, else audit `adapter=stub`
- ReadyPup is RevenueCat — do not build ReadyPup here
- Hunt/Tarka out of scope
- YAGNI: no incident overage metering, no native mobile, no HIPAA claims
- TDD: failing test → implement → pass → commit per task
- Path A (`no_movement_ok`) and Path B (`no_movement_silence`) must remain unchanged for home mode
- Mac-shaped API shape required: `/ui`, fixtures `no_movement_ok` / `no_movement_silence`, `/demo/upload` (box may be thinner — implement full surface)

---

## File structure (create / modify)

```
configs/
  demo_home.yaml                          # KEEP — home Path A/B (unchanged rungs)
  demo_facility.yaml                      # CREATE — facility ladder with notify + supervisor

src/care_ladder/
  models.py                               # MODIFY — CarePlan mode/supervisor/notifications; TenantMode
  plan_loader.py                          # MODIFY — validate facility notify/supervisor fields + demo phones on supervisor
  db/
    __init__.py                           # CREATE
    base.py                               # CREATE — SQLAlchemy DeclarativeBase + engine helpers
    models.py                             # CREATE — Tenant, User, IncidentRow, AuditEventRow, Subscription
    session.py                            # CREATE — SessionLocal / get_session
  audit/
    store.py                              # KEEP protocol surface (save/get/list_incidents)
    postgres_store.py                     # CREATE — PostgresAuditStore implementing AuditStore API + tenant_id
  auth/
    __init__.py                           # CREATE
    passwords.py                          # CREATE — hash/verify
    sessions.py                           # CREATE — sign/unsign session cookie
    deps.py                               # CREATE — FastAPI Depends: require_user, require_tenant
  tenancy/
    __init__.py                           # CREATE
    service.py                            # CREATE — create_tenant, get_tenant, seed_demo_tenants
  billing/
    __init__.py                           # CREATE
    stripe_checkout.py                    # CREATE — create Checkout Session, Customer Portal URL
    webhook.py                            # CREATE — verify + apply subscription events
    plans.py                              # CREATE — PlanId enum + feature gates (home / facility_starter)
  channels/
    dial.py                               # KEEP — StubDialer
    speaker.py                            # KEEP
    notify.py                             # CREATE — NotifyChannelAdapter (Slack webhook / stub)
    supervisor.py                         # CREATE — NotifySupervisorAdapter (Slack DM stub / webhook)
  ladder/
    orchestrator.py                       # MODIFY — handle notify_channel + notify_supervisor rungs
  api/
    app.py                                # MODIFY — mount auth, billing, tenant-scoped incidents, facility fixture, landing
    deps.py                               # CREATE — wire store/session from app.state
    static/
      index.html                          # MODIFY — mode badge, notify/supervisor labels, facility demo button
      landing.html                        # CREATE — problem → facility wedge → pricing → demo login
  migrations/                             # CREATE (Alembic) OR scripts/migrate_saas.py for MVP single upgrade
    env.py
    versions/001_saas_tenancy.py

tests/
  test_db_tenancy.py                      # CREATE
  test_auth_session.py                    # CREATE
  test_facility_plan_loader.py            # CREATE
  test_notify_channel.py                  # CREATE
  test_notify_supervisor.py               # CREATE
  test_facility_fixture.py                # CREATE
  test_ui_facility_mode.py                # CREATE
  test_stripe_billing.py                  # CREATE
  test_landing_and_demo_login.py          # CREATE
  # existing tests must keep passing for home Path A/B

docs/
  demo-video-script.md                    # MODIFY — add facility notify beat (shot list only)
  galuxium/
    executive-briefing.md                 # CREATE — Devpost About draft
  README.md (repo root)                   # MODIFY — Galuxium section: architecture, schema, fiscal, deploy

Dockerfile                                # MODIFY — install SaaS deps, CARE_LADDER_STORE=postgres
fly.toml OR render.yaml                   # CREATE — public HTTPS host + Postgres
.env.example                              # CREATE — DATABASE_URL, SESSION_SECRET, STRIPE_*, SLACK_WEBHOOK_URL
pyproject.toml                            # MODIFY — sqlalchemy, alembic, bcrypt, itsdangerous, stripe, httpx
```

---

### Task 1: Postgres models + tenant/mode + PostgresAuditStore

**Files:**
- Create: `src/care_ladder/db/__init__.py`, `src/care_ladder/db/base.py`, `src/care_ladder/db/models.py`, `src/care_ladder/db/session.py`, `src/care_ladder/audit/postgres_store.py`, `tests/test_db_tenancy.py`, `alembic.ini`, `src/care_ladder/migrations/env.py`, `src/care_ladder/migrations/versions/001_saas_tenancy.py`
- Modify: `pyproject.toml` (add `sqlalchemy>=2`, `psycopg[binary]>=3`, `alembic`), `src/care_ladder/models.py` (add `tenant_id` optional on `Incident` for serialization)
- Keep: `src/care_ladder/audit/store.py` in-memory for unit tests

**Interfaces:**
- Consumes: existing `Incident`, `AuditEvent`, `CueEvent` pydantic models
- Produces:
  - `TenantMode = Literal["home", "facility"]`
  - SQLAlchemy `Tenant(id, name, mode, plan, subscription_status, created_at)`
  - `User(id, tenant_id, email, password_hash, role)`
  - `IncidentRow` / `AuditEventRow` keyed by `tenant_id` + `incident_id`
  - `PostgresAuditStore(session_factory, tenant_id: str)` with `.save(incident) -> Incident`, `.get(incident_id) -> Incident | None`, `.list_incidents() -> list[Incident]` (tenant-scoped)
  - `create_engine_from_url(url: str)` / `make_session_factory(engine)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_tenancy.py
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from care_ladder.audit.postgres_store import PostgresAuditStore
from care_ladder.db.base import Base
from care_ladder.db.models import Tenant
from care_ladder.models import AuditEvent, CueEvent, Incident


@pytest.fixture()
def pg_session_factory(tmp_path):
    # SQLite for unit tests; production uses Postgres via DATABASE_URL
    url = f"sqlite:///{tmp_path / 'saas.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as s:
        s.add(Tenant(id="ten-home", name="Demo Home", mode="home", plan="home", subscription_status="active"))
        s.add(Tenant(id="ten-fac", name="Demo Facility", mode="facility", plan="facility_starter", subscription_status="active"))
        s.commit()
    return Session


def test_postgres_store_scopes_incidents_by_tenant(pg_session_factory):
    store_a = PostgresAuditStore(pg_session_factory, tenant_id="ten-home")
    store_b = PostgresAuditStore(pg_session_factory, tenant_id="ten-fac")
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "unit"})
    inc_a = Incident(
        id=uuid.uuid4().hex,
        household_id="demo-home-1",
        cue=cue,
        events=[AuditEvent(tool="cue", cue_kind="no_movement", detail={})],
        status="resolved",
    )
    store_a.save(inc_a)
    assert store_a.get(inc_a.id) is not None
    assert store_b.get(inc_a.id) is None
    assert len(store_a.list_incidents()) == 1
    assert store_b.list_incidents() == []


def test_tenant_mode_values(pg_session_factory):
    with pg_session_factory() as s:
        home = s.get(Tenant, "ten-home")
        fac = s.get(Tenant, "ten-fac")
    assert home.mode == "home"
    assert fac.mode == "facility"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/opencv-care-ladder && python -m pytest tests/test_db_tenancy.py -v`  
Expected: FAIL (`ModuleNotFoundError: care_ladder.db` or `PostgresAuditStore`)

- [ ] **Step 3: Write minimal implementation**

`src/care_ladder/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

`src/care_ladder/db/models.py`: tables `tenants`, `users`, `incidents`, `audit_events`, `subscriptions` with FK `tenant_id`. Store incident cue/events as JSON columns for MVP (no need to normalize every audit field). `Tenant.mode` constrained to `home`|`facility`; `plan` to `home`|`facility_starter`|`facility_growth`|`demo`; `subscription_status` to `none`|`active`|`past_due`|`canceled`.

`src/care_ladder/audit/postgres_store.py`: on `save`, upsert incident row + replace event rows; stamp `tenant_id`; reconstruct pydantic `Incident` on `get`/`list_incidents`. Filter every query with `IncidentRow.tenant_id == self.tenant_id`.

Alembic revision `001_saas_tenancy` creates the same tables for real Postgres (`DATABASE_URL`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db_tenancy.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/care_ladder/db src/care_ladder/audit/postgres_store.py src/care_ladder/migrations alembic.ini tests/test_db_tenancy.py src/care_ladder/models.py
git commit -m "feat(saas): Postgres tenancy models and tenant-scoped audit store"
```

---

### Task 2: Auth (session cookie) + tenant scoping on API

**Files:**
- Create: `src/care_ladder/auth/__init__.py`, `src/care_ladder/auth/passwords.py`, `src/care_ladder/auth/sessions.py`, `src/care_ladder/auth/deps.py`, `src/care_ladder/tenancy/__init__.py`, `src/care_ladder/tenancy/service.py`, `tests/test_auth_session.py`
- Modify: `src/care_ladder/api/app.py` (login/logout/me, inject tenant store), `pyproject.toml` (`bcrypt`, `itsdangerous`)
- Create: `.env.example` with `SESSION_SECRET=`, `DATABASE_URL=`

**Interfaces:**
- Consumes: `User`, `Tenant` ORM models; `PostgresAuditStore` / in-memory `AuditStore`
- Produces:
  - `hash_password(plain: str) -> str` / `verify_password(plain: str, hashed: str) -> bool`
  - `SessionData(user_id: str, tenant_id: str, email: str)`
  - `create_session_token(data: SessionData, secret: str) -> str` / `read_session_token(token: str, secret: str) -> SessionData | None`
  - Cookie name: `care_ladder_session` (HttpOnly, SameSite=Lax)
  - Routes: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
  - `seed_demo_tenants(session)` creates:
    - tenant `demo-home` mode=home, user `demo@careladder.local` / `demo-pass-home`
    - tenant `demo-facility` mode=facility plan=facility_starter, user `facility@careladder.local` / `demo-pass-facility`
  - Incident list/get use `request.state.tenant_id` when auth middleware active; demo fixtures without cookie still work when `CARE_LADDER_AUTH=off` (default for local Path A/B tests) OR judge uses demo login

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_session.py
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.auth.passwords import hash_password, verify_password
from care_ladder.auth.sessions import SessionData, create_session_token, read_session_token


def test_password_roundtrip():
    h = hash_password("demo-pass-home")
    assert verify_password("demo-pass-home", h)
    assert not verify_password("wrong", h)


def test_session_token_roundtrip():
    secret = "test-secret-not-for-prod"
    tok = create_session_token(
        SessionData(user_id="u1", tenant_id="ten-home", email="demo@careladder.local"),
        secret=secret,
    )
    data = read_session_token(tok, secret=secret)
    assert data is not None
    assert data.tenant_id == "ten-home"
    assert data.email == "demo@careladder.local"


def test_login_sets_cookie_and_me_returns_tenant(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    app = create_app(store=AuditStore())
    # create_app must seed or accept injected demo user when AUTH=on + memory mode
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "demo@careladder.local", "password": "demo-pass-home"})
    assert r.status_code == 200
    assert "care_ladder_session" in r.cookies
    me = client.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "demo@careladder.local"
    assert body["tenant"]["mode"] in ("home", "facility")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_session.py -v`  
Expected: FAIL (auth modules / routes missing)

- [ ] **Step 3: Write minimal implementation**

`passwords.py`: bcrypt hash/verify.  
`sessions.py`: `URLSafeTimedSerializer` from itsdangerous; max age 7 days.  
`deps.py`: `get_current_user(request) -> SessionData | None`; `require_user` raises 401.  
`tenancy/service.py`: `seed_demo_tenants` + `authenticate(email, password) -> User|None`.  
`app.py`: when `CARE_LADDER_AUTH=on`, require session for `/incidents*`; keep `/demo/run` and `/ui` reachable for judges after demo login. Default `CARE_LADDER_AUTH` unset/off so existing `tests/test_api_timeline.py` and Path A/B tests keep passing without cookies. When AUTH=on and memory store, seed two in-process demo users on startup.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_session.py tests/test_api_timeline.py tests/test_demo_paths_and_ui.py -v`  
Expected: PASS (auth tests + existing demo API tests)

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/auth src/care_ladder/tenancy src/care_ladder/api/app.py tests/test_auth_session.py .env.example pyproject.toml
git commit -m "feat(saas): session auth and tenant-scoped API access"
```

---

### Task 3: Facility care-plan template + loader validation

**Files:**
- Create: `configs/demo_facility.yaml`, `tests/test_facility_plan_loader.py`
- Modify: `src/care_ladder/models.py`, `src/care_ladder/plan_loader.py`

**Interfaces:**
- Consumes: YAML care plans
- Produces: extended pydantic models:
  - `CarePlan.mode: Literal["home", "facility"] = "home"`
  - `SupervisorContact(display_name: str, phone_e164: str | None = None, slack_user_id: str | None = None, teams_user_id: str | None = None)`
  - `SlackNotifyConfig(enabled: bool = False, webhook_env: str = "SLACK_WEBHOOK_URL")`
  - `TeamsNotifyConfig(enabled: bool = False)`
  - `NotificationsConfig(slack: SlackNotifyConfig = ..., teams: TeamsNotifyConfig = ...)`
  - `CarePlan.supervisor: SupervisorContact | None = None`
  - `CarePlan.notifications: NotificationsConfig | None = None`
  - `load_care_plan(path) -> CarePlan` validates: if any rung `tool in {"notify_channel","notify_supervisor"}` then `mode` must be `facility`, `supervisor` required for `notify_supervisor`, and demo phones on supervisor when `CARE_LADDER_ENV=demo`
  - Home default template must **not** include notify rungs

- [ ] **Step 1: Write the failing test**

```python
# tests/test_facility_plan_loader.py
from pathlib import Path

import pytest

from care_ladder.plan_loader import load_care_plan


def test_loads_demo_facility_with_notify_and_supervisor():
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    assert plan.mode == "facility"
    assert plan.supervisor is not None
    assert plan.supervisor.display_name == "Floor Lead"
    assert plan.supervisor.phone_e164.startswith("+121255501")
    assert plan.notifications is not None
    assert plan.notifications.slack.enabled is True
    tools = [r.tool for r in plan.rungs]
    assert "notify_channel" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    emergency = next(r for r in plan.rungs if r.tool == "emergency")
    assert emergency.params.get("enabled") is False


def test_home_plan_has_no_notify_rungs():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    assert getattr(plan, "mode", "home") in ("home", None) or plan.mode == "home"
    tools = [r.tool for r in plan.rungs]
    assert "notify_channel" not in tools
    assert "notify_supervisor" not in tools


def test_notify_rungs_rejected_on_home_mode(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
household_id: bad
mode: home
caregiver: {display_name: Alex, phone_e164: "+12125550101"}
monitored: {display_name: Pat}
triggers:
  no_movement: {enabled: true, timeout_sec: 900}
rungs:
  - {id: n1, tool: notify_channel, params: {channel: slack, template: incident_open}}
  - {id: emergency, tool: emergency, params: {enabled: false}}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="facility"):
        load_care_plan(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_facility_plan_loader.py -v`  
Expected: FAIL (missing YAML / mode fields)

- [ ] **Step 3: Write minimal implementation**

`configs/demo_facility.yaml` (exact content):

```yaml
household_id: demo-facility-1
mode: facility
caregiver:
  display_name: Alex
  phone_e164: "+12125550101"
monitored:
  display_name: Pat
supervisor:
  display_name: Floor Lead
  slack_user_id: "U0DEMO"
  phone_e164: "+12125550103"
notifications:
  slack:
    enabled: true
    webhook_env: SLACK_WEBHOOK_URL
  teams:
    enabled: false
zones:
  - id: living_room
    polygon: [[0, 0], [640, 0], [640, 480], [0, 480]]
triggers:
  no_movement:
    enabled: true
    timeout_sec: 900
  no_visibility:
    enabled: true
  distress_heuristic:
    enabled: true
rungs:
  - id: reperceive
    tool: reperceive
    params: { roi: auto }
  - id: ask_ok
    tool: speaker_prompt
    params:
      text: "Are you okay? Do you want me to call Alex?"
      channel: nest_or_alexa_then_phone
  - id: wait_reply
    tool: wait
    params: { sec: 120 }
  - id: notify_ops
    tool: notify_channel
    params: { channel: slack, template: incident_open }
  - id: escalate_supervisor
    tool: notify_supervisor
    params: { contact: supervisor }
  - id: dial_primary
    tool: dial_contact
    params: { contact: caregiver }
  - id: emergency
    tool: emergency
    params: { enabled: false }
quiet_hours:
  start: "22:00"
  end: "07:00"
  policy: soft_suppress_non_distress
```

Extend `validate_demo_phones` to include `plan.supervisor` when present. Add `validate_facility_tools(plan)` called from `load_care_plan`. Set `demo_home.yaml` `mode: home` explicitly (additive; existing tests still pass).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_facility_plan_loader.py tests/test_plan_loader.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add configs/demo_facility.yaml configs/demo_home.yaml src/care_ladder/models.py src/care_ladder/plan_loader.py tests/test_facility_plan_loader.py
git commit -m "feat(saas): facility care-plan template and loader validation"
```

---

### Task 4: `notify_channel` tool (Slack webhook / stub) + orchestrator wiring

**Files:**
- Create: `src/care_ladder/channels/notify.py`, `tests/test_notify_channel.py`
- Modify: `src/care_ladder/ladder/orchestrator.py`

**Interfaces:**
- Consumes: `CarePlan.notifications`, rung params `{channel: "slack"|"teams", template: str}`, env webhook URL
- Produces:
  - `@dataclass NotifyResult: status: Literal["sent","stubbed","skipped"]; adapter: Literal["slack","teams","stub"]; channel: str; detail: dict`
  - `class NotifyChannelAdapter: async def notify(self, *, channel: str, template: str, incident_id: str, plan: CarePlan) -> NotifyResult`
  - Behavior: if `channel=="slack"` and `os.environ.get(plan.notifications.slack.webhook_env)` non-empty → POST JSON payload via httpx; `adapter="slack"`, `status="sent"`. Else → `adapter="stub"`, `status="stubbed"`. Teams MVP: always stub with `adapter="stub"` (spec allows Teams stub-only).
  - Orchestrator: on `tool == "notify_channel"`, call adapter, `_append(..., tool="notify_channel", detail={..., "adapter": result.adapter})`, continue to next rung (does not resolve).
  - `run_incident(..., notifier: NotifyChannelAdapter | None = None)` — default constructs `NotifyChannelAdapter()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notify_channel.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.notify import NotifyChannelAdapter, NotifyResult
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan

DAYTIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def test_notify_stubs_when_webhook_missing(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    adapter = NotifyChannelAdapter()
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    result = asyncio.run(
        adapter.notify(channel="slack", template="incident_open", incident_id="abc", plan=plan)
    )
    assert result.status == "stubbed"
    assert result.adapter == "stub"


def test_notify_posts_slack_when_webhook_set(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T0/B0/DEMO")
    adapter = NotifyChannelAdapter()
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    mock_resp = httpx.Response(200, request=httpx.Request("POST", "https://hooks.slack.com/services/T0/B0/DEMO"))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as post:
        result = asyncio.run(
            adapter.notify(channel="slack", template="incident_open", incident_id="abc", plan=plan)
        )
    assert result.status == "sent"
    assert result.adapter == "slack"
    assert post.await_count == 1


def test_orchestrator_emits_notify_channel_audit_event():
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_notify"})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
            notifier=NotifyChannelAdapter(),
        )
    )
    tools = [e.tool for e in incident.events]
    assert "notify_channel" in tools
    ev = next(e for e in incident.events if e.tool == "notify_channel")
    assert ev.detail.get("adapter") in ("stub", "slack")
    assert ev.detail.get("channel") == "slack"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notify_channel.py -v`  
Expected: FAIL (`notify` module missing / unknown_tool_skipped)

- [ ] **Step 3: Write minimal implementation**

Implement `NotifyChannelAdapter` in `channels/notify.py`. In `orchestrator.py`, before the unknown-tool branch, handle `notify_channel`:

```python
if tool == "notify_channel":
    channel = str(rung.params.get("channel", "slack"))
    template = str(rung.params.get("template", "incident_open"))
    adapter = notifier or NotifyChannelAdapter()
    result = await adapter.notify(
        channel=channel, template=template, incident_id=incident.id, plan=plan
    )
    _append(
        events,
        tool="notify_channel",
        cue_kind=cue.kind,
        rung_id=rung.id,
        detail={
            "channel": channel,
            "template": template,
            "status": result.status,
            "adapter": result.adapter,
            **result.detail,
        },
    )
    idx += 1
    continue
```

Add `notifier` optional kwarg to `run_incident` signature. Payload text must not claim medical diagnosis — e.g. `"Care Ladder incident {id} opened (cue={kind}). Not a medical alert."`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notify_channel.py tests/test_orchestrator.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/channels/notify.py src/care_ladder/ladder/orchestrator.py tests/test_notify_channel.py pyproject.toml
git commit -m "feat(saas): notify_channel Slack webhook with stub adapter"
```

---

### Task 5: `notify_supervisor` tool + tests

**Files:**
- Create: `src/care_ladder/channels/supervisor.py`, `tests/test_notify_supervisor.py`
- Modify: `src/care_ladder/ladder/orchestrator.py` (handle `notify_supervisor`), `src/care_ladder/channels/dial.py` (`next_rung_after_no_answer` may skip notify rungs already passed — no change required if notify sits before dial)

**Interfaces:**
- Consumes: `plan.supervisor`, rung params `{contact: "supervisor"}`
- Produces:
  - `@dataclass SupervisorNotifyResult: status: Literal["sent","stubbed"]; adapter: Literal["slack","stub"]; supervisor_id: str; detail: dict`
  - `class NotifySupervisorAdapter: async def notify(self, *, plan: CarePlan, incident_id: str) -> SupervisorNotifyResult`
  - Prefer Slack webhook mention/`slack_user_id` in payload when webhook env set; else stub. Always audit.
  - Orchestrator appends `tool="notify_supervisor"` with `adapter` and `supervisor.display_name`; continues (does not resolve).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notify_supervisor.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.notify import NotifyChannelAdapter
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.channels.supervisor import NotifySupervisorAdapter
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan

DAYTIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def test_supervisor_stub_without_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    result = asyncio.run(
        NotifySupervisorAdapter().notify(plan=plan, incident_id="inc1")
    )
    assert result.status == "stubbed"
    assert result.adapter == "stub"
    assert "Floor Lead" in result.supervisor_id or result.detail.get("display_name") == "Floor Lead"


def test_facility_silence_path_notifies_then_supervisor_then_dial():
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_full"})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
            notifier=NotifyChannelAdapter(),
            supervisor_notifier=NotifySupervisorAdapter(),
        )
    )
    tools = [e.tool for e in incident.events]
    assert tools.index("notify_channel") < tools.index("notify_supervisor")
    assert tools.index("notify_supervisor") < tools.index("dial_contact")
    sup = next(e for e in incident.events if e.tool == "notify_supervisor")
    assert sup.detail.get("adapter") in ("stub", "slack")
    assert incident.status == "resolved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notify_supervisor.py -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`channels/supervisor.py` as above. Orchestrator branch:

```python
if tool == "notify_supervisor":
    adapter = supervisor_notifier or NotifySupervisorAdapter()
    result = await adapter.notify(plan=plan, incident_id=incident.id)
    _append(
        events,
        tool="notify_supervisor",
        cue_kind=cue.kind,
        rung_id=rung.id,
        detail={
            "contact": "supervisor",
            "status": result.status,
            "adapter": result.adapter,
            "display_name": plan.supervisor.display_name if plan.supervisor else None,
            "slack_user_id": plan.supervisor.slack_user_id if plan.supervisor else None,
            **result.detail,
        },
    )
    idx += 1
    continue
```

Add `supervisor_notifier` optional kwarg to `run_incident`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notify_supervisor.py tests/test_notify_channel.py tests/test_orchestrator.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/channels/supervisor.py src/care_ladder/ladder/orchestrator.py tests/test_notify_supervisor.py
git commit -m "feat(saas): notify_supervisor escalate with stub/Slack audit"
```

---

### Task 6: Home vs facility default plans + demo fixtures (Path A/B unchanged)

**Files:**
- Modify: `src/care_ladder/api/app.py` (facility fixture + plan selection), `tests/test_demo_paths_and_ui.py` or create `tests/test_facility_fixture.py`
- Keep: `_run_no_movement_ok` / `_run_no_movement_silence` on `configs/demo_home.yaml` exactly as today

**Interfaces:**
- Consumes: `demo_home.yaml`, `demo_facility.yaml`, notify adapters
- Produces:
  - New fixture id: `facility_notify_silence` in `SUPPORTED_FIXTURES`
  - `_run_facility_notify_silence(store)`: load facility plan, silence speaker, StubDialer caregiver answered, run_incident with notifier + supervisor_notifier, midday `DEMO_NOW`
  - `GET /tenant/me` or include mode on `GET /auth/me` (already) and `GET /demo/context` → `{mode, plan_household_id, fixtures: [...]}` for UI
  - Home fixtures unchanged: `no_movement_ok`, `no_movement_silence` still resolve Path A / escalate Path B without notify events

- [ ] **Step 1: Write the failing test**

```python
# tests/test_facility_fixture.py
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_path_a_unchanged_no_notify_tools():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_channel" not in tools
    assert "notify_supervisor" not in tools
    assert inc["status"] == "resolved"


def test_facility_notify_silence_fixture():
    client = TestClient(create_app(store=AuditStore()))
    r = client.post("/demo/run", json={"fixture": "facility_notify_silence"})
    assert r.status_code == 200
    inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "notify_channel" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    notify = next(e for e in inc["events"] if e["tool"] == "notify_channel")
    assert notify["detail"]["adapter"] in ("stub", "slack")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_facility_fixture.py -v`  
Expected: FAIL (`unknown fixture facility_notify_silence`)

- [ ] **Step 3: Write minimal implementation**

In `app.py`:

```python
_FACILITY_PLAN_PATH = _REPO_ROOT / "configs" / "demo_facility.yaml"
SUPPORTED_FIXTURES = frozenset({..., "facility_notify_silence"})

async def _run_facility_notify_silence(store: AuditStore):
    from care_ladder.channels.notify import NotifyChannelAdapter
    from care_ladder.channels.supervisor import NotifySupervisorAdapter
    plan = load_care_plan(_FACILITY_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_notify_silence"})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=SpeakerSimulator(scripted=[]),
        dialer=StubDialer(behavior={"caregiver": "answered"}),
        pre_event_frames=[],
        store=store,
        now=DEMO_NOW,
        notifier=NotifyChannelAdapter(),
        supervisor_notifier=NotifySupervisorAdapter(),
    )
    return incident
```

Wire into `demo_run`. Add `GET /demo/context` returning available fixtures and default mode.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_facility_fixture.py tests/test_demo_paths_and_ui.py tests/test_e2e_demo.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/api/app.py tests/test_facility_fixture.py
git commit -m "feat(saas): facility_notify_silence demo fixture; Path A/B unchanged"
```

---

### Task 7: UI — mode badge + notify/supervisor timeline + facility demo button

**Files:**
- Modify: `src/care_ladder/api/static/index.html`
- Create: `tests/test_ui_facility_mode.py`

**Interfaces:**
- Consumes: `/demo/context`, incident JSON events
- Produces: UI showing:
  - Mode badge in header (Home / Facility) from `/demo/context` or `/auth/me`
  - Button **Facility · notify → supervisor** with `data-fixture="facility_notify_silence"`
  - Timeline labels for `notify_channel` and `notify_supervisor` (include `adapter=stub|slack` in detail text)
  - Footer unchanged: no clinical / no real 911 claims

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ui_facility_mode.py
from pathlib import Path

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_ui_contains_facility_controls_and_tool_labels():
    html = Path("src/care_ladder/api/static/index.html").read_text(encoding="utf-8")
    assert "facility_notify_silence" in html
    assert "notify_channel" in html or "notify ops" in html.lower() or "Notify" in html
    assert "mode-badge" in html or "data-mode" in html


def test_facility_fixture_visible_in_ui_served():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "facility_notify_silence" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ui_facility_mode.py -v`  
Expected: FAIL (button / badge missing)

- [ ] **Step 3: Write minimal implementation**

In `index.html` header actions, add:

```html
<button class="btn" data-fixture="facility_notify_silence">Facility · notify → supervisor</button>
<span id="mode-badge" class="badge b-cue" data-mode="home">Home</span>
```

Extend `TOOL_LABEL`:

```javascript
notify_channel:"notify channel", notify_supervisor:"notify supervisor",
```

In `detailText`, if `d.adapter` present push `"adapter: "+d.adapter`. On load, `fetch("/demo/context")` and set `#mode-badge` text/class to Home or Facility.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ui_facility_mode.py tests/test_demo_paths_and_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/api/static/index.html tests/test_ui_facility_mode.py
git commit -m "feat(saas): facility mode badge and notify timeline UI"
```

---

### Task 8: Stripe Checkout + webhook + plan gating

**Files:**
- Create: `src/care_ladder/billing/__init__.py`, `src/care_ladder/billing/plans.py`, `src/care_ladder/billing/stripe_checkout.py`, `src/care_ladder/billing/webhook.py`, `tests/test_stripe_billing.py`
- Modify: `src/care_ladder/api/app.py` (routes), `pyproject.toml` (`stripe`), `.env.example`

**Interfaces:**
- Consumes: Stripe test-mode secret key, price IDs, webhook secret; `Tenant` row
- Produces:
  - `PlanId = Literal["home", "facility_starter", "facility_growth", "demo"]`
  - `PLAN_FEATURES = {"home": {"notify": False, "seats": 2}, "facility_starter": {"notify": True, "seats": 10, "retention_days": 7}, "facility_growth": {"notify": True, "seats": 25, "retention_days": 30}, "demo": {"notify": True, "seats": 10}}`
  - `tenant_can_use_notify(tenant) -> bool` True when plan in facility_* or demo OR mode==facility with active/demo status
  - `POST /billing/checkout` body `{plan: "home"|"facility_starter"}` → `{checkout_url: str}` (Stripe Checkout subscription mode)
  - `POST /billing/webhook` raw body + `Stripe-Signature` → update `tenant.plan` + `subscription_status`
  - `POST /billing/portal` → Customer Portal URL
  - Gating: `facility_notify_silence` returns 402/403 with `{detail: "upgrade_required"}` when tenant plan is `home` and not demo; demo tenants always allowed
  - YAGNI: no per-incident overage metering

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stripe_billing.py
from care_ladder.billing.plans import PLAN_FEATURES, tenant_can_use_notify
from care_ladder.billing.webhook import apply_checkout_completed


class FakeTenant:
    def __init__(self, plan="home", subscription_status="none", mode="home"):
        self.plan = plan
        self.subscription_status = subscription_status
        self.mode = mode
        self.id = "ten-1"


def test_home_plan_cannot_notify():
    assert PLAN_FEATURES["home"]["notify"] is False
    assert tenant_can_use_notify(FakeTenant(plan="home", mode="home")) is False


def test_facility_starter_can_notify():
    assert tenant_can_use_notify(FakeTenant(plan="facility_starter", subscription_status="active", mode="facility")) is True


def test_apply_checkout_completed_sets_plan():
    t = FakeTenant()
    apply_checkout_completed(
        t,
        metadata={"tenant_id": "ten-1", "plan": "facility_starter"},
        status="active",
    )
    assert t.plan == "facility_starter"
    assert t.subscription_status == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stripe_billing.py -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`plans.py` as interfaces.  
`stripe_checkout.py`: if `STRIPE_SECRET_KEY` unset, return a stub checkout URL `/billing/stub-success?plan=...` for local demos (document honesty). When set, `stripe.checkout.Session.create(mode="subscription", line_items=[{price: PRICE_ID, quantity: 1}], success_url, cancel_url, metadata={tenant_id, plan})`.  
`webhook.py`: verify signature when secret set; handle `checkout.session.completed` and `customer.subscription.updated/deleted`.  
`app.py`: mount routes; gate facility fixture with `tenant_can_use_notify` when AUTH=on; demo seed tenants use `plan=demo` so judges never need a card.

Indicative prices (document only): Home $29/mo, Facility Starter $199/mo, Facility Growth $499/mo (Growth checkout optional for MVP — gate enum includes it but Checkout only offers Home + Facility Starter per spec MVP).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_stripe_billing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/billing src/care_ladder/api/app.py tests/test_stripe_billing.py pyproject.toml .env.example
git commit -m "feat(saas): Stripe Checkout, webhook, and facility plan gating"
```

---

### Task 9: Landing page + pricing + demo login

**Files:**
- Create: `src/care_ladder/api/static/landing.html`, `tests/test_landing_and_demo_login.py`
- Modify: `src/care_ladder/api/app.py` (serve `/` as landing, keep `/ui/` console)

**Interfaces:**
- Consumes: billing plan table, auth login
- Produces:
  - `GET /` → landing HTML: problem → facility lean-ops wedge → pricing table (Home $29 / Facility Starter $199 / Facility Growth $499) → **Demo login** buttons that POST `/auth/login` for home + facility demo users then redirect to `/ui/`
  - Copy rules: no clinical diagnosis claims; emergency fail-closed mentioned; ReadyPup not mentioned
  - CTA: "Open caregiver console" → `/ui/`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_landing_and_demo_login.py
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_landing_has_pricing_and_facility_wedge():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/")
    assert r.status_code == 200
    text = r.text.lower()
    assert "facility" in text
    assert "$29" in r.text or "29/mo" in text
    assert "$199" in r.text or "199/mo" in text
    assert "not a medical" in text or "not medical" in text
    assert "diagnoses patients" not in text and "clinical accuracy" not in text
    assert "demo" in text


def test_landing_links_to_ui():
    client = TestClient(create_app(store=AuditStore()))
    r = client.get("/")
    assert "/ui" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_landing_and_demo_login.py -v`  
Expected: FAIL (landing missing or `/` still not landing)

- [ ] **Step 3: Write minimal implementation**

Create `landing.html` with sections: Hero one-liner from spec ("Vision spots the moment; the ladder picks the next human-safe step with an operator in the loop."), Dual ICP table (Home vs Facility), Pricing, Demo login form (email/password prefilled tips for `facility@careladder.local`), footer disclaimers.  
Mount in `create_app`:

```python
@application.get("/", include_in_schema=False)
def landing():
    return FileResponse(static_dir / "landing.html")
```

Keep `StaticFiles` at `/ui`. Ensure no "HIPAA" or "911 dispatch" product claims.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_landing_and_demo_login.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/care_ladder/api/static/landing.html src/care_ladder/api/app.py tests/test_landing_and_demo_login.py
git commit -m "feat(saas): landing page with pricing and demo login"
```

---

### Task 10: Dockerfile / Fly-or-Render deploy + README Galuxium section

**Files:**
- Modify: `Dockerfile`, `README.md`, `pyproject.toml` (ensure httpx not httpx2 typo fixed if still present)
- Create: `fly.toml` **or** `render.yaml` (pick one primary: **Render** web + Postgres for simplest HTTPS), `.env.example` completed, `scripts/seed_saas_demo.py`

**Interfaces:**
- Consumes: `DATABASE_URL`, `SESSION_SECRET`, optional `STRIPE_*`, `SLACK_WEBHOOK_URL`, `CARE_LADDER_ENV=demo`, `CARE_LADDER_AUTH=on` in prod
- Produces: container that runs migrations then uvicorn; public HTTPS URL documented in README; README **Galuxium Nexus V2** section covering architecture diagram (text), schema summary, fiscal architecture, local run, demo accounts, dual-hackathon note (ReadyPup ≠ Care Ladder)

- [ ] **Step 1: Write the failing test (smoke / docs presence)**

```python
# tests/test_deploy_docs.py
from pathlib import Path

def test_readme_has_galuxium_section():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Galuxium" in readme
    assert "Facility Starter" in readme or "facility_starter" in readme
    assert "Stripe" in readme
    assert "ReadyPup" in readme  # explicit do-not-mix note


def test_deploy_config_exists():
    assert Path("render.yaml").exists() or Path("fly.toml").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_deploy_docs.py -v`  
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`render.yaml` example:

```yaml
services:
  - type: web
    name: care-ladder
    runtime: docker
    plan: starter
    healthCheckPath: /demo/context
    envVars:
      - key: CARE_LADDER_ENV
        value: demo
      - key: CARE_LADDER_AUTH
        value: on
      - key: DATABASE_URL
        fromDatabase:
          name: care-ladder-db
          property: connectionString
      - key: SESSION_SECRET
        generateValue: true
databases:
  - name: care-ladder-db
    plan: basic-256mb
```

Dockerfile: `pip install -e .`, copy `configs/demo_facility.yaml`, CMD runs `alembic upgrade head && python scripts/seed_saas_demo.py && uvicorn care_ladder.api.app:app --host 0.0.0.0 --port 8000`.

README Galuxium section must include fiscal table (Home $29 / Facility Starter $199 / Facility Growth $499), StubDialer honesty, Slack stub-vs-real, and "RevenueCat Shipaton uses ReadyPup — not this repo filing."

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_deploy_docs.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Dockerfile render.yaml fly.toml README.md scripts/seed_saas_demo.py tests/test_deploy_docs.py .env.example pyproject.toml
git commit -m "chore(saas): Render/Fly deploy config and Galuxium README"
```

---

### Task 11: Demo video shot list — facility notify beat (docs only)

**Files:**
- Modify: `docs/demo-video-script.md`

**Interfaces:**
- Consumes: existing shot list (Path A/B, DNN, fall)
- Produces: added shot row for facility notify → supervisor → dial; mute-test note that notify/supervisor rows are readable without VO; no video file creation in this task

- [ ] **Step 1: Write the failing test**

```python
# tests/test_demo_video_facility_beat.py
from pathlib import Path

def test_demo_video_script_includes_facility_notify_beat():
    text = Path("docs/demo-video-script.md").read_text(encoding="utf-8")
    assert "facility" in text.lower()
    assert "notify" in text.lower()
    assert "supervisor" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_demo_video_facility_beat.py -v`  
Expected: FAIL (facility notify beat not yet in script)

- [ ] **Step 3: Write minimal implementation**

Insert a new shot after Path B (adjust times so total stays 2–5 min for Galuxium cut; note OpenCV cut may remain longer):

| # | Time | On screen | VO |
| --- | --- | --- | --- |
| 5b | (Galuxium cut) | `/ui/` mode badge **Facility** → click **Facility · notify → supervisor** → timeline shows `notify_channel` (`adapter: stub` or slack) then `notify_supervisor` (Floor Lead) then dial | "For assisted living, the ladder is leaner ops: after check-in silence, ops get a Slack ping, the floor lead is escalated, then the primary caregiver is dialed — still confirm-before-escalate, still no live 911, still not a medical diagnosis." |

Add mute-test checklist bullet: cue → notify → supervisor → dial → resolve readable without VO.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_demo_video_facility_beat.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/demo-video-script.md tests/test_demo_video_facility_beat.py
git commit -m "docs(galuxium): facility notify beat in demo video shot list"
```

---

### Task 12: Devpost executive briefing draft

**Files:**
- Create: `docs/galuxium/executive-briefing.md`

**Interfaces:**
- Consumes: design spec §§1–7
- Produces: Devpost-ready markdown covering market friction, architecture, cohort/ICP, fiscal architecture, success criteria, dual-hackathon separation (ReadyPup / OpenCV / Galuxium), explicit non-goals (no HIPAA claims, no live 911, no clinical diagnosis)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_galuxium_briefing.py
from pathlib import Path

def test_executive_briefing_exists_and_covers_required_sections():
    p = Path("docs/galuxium/executive-briefing.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8").lower()
    for needle in ["market", "architecture", "facility", "stripe", "fiscal", "readypup", "911", "medical"]:
        assert needle in text
    assert "hipaa certified" not in text
    assert "diagnos" not in text or "not a" in text or "no medical" in text or "non-clinical" in text or "does not diagnose" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_galuxium_briefing.py -v`  
Expected: FAIL (file missing)

- [ ] **Step 3: Write minimal implementation**

Write `docs/galuxium/executive-briefing.md` with these exact section headings and concrete copy (no placeholders):

```markdown
# Care Ladder — Galuxium Nexus V2 Executive Briefing

## Market friction
Families and facilities need remote eyes without a human glued to camera walls. Raw motion alerts are noisy; Care Ladder turns vision cues into a configurable escalation ladder that confirms before escalating.

## Dual ICP
- Home-care: family / private caregiver — check-in → call primary (optional secondary).
- Facility (primary Galuxium story): assisted living ops — check-in → Slack/Teams notify → supervisor → dial primary caregiver. Leaner floors/nights: staff are not screen-glued.

## Architecture (hosted SaaS)
Browser caregiver console → HTTPS → FastAPI (auth, billing webhooks, orchestrator) → Postgres audit store → notify adapters (Slack webhook or stub) → StubDialer (secret-gated real telephony later) → Stripe Checkout. Vision path: fixtures + upload (OpenCV); no mandatory live RTSP for Galuxium MVP.

## Fiscal architecture
| Plan | Price | Includes |
| --- | --- | --- |
| Home | $29/mo per household | 1 household, 2 seats, home ladder |
| Facility Starter | $199/mo per site | 1 site, 10 seats, Slack/Teams notify, supervisor escalate, 7d clip retention |
| Facility Growth | $499/mo per site | 25 seats, 30d retention |
Engine: Stripe Checkout + Customer Portal; webhook updates tenant.plan / subscription_status. Free judge demo tenant (no card). No incident overage metering in MVP.

## Cohort and go-to-market wedge
Lead with facility lean-ops for Galuxium judges; keep home Path A/B as the simpler plan and demo spine.

## Non-goals (hard)
No medical diagnosis claims. No live 911/EMS product feature. No face recognition. No HIPAA certification claims. No ReadyPup / RevenueCat packaging here. Hunt/Tarka out of scope.

## Success criteria
Judge opens live URL, runs Path A and Path B. Facility demo shows Slack-or-stub notify + supervisor on the timeline. Stripe test-mode checkout unlocks Facility Starter. Video mute-test readable. Tarka-circle pre-submit review before filing.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_galuxium_briefing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/galuxium/executive-briefing.md tests/test_galuxium_briefing.py
git commit -m "docs(galuxium): Devpost executive briefing draft"
```

---

## Self-review (author checklist)

**Spec coverage**
| Spec requirement | Task |
| --- | --- |
| Multi-tenant Postgres + auth + tenant.mode | 1, 2 |
| Home + facility default care plans | 3, 6 |
| notify_channel + notify_supervisor (Slack/stub) | 4, 5 |
| Facility UI: mode badge, notify/supervisor events | 7 |
| Stripe Checkout Home + Facility Starter | 8 |
| Public HTTPS deploy + README | 10 |
| Landing + pricing + demo login | 9 |
| Demo video 2–5 min facility notify beat (shot list) | 11 |
| Executive briefing / fiscal for Devpost | 12 |
| Path A/B unchanged | 6 |
| emergency fail-closed / reserved phones / privacy / StubDialer | Global + 3, 4, 5 |
| ReadyPup / Hunt / Tarka / overage / mobile / HIPAA out of scope | Global + 10, 12 |
| Object storage for privacy frames | Existing `CloudSinks`; deploy README documents optional S3 — not reimplemented (reuse) |

**Placeholder scan:** none intentionally left (no TBD/TODO/"similar to Task N").

**Type consistency:** `NotifyChannelAdapter.notify` / `NotifySupervisorAdapter.notify` / `run_incident(..., notifier=, supervisor_notifier=)` / `tenant_can_use_notify` / fixture id `facility_notify_silence` used consistently across tasks 4–8.

**Note on object storage:** Spec §2.1 mentions S3-compatible storage; the repo already has `care_ladder.cloud.sinks.CloudSinks`. Galuxium MVP reuses it — no new object-store module in this plan (YAGNI). Document env vars in README Task 10.

