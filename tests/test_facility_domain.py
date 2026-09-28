"""Mockup H Slice 1: facility domain - reply classification, priority, staff, cases.

Design: docs/superpowers/specs -> Downloads/2026-09-28 facility-floor-console
Section 4: ReplyClass positive|negative|silence|unclear; Priority P1|P2|P3;
StaffMember with break routing; Case with human id, state, docs requirement.
"""

from care_ladder.facility.models import Case, Priority, ReplyClass, StaffMember
from care_ladder.facility.classify import classify_reply, reply_class_from_kind


def test_reply_class_from_speaker_kind():
    """Existing speaker kinds map onto the facility taxonomy."""
    assert reply_class_from_kind("ok") == "positive"
    assert reply_class_from_kind("call_caregiver") == "negative"
    assert reply_class_from_kind("silence") == "silence"


def test_classify_fixture_override_wins():
    """Fixtures pin the class; the classifier must never override them."""
    got = classify_reply("I feel awful, I cannot get up", fixture_class="negative")
    assert got.reply_class == "negative"
    assert got.source == "fixture"


def test_classify_offline_no_network(monkeypatch):
    """No LLM credentials: keyword fallback, never a network call."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)

    def boom(*a, **k):  # any network attempt fails the test
        raise AssertionError("network call in offline classify")

    import care_ladder.facility.classify as C

    monkeypatch.setattr(C, "_llm_classify", boom)
    got = classify_reply("I'm fine")
    assert got.reply_class == "positive"
    assert got.source == "keyword"
    got = classify_reply("no, I need help")
    assert got.reply_class == "negative"
    got = classify_reply("")
    assert got.reply_class == "silence"
    got = classify_reply("maybe the weather")
    assert got.reply_class == "unclear"


def test_negative_raises_priority_default_map():
    assert Priority.default_for("no_movement", "silence") == "P2"
    assert Priority.default_for("no_movement", "negative") == "P1"
    assert Priority.default_for("distress_heuristic", "silence") == "P1"


def test_case_human_id_and_documentation_rule():
    c = Case.open_from_incident(
        incident_id="abc", tenant_id="demo-facility",
        room_label="204", origin="from_negative_reply", priority="P1",
    )
    assert c.human_id.startswith("CL-")
    assert c.state == "paged"
    assert c.slack_thread_url.endswith(f"/thread/{c.human_id}")
    blocked = c.close(documentation="too short", now=None)
    assert blocked is False and c.state != "closed"
    ok = c.close(documentation="Resident stated she felt dizzy; vitals checked, MD notified.", now=None)
    assert ok and c.state == "closed" and c.closed_at is not None


def test_staff_break_routing():
    s = StaffMember(id="s1", tenant_id="demo-facility", display_name="Maria G.", role="RN", initials="MG")
    assert s.assignable() is True
    s.go_on_break(minutes=30)
    assert s.assignable() is False  # requires pull_off_break override
    s.come_off_break()
    assert s.assignable() is True
