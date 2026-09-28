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
