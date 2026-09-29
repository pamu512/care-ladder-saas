"""P1 BotThread FSM: inform, first-wins ack, pressure at t-3, calling_N, close."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from care_ladder.channels.ack import AckRegistry
from care_ladder.channels.bot import BotThread
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerReply
from care_ladder.models import CueEvent

T0 = datetime(2026, 9, 29, 14, 42, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def _thread(clock: _Clock, *, registry: AckRegistry | None = None, dialer=None) -> BotThread:
    sent: list[dict] = []

    def sender(text: str, extra: dict | None = None) -> dict:
        payload = {"text": text, **(extra or {})}
        sent.append(payload)
        return {"adapter": "recording", "channel": "telegram", "delivered": True, "message": text, "msg_id": str(len(sent))}

    thread = BotThread(
        household_id="demo-family-1",
        channel="telegram",
        chat_ref="-1001",
        members=[
            {"id": "james", "display_name": "James", "role": "you"},
            {"id": "sarah", "display_name": "Sarah", "role": "next"},
        ],
        now=clock,
        sender=sender,
        dialer=dialer or StubDialer(behavior={"caregiver": "no_answer", "secondary": "no_answer"}),
        ack_registry=registry or AckRegistry(secret="fsm-test"),
    )
    thread.sent = sent  # type: ignore[attr-defined]
    return thread


def _page(thread: BotThread, timeout_sec: float = 300) -> None:
    thread.on_cue(CueEvent(kind="no_movement", confidence=0.9, detail={}))
    thread.on_speaker(SpeakerReply(kind="silence", raw=""))
    thread.page(
        incident_id="inc-fsm",
        rung_id="page_family",
        message="Mom didn't answer. Paging you now.",
        timeout_sec=timeout_sec,
        ack_url="https://demo.example/ack/tok",
        next_contact="Sarah",
    )


def test_speaker_ok_closes_without_paging_family():
    clock = _Clock(T0)
    thread = _thread(clock)
    thread.on_cue(CueEvent(kind="no_movement", confidence=0.9, detail={}))
    assert thread.state == "speaker_window"
    thread.on_speaker(SpeakerReply(kind="ok", raw="I'm fine"))
    assert thread.state == "closed"
    kinds = [e["message_kind"] for e in thread.audit]
    assert "inform_card" not in kinds


def test_inform_ack_in_window_stops_escalation():
    clock = _Clock(T0)
    thread = _thread(clock)
    _page(thread, timeout_sec=300)
    assert thread.state == "family_paged"
    result = thread.handle_button("ack", by="James", msg_ref="m-btn-1")
    assert result["accepted"] is True
    assert thread.escalation_stopped is True
    assert thread.owner == "James"
    clock.t = T0 + timedelta(seconds=300)
    thread.tick()
    assert thread.state != "calling_1"
    assert thread.state != "pressure"
    assert any("how did it go" in e["text"].lower() for e in thread.audit)


def test_pressure_fires_at_t_minus_3():
    clock = _Clock(T0)
    thread = _thread(clock)
    _page(thread, timeout_sec=300)
    clock.t = T0 + timedelta(seconds=119)
    thread.tick()
    assert thread.state == "family_paged"
    assert not any(e["message_kind"] == "pressure" for e in thread.audit)
    clock.t = T0 + timedelta(seconds=120)
    thread.tick()
    assert thread.state == "pressure"
    warn = next(e for e in thread.audit if e["message_kind"] == "pressure")
    assert "3:00" in warn["text"]
    assert "\u2014" not in warn["text"]


def test_deadline_starts_calling_1():
    clock = _Clock(T0)
    thread = _thread(clock)
    _page(thread, timeout_sec=300)
    clock.t = T0 + timedelta(seconds=300)
    thread.tick()
    assert thread.state == "calling_1"
    assert any("calling you now" in e["text"].lower() for e in thread.audit)


def test_call_answered_closes_with_docs():
    clock = _Clock(T0)
    thread = _thread(clock, dialer=StubDialer(behavior={"caregiver": "answered"}))
    _page(thread, timeout_sec=300)
    clock.t = T0 + timedelta(seconds=300)
    thread.tick()
    thread.on_call_result("answered", contact_id="caregiver", next_contact="Sarah")
    assert thread.state == "closed"
    close = next(e for e in thread.audit if e["message_kind"] == "close")
    assert "you answered" in close["text"].lower()
    assert "sarah" in close["text"].lower()
    assert thread.documentation


def test_numbered_reply_equals_button():
    clock = _Clock(T0)
    a = _thread(clock)
    b = _thread(_Clock(T0))
    _page(a)
    _page(b)
    a.handle_inbound("1", by="James", msg_ref="r1")
    b.handle_button("ack", by="James", msg_ref="b1")
    assert a.escalation_stopped is True
    assert b.escalation_stopped is True
    assert a.owner == b.owner == "James"


def test_new_cue_while_open_joins_same_thread():
    clock = _Clock(T0)
    thread = _thread(clock)
    _page(thread)
    thread.on_cue(CueEvent(kind="no_visibility", confidence=0.8, detail={}))
    assert thread.state == "family_paged"
    assert thread.active_count == 1


def test_audit_events_carry_timestamps_and_no_em_dash():
    clock = _Clock(T0)
    thread = _thread(clock)
    _page(thread)
    thread.handle_inbound("she's fine - balcony again", by="James", msg_ref="out1")
    # outcome before ack is ignored; ack first
    thread.handle_button("ack", by="James", msg_ref="m1")
    thread.handle_inbound("she's fine - balcony again", by="James", msg_ref="out2")
    assert thread.state == "closed"
    for ev in thread.audit:
        assert ev["at"]
        assert ev["channel"] == "telegram"
        assert ev["chat_ref"] == "-1001"
        assert "\u2014" not in ev["text"]
        assert "at" in ev
