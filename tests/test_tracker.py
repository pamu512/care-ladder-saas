"""PersonTracker: count, enter/leave, shape signatures, stranger-vs-resident case."""

from care_ladder.vision.tracker import PersonTracker


def _det(cx, cy, h, w):
    return {"cx": cx, "cy": cy, "height_ratio": h, "aspect": w / h if h else 0.0}


def test_single_person_count_and_leave():
    tr = PersonTracker(320, 240, max_missed=2)
    snap = tr.observe([_det(160, 120, 0.5, 0.3)], t=0.0)
    assert snap["person_count"] == 1
    snap = tr.observe([_det(162, 121, 0.5, 0.3)], t=0.5)  # same person, moved a bit
    assert snap["person_count"] == 1
    assert len(snap["tracks"]) == 1
    assert snap["tracks"][0]["frames"] == 2

    # person leaves; after max_missed empty frames the track retires
    snap = tr.observe([], t=1.0)
    assert snap["person_count"] == 1  # not retired yet
    snap = tr.observe([], t=1.5)
    assert snap["person_count"] == 1  # miss #2
    snap = tr.observe([], t=2.0)
    assert snap["person_count"] == 0  # retired
    events = snap["events"]
    assert events[0]["type"] == "enter"
    assert events[-1]["type"] == "leave"


def test_two_simultaneous_people_kept_separate():
    tr = PersonTracker(320, 240)
    tr.observe([_det(80, 120, 0.6, 0.3), _det(240, 120, 0.4, 0.25)], t=0.0)
    snap = tr.observe([_det(82, 120, 0.6, 0.3), _det(242, 121, 0.4, 0.25)], t=0.5)
    assert snap["person_count"] == 2
    # distinct height signatures preserved (tall vs short)
    heights = sorted(t["height_ratio"] for t in snap["tracks"])
    assert heights == [0.4, 0.6]


def test_stranger_replaces_resident_detected_as_two_tracks():
    """Resident leaves, a different-height person enters → leave + enter events."""
    tr = PersonTracker(320, 240, max_missed=1)
    tr.observe([_det(160, 120, 0.7, 0.3)], t=0.0)  # resident (tall)
    tr.observe([_det(160, 120, 0.7, 0.3)], t=0.5)
    tr.observe([], t=1.0)  # resident gone (miss 1)
    snap = tr.observe([_det(160, 125, 0.45, 0.3)], t=1.5)  # shorter stranger enters
    # new det does NOT match the missed tall track (height delta > gate)
    kinds = [e["type"] for e in snap["events"]]
    assert "leave" in kinds and "enter" in kinds
    enter = next(e for e in snap["events"] if e["type"] == "enter" and e["t"] == 1.5)
    assert enter["height_ratio"] == 0.45


def test_height_gate_prevents_wrong_match():
    tr = PersonTracker(320, 240, max_missed=1)
    tr.observe([_det(160, 120, 0.8, 0.3)], t=0.0)  # very tall
    snap = tr.observe([_det(160, 120, 0.3, 0.5)], t=0.5)  # same spot, very different shape
    # must be a NEW track, not a match: new shape is tracked,
    # old tall one still pending retirement this frame
    new_tracks = [t for t in snap["tracks"] if t["height_ratio"] == 0.3]
    assert len(new_tracks) == 1
    # and after retirement frames the tall track leaves
    snap = tr.observe([_det(160, 120, 0.3, 0.5)], t=1.0)
    assert snap["person_count"] == 1
    assert all(t["height_ratio"] == 0.3 for t in snap["tracks"])
