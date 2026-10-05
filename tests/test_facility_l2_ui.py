"""Layer 2 console UI: cover controls, handoff, retention, honesty labels."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    import sys

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "l2-ui-test")
    appmod = sys.modules["care_ladder.api.app"]
    appmod._FACILITY_STATES.clear()
    appmod._SETTINGS_OVERRIDES.clear()
    app = create_app(store=AuditStore())
    return TestClient(app)


def test_console_serves_cover_controls(client):
    html = client.get("/ui/facility/").text
    assert "data-cover=" in html
    assert "On duty" in html
    assert "On call" in html
    assert "Backup" in html
    assert "/facility/staff/" in html and "/cover" in html


def test_console_serves_handoff_controls(client):
    html = client.get("/ui/facility/").text
    assert "Add handoff note" in html
    assert "/facility/cases/" in html and "/handoff" in html
    assert "Handoff notes" in html


def test_console_serves_retention_and_policy_copy(client):
    html = client.get("/ui/facility/").text
    assert "Audit retention" in html
    assert "audit_retention_years" in html
    assert "owner may extend" in html
    # per-place policy language (no site-wide override)
    assert "per place" in html
    assert "straight page" in html or "straight pages" in html


def test_console_staff_page_and_handoff_rung_labels(client):
    html = client.get("/ui/facility/").text
    assert "staff_page:" in html  # RUNG_LABELS key
    assert "handoff_note:" in html
    assert "Staff page" in html
    assert "Handoff note" in html


def test_console_no_em_dash(client):
    html = client.get("/ui/facility/").text
    assert "\u2014" not in html


def test_overview_kpi_cover_fields(client):
    html = client.get("/ui/facility/").text
    assert "On duty" in html
    assert "On call + backup" in html
    assert "cover.on_duty" in html or "s.cover" in html


def test_cover_editor_hint_visible(client):
    html = client.get("/ui/facility/").text
    assert "only the owner or the floor lead" in html.lower()
