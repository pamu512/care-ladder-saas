"""Mockup H Slice 4: facility console page (Alert/Cases/Audit tabs) at /ui/facility."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "facility-ui-test")
    app = create_app(store=AuditStore())
    return TestClient(app)


def test_facility_page_serves_tabs(client):
    r = client.get("/ui/facility")
    assert r.status_code == 200
    html = r.text
    assert "Alert center" in html and "Cases" in html and "Audit" in html
    assert "no em dash check" not in html  # placeholder; real check below
    assert "\u2014" not in html  # no em dashes in copy


def test_facility_page_has_break_and_assign_controls(client):
    r = client.get("/ui/facility")
    assert "pull_off_break" in r.text
    assert "/facility/staff" in r.text
    assert "/facility/alerts" in r.text
    assert "/facility/cases" in r.text
    assert "/facility/audit/summary" in r.text


def test_home_console_unchanged(client):
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "Path A" in r.text  # home fixture buttons still present
    assert 'data-fixture="no_movement_ok"' in r.text


def test_facility_link_appears_for_facility_mode(client):
    """Home page links to the facility console (navigation, not replacement)."""
    r = client.get("/ui/")
    assert "/ui/facility" in r.text


def test_facility_alerts_have_aria_hooks(client):
    r = client.get("/ui/facility/")
    html = r.text
    assert 'role="button"' in html or "setAttribute(\"role\"" in html
    assert "aria-selected" in html
    assert "detailDirty" in html or "detailDraft" in html
    assert "keydown" in html


def test_facility_alerts_aging_chips(client):
    html = client.get("/ui/facility/").text
    assert "aging" in html
    assert "to ack target" in html


# ---- Task 3 ----


def test_facility_ui_has_toast_and_owner_fields(client):
    html = client.get("/ui/facility/").text
    assert 'id="toast"' in html
    assert "owner_display_name" in html
    assert "data-doc-count" in html or "doc-count" in html


# ---- Task 4 ----


def test_facility_audit_register_hooks(client):
    html = client.get("/ui/facility/").text
    assert "audit/register" in html
    assert "Closed-case register" in html or "closed-case register" in html.lower() or 'id="audit-register"' in html
    assert "Resolved by response" in html or "resolved by response" in html
    assert "lead-actions" in html or "Lead actions" in html
    assert "\u2014" not in html


# ---- Task 5 ----


def test_facility_break_duration_hooks(client):
    html = client.get("/ui/facility/").text
    assert 'data-minutes="15"' in html
    assert "break_until" in html
    assert "m left" in html


# ---- Task 6 ----


def test_facility_demo_strip_and_loading(client):
    html = client.get("/ui/facility/").text
    assert "demo-strip" in html
    assert "loading" in html
    assert "/ui/facility/" in client.get("/ui/").text or "/ui/facility/" in html


# ---- SaaS shell (console-full-saas mockup + UI/UX guide v1.0) ----

# Guide §2 token declarations (comment in the guide uses an em dash; §13
# forbids \u2014 in shipped UI, so we assert the values, not that comment).
_GUIDE_TOKENS = (
    "--bg:#0b0f14; --side:#0d1319; --card:#121820; --card2:#0e141b; --raise:#161f2a;",
    "--border:#1f2a36; --border2:#2b3a49;",
    "--text:#e8eef4; --muted:#8b9bab; --faint:#5f7189;",
    "--accent:#18a4c2; --accent-deep:#0e7490; --accent-ink:#04141a;",
    "--accent-soft:rgba(24,164,194,.12);",
    "--ok:#34c98e; --warn:#f5b544; --bad:#f4574d;",
    "--p1:#f4574d; --p2:#f5a044; --p3:#5b8def;",
    "--vio:#b9a6ff; --vio-soft:rgba(185,166,255,.11);",
    "--radius:12px;",
)


def test_facility_shell_uses_guide_tokens_and_232px_sidebar(client):
    html = client.get("/ui/facility/").text
    for token_line in _GUIDE_TOKENS:
        assert token_line in html, token_line
    assert "grid-template-columns:232px" in html
    assert "max-width:980px" in html
    assert "data-view" in html
    assert 'id="view-alerts"' in html
    assert 'id="view-cases"' in html
    assert 'id="view-audit"' in html
    assert 'id="view-staff"' in html
    assert "Staff · shifts" in html
    assert "Resident answers first" in html


def test_facility_shell_omits_unwired_product_nav(client):
    html = client.get("/ui/facility/").text
    assert 'data-view="people"' not in html
    assert 'data-view="places"' not in html
    assert 'data-view="channels"' not in html
    assert "coming soon" not in html.lower()
    assert "Coming soon" not in html
    # guide §12: hide stub toasts and n/a timing rails
    assert 'showToast("PDF export coming soon")' not in html
    assert 'showToast("Range not available yet")' not in html
    assert "n/a" not in html


def test_facility_billing_compare_matches_live_stripe_prices(client):
    html = client.get("/ui/facility/").text
    assert "$9 · 1 household, 1 camera" in html
    assert "$49 · 10 rooms, Slack queue, audit export" in html
    assert "$99 · unlimited rooms, multi-tenant admin" in html
    assert "$29" not in html
    assert "$199" not in html
    assert "$499" not in html


def test_facility_existing_api_hooks_survive_shell(client):
    html = client.get("/ui/facility/").text
    assert 'data-fixture="facility_negative_reply"' in html
    assert "pull_off_break" in html
    assert "/facility/staff" in html
    assert "/facility/alerts" in html
    assert "/facility/audit/summary" in html
    assert "Alert center" in html
    assert "Cases" in html
    assert "Audit" in html
    assert "\u2014" not in html
