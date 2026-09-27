"""Task 11: Galuxium cut demo script carries the facility notify beat."""

from pathlib import Path


def test_galuxium_demo_script_exists_and_has_facility_beat():
    text = Path("docs/galuxium/demo-video-galuxium.md").read_text(encoding="utf-8")
    low = text.lower()
    assert "facility" in low
    assert "notify" in low
    assert "supervisor" in low


def test_galuxium_script_covers_core_beats():
    text = Path("docs/galuxium/demo-video-galuxium.md").read_text(encoding="utf-8")
    low = text.lower()
    # Path A ladder + DNN + fall signature beats carry over from the OpenCV cut
    assert "path a" in low
    assert "path b" in low
    assert "check-in" in low or "checkin" in low or "check in" in low
    assert "audit" in low


def test_galuxium_script_writes_honest_disclaimers():
    text = Path("docs/galuxium/demo-video-galuxium.md").read_text(encoding="utf-8")
    low = text.lower()
    assert "stub" in low
    assert "555" in low or "five-five-five" in low  # reserved fictional numbers stated
    assert "emergency" in low  # must state emergency calling is off/fail-closed


def test_opencv_script_untouched():
    # the OpenCV cut's production script must not grow a facility beat
    text = Path("docs/demo-video-script.md").read_text(encoding="utf-8")
    assert "notify_supervisor" not in text
