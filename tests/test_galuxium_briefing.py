"""Task 12: Devpost executive briefing covers required sections."""

from pathlib import Path


def test_executive_briefing_exists_and_covers_required_sections():
    p = Path("docs/galuxium/executive-briefing.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8").lower()
    for needle in [
        "market",
        "architecture",
        "facility",
        "stripe",
        "fiscal",
        "readypup",
        "911",
        "medical",
    ]:
        assert needle in text
    assert "hipaa certified" not in text
    assert (
        "diagnos" not in text
        or "not a" in text
        or "no medical" in text
        or "non-clinical" in text
        or "does not diagnose" in text
    )


def test_briefing_has_fiscal_table_and_demo_accounts():
    text = Path("docs/galuxium/executive-briefing.md").read_text(encoding="utf-8")
    assert "$9/mo" in text and "$49/mo" in text and "$99/mo" in text
    assert "$29" not in text and "$199" not in text and "$499" not in text
    assert "demo@careladder.local" in text
