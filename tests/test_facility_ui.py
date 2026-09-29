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
