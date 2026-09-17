"""Task 4: notify_channel tool (Slack webhook / stub) + orchestrator wiring."""

from care_ladder.channels.notify import NotifyChannelAdapter, notify_channel_tool
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FACILITY = _REPO / "configs" / "demo_facility.yaml"


class RecordingNotifier(NotifyChannelAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def notify(self, message: str) -> dict:
        self.calls.append(message)
        return {"adapter": "recording", "delivered": True}


def test_notify_channel_adapter_stub_when_no_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    a = NotifyChannelAdapter()
    res = a.notify("hello ops")
    assert res["adapter"] == "stub"
    assert res["delivered"] is True  # stub success is honest in demo; audit records adapter


def test_notify_channel_adapter_slack_when_webhook(monkeypatch):
    import asyncio

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/T000/B000/XXX")
    a = NotifyChannelAdapter()
    sent: list[dict] = []

    import httpx2 as httpx

    async def fake_post(self, url, *, json=None, **kw):
        sent.append({"url": url, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res = asyncio.run(a.notify_async("floor lead needed"))
    assert res["adapter"] == "slack"
    assert res["delivered"] is True, res
    assert sent and "floor lead needed" in sent[0]["json"]["text"]


async def _run_facility_incident(notifier=None):
    plan = load_care_plan(_FACILITY)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "facility_silence"})
    from datetime import datetime, timezone

    return await run_incident(
        cue,
        plan,
        speaker=SpeakerSimulator(scripted=[]),  # silence -> falls through to notify
        dialer=StubDialer(behavior={"caregiver": "answered"}),
        notifier=notifier,
        now=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),  # midday: outside quiet hours
    )


def test_orchestrator_runs_notify_channel_rung():
    import asyncio

    recorder = RecordingNotifier()
    incident = asyncio.run(_run_facility_incident(notifier=recorder))
    tools = [e.tool for e in incident.events]
    assert "notify_channel" in tools
    assert "notify_supervisor" in tools  # Task 5 wires this; rung exists in plan
    assert incident.status == "resolved"
    # the notify event carries adapter + message detail
    ev = next(e for e in incident.events if e.tool == "notify_channel")
    assert ev.detail["delivered"] is True
    assert recorder.calls, "notifier was invoked"


def test_notify_missing_notifier_falls_back_to_stub_audit():
    import asyncio

    incident = asyncio.run(_run_facility_incident(notifier=None))
    ev = next(e for e in incident.events if e.tool == "notify_channel")
    assert ev.detail["adapter"] == "stub"
    assert ev.detail["delivered"] is True
