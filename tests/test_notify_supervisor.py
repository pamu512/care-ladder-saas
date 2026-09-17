"""Task 5: notify_supervisor tool - dedicated supervisor adapter + tests."""

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

_REPO = Path(__file__).resolve().parents[1]
_FACILITY = _REPO / "configs" / "demo_facility.yaml"


class RecordingSupervisor(NotifySupervisorAdapter):
    def __init__(self):
        self.calls: list[str] = []

    def notify(self, message: str) -> dict:
        self.calls.append(message)
        return {"adapter": "recording-supervisor", "delivered": True, "message": message}


async def _run(sup=None):
    plan = load_care_plan(_FACILITY)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_silence"})
    return await run_incident(
        cue, plan,
        speaker=SpeakerSimulator(scripted=[]),
        dialer=StubDialer(behavior={"caregiver": "answered"}),
        supervisor_notifier=sup,
        now=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
    )


def test_supervisor_adapter_stub_without_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    a = NotifySupervisorAdapter(supervisor=type("S", (), {"display_name": "Floor Lead", "slack_user_id": "U0DEMO"})())
    res = a.notify("escalating")
    assert res["adapter"] == "stub"
    assert res["delivered"] is True
    assert "Floor Lead" in res["message"]  # supervisor addressed by name


def test_supervisor_adapter_mentions_slack_user(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/T000/B000/XXX")
    a = NotifySupervisorAdapter(supervisor=type("S", (), {"display_name": "Floor Lead", "slack_user_id": "U0DEMO"})())
    assert "<@U0DEMO>" in a._compose("resident unresponsive")


def test_orchestrator_uses_supervisor_notifier_for_supervisor_rung():
    rec = RecordingSupervisor()
    incident = asyncio.run(_run(sup=rec))
    ev = next(e for e in incident.events if e.tool == "notify_supervisor")
    assert ev.detail["adapter"] == "recording-supervisor"
    assert rec.calls, "supervisor notifier invoked"
    assert incident.status == "resolved"


def test_supervisor_rung_falls_back_to_channel_adapter():
    incident = asyncio.run(_run(sup=None))
    ev = next(e for e in incident.events if e.tool == "notify_supervisor")
    assert ev.detail["adapter"] == "stub"
    assert ev.detail["delivered"] is True
