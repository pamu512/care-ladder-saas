"""P1 orchestrator: telegram_family pages through BotThread; audit stamps ``at``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from care_ladder.channels.ack import AckRegistry
from care_ladder.channels.bot import BotThread
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.router import PageRouter
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan

_REPO = Path(__file__).resolve().parents[1]
_FAMILY = _REPO / "configs" / "demo_family.yaml"
_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _plan():
    import copy

    plan = load_care_plan(_FAMILY)
    plan = copy.deepcopy(plan)
    for rung in plan.rungs:
        if rung.tool == "notify_and_await_ack":
            rung.params["ack_timeout_sec"] = 0.3
    return plan


def _thread(registry: AckRegistry) -> BotThread:
    sent: list[str] = []

    def sender(text: str, extra=None):
        sent.append(text)
        return {"adapter": "recording", "channel": "telegram", "delivered": True, "message": text, "msg_id": str(len(sent))}

    thread = BotThread(
        household_id="demo-family-1",
        channel="telegram",
        chat_ref="-1001",
        members=[{"id": "james", "display_name": "James", "role": "you"},
                 {"id": "sarah", "display_name": "Sarah", "role": "next"}],
        sender=sender,
        ack_registry=registry,
        now=lambda: _NOW,
    )
    thread.sent = sent  # type: ignore[attr-defined]
    return thread


def test_demo_family_plan_loads_telegram_family_channel():
    plan = load_care_plan(_FAMILY)
    assert plan.household_id == "demo-family-1"
    assert plan.mode == "home"
    page = next(r for r in plan.rungs if r.tool == "notify_and_await_ack")
    assert page.params["channel"] == "telegram_family"
    assert any(r.tool == "speaker_prompt" for r in plan.rungs)
    assert any(r.tool == "dial_contact" for r in plan.rungs)


def test_family_plan_routes_page_through_bot_thread():
    plan = _plan()
    registry = AckRegistry(secret="fam-orch")
    thread = _thread(registry)

    async def scenario():
        return await run_incident(
            cue=CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "family_silence"}),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            page_router=PageRouter(),
            ack_registry=registry,
            bot_thread=thread,
            ack_base_url="https://demo.example",
            max_ack_wait_sec=-1,
            now=_NOW,
            incident_id="inc-fam-timeout",
        )

    incident = asyncio.run(scenario())
    tools = [e.tool for e in incident.events]
    assert "notify_and_await_ack" in tools
    assert "bot" in tools
    bot_events = [e for e in incident.events if e.tool == "bot"]
    assert any(e.detail.get("message_kind") == "inform_card" for e in bot_events)
    assert all(e.at is not None for e in bot_events)
    assert all(e.detail.get("at") for e in bot_events)
    assert thread.state in {"family_paged", "pressure", "calling_1", "closed"}
    # inform card was sent by the thread, not a bare telegram adapter string
    assert any("Paging you now" in m or "didn't answer" in m for m in thread.sent)


def test_family_ack_via_bot_stops_escalation():
    plan = _plan()
    registry = AckRegistry(secret="fam-orch-ack")
    thread = _thread(registry)
    incident_id = "inc-fam-ack"

    async def scenario():
        registry.schedule_auto_ack(incident_id, after_sec=0.05, by="James", channel="telegram")
        return await run_incident(
            cue=CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "family_ack"}),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            page_router=PageRouter(),
            ack_registry=registry,
            bot_thread=thread,
            ack_base_url="https://demo.example",
            max_ack_wait_sec=-1,
            now=_NOW,
            incident_id=incident_id,
        )

    incident = asyncio.run(scenario())
    tools = [e.tool for e in incident.events]
    resolve = next(e for e in incident.events if e.tool == "resolve")
    assert resolve.detail["reason"] == "caretaker_ack"
    assert resolve.detail["ack_channel"] == "telegram"
    assert "dial_contact" not in tools
    assert incident.status == "resolved"
    assert resolve.at is not None


def test_ack_link_fallback_still_resolves_family_page():
    """GET /ack/{token} (web origin) still first-wins the same pending window."""
    plan = _plan()
    registry = AckRegistry(secret="fam-link")
    thread = _thread(registry)
    incident_id = "inc-fam-link"

    async def scenario():
        async def tap_link():
            await asyncio.sleep(0.05)
            pending = registry.get_pending(incident_id, "page_family")
            assert pending is not None
            registry.acknowledge(pending.token, by="James (ack link)", channel="web", origin="link")

        incident, _ = await asyncio.gather(
            run_incident(
                cue=CueEvent(kind="no_movement", confidence=0.9, detail={}),
                plan=plan,
                speaker=SpeakerSimulator(scripted=[]),
                dialer=StubDialer(behavior={"caregiver": "answered"}),
                page_router=PageRouter(),
                ack_registry=registry,
                bot_thread=thread,
                ack_base_url="https://demo.example",
                max_ack_wait_sec=-1,
                now=_NOW,
                incident_id=incident_id,
            ),
            tap_link(),
        )
        return incident

    incident = asyncio.run(scenario())
    resolve = next(e for e in incident.events if e.tool == "resolve")
    assert resolve.detail["reason"] == "caretaker_ack"
    assert resolve.detail["ack_channel"] == "web"
    assert incident.status == "resolved"
