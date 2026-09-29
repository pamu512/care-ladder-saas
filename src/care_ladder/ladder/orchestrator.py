"""Care ladder agentic loop: cue → rungs → audit trail."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, time, timezone
from typing import Any

from care_ladder.audit.store import AuditStore
from care_ladder.channels.dial import StubDialer, next_rung_after_no_answer
from care_ladder.channels.speaker import SpeakerChannel
from care_ladder.models import AuditEvent, CarePlan, CueEvent, Incident, PrivacyMode, Rung
from care_ladder.privacy import blur_faces, to_silhouette


def _contact_for_role(plan: CarePlan, role: str):
    if role == "caregiver":
        return plan.caregiver
    if role == "secondary":
        if plan.secondary is None:
            raise ValueError("plan has no secondary contact")
        return plan.secondary
    if role == "monitored":
        return plan.monitored
    raise ValueError(f"unknown contact role: {role!r}")


def _append(
    events: list[AuditEvent],
    *,
    tool: str,
    cue_kind: str | None = None,
    rung_id: str | None = None,
    detail: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> None:
    from datetime import datetime, timezone as _tz

    events.append(
        AuditEvent(
            tool=tool,
            cue_kind=cue_kind,
            rung_id=rung_id,
            detail=detail or {},
            at=at or datetime.now(_tz.utc),
        )
    )


def _flush_bot_audit(
    events: list[AuditEvent],
    thread,
    *,
    cue_kind: str | None = None,
    rung_id: str | None = None,
) -> None:
    """Copy new BotThread audit rows onto the incident timeline (tool=bot)."""
    if thread is None:
        return
    flushed = int(getattr(thread, "_flushed", 0))
    rows = list(getattr(thread, "audit", []) or [])
    for row in rows[flushed:]:
        at = None
        raw = row.get("at") if isinstance(row, dict) else None
        if isinstance(raw, datetime):
            at = raw
        elif isinstance(raw, str):
            try:
                at = datetime.fromisoformat(raw)
            except ValueError:
                at = None
        _append(
            events,
            tool="bot",
            cue_kind=cue_kind,
            rung_id=rung_id,
            detail=dict(row),
            at=at,
        )
    thread._flushed = len(rows)


def _family_thread_for_plan(plan, bot_thread, *, page_router, ack_registry, clock: datetime):
    """Reuse an injected thread, or build one when the plan pages a family channel."""
    if bot_thread is not None:
        return bot_thread
    from care_ladder.channels.bot import BotThread, adapter_channel, is_family_channel

    page = next(
        (
            r
            for r in plan.rungs
            if r.tool == "notify_and_await_ack"
            and is_family_channel(str(r.params.get("channel", "")))
        ),
        None,
    )
    if page is None:
        return None
    channel = adapter_channel(str(page.params.get("channel")))
    chat_ref = ""
    if plan.notifications is not None and plan.notifications.telegram.chat_id:
        chat_ref = str(plan.notifications.telegram.chat_id)
    adapter = page_router.get(channel) if page_router is not None else None
    next_name = plan.secondary.display_name if plan.secondary is not None else "Sarah"

    def sender(text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = extra or {}
        if adapter is None:
            return {"adapter": "stub", "channel": channel, "delivered": True, "message": text}
        if extra.get("buttons") and hasattr(adapter, "notify_alert"):
            return adapter.notify_alert(
                text,
                callback_id=str(extra.get("callback_id") or "x"),
                next_contact=next_name,
            )
        return adapter.notify(text)

    members = [
        {"id": "caregiver", "display_name": plan.caregiver.display_name, "role": "you"},
    ]
    if plan.secondary is not None:
        members.append(
            {"id": "secondary", "display_name": plan.secondary.display_name, "role": "next"}
        )
    return BotThread(
        household_id=plan.household_id,
        channel=channel,
        chat_ref=chat_ref or "family",
        members=members,
        now=lambda: clock,
        sender=sender,
        ack_registry=ack_registry,
    )


async def _wait_ack_ticking(
    registry,
    thread,
    incident_id: str,
    rung_id: str,
    timeout_sec: float,
    *,
    poll_sec: float = 0.25,
):
    """Same wait loop as the registry, plus BotThread.tick for pressure / calling_N."""
    import time

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        outcome = registry.outcome_for(incident_id, rung_id)
        if outcome is not None:
            return outcome
        if thread is not None:
            thread.tick()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(poll_sec, remaining))


def _log_jump(
    events: list[AuditEvent],
    rung: Rung,
    *,
    reason: str,
    from_index: int,
    to_index: int | None,
    **extra: Any,
) -> None:
    detail: dict[str, Any] = {
        "reason": reason,
        "skipped_tool": rung.tool,
        "skipped_rung_id": rung.id,
        "from_index": from_index,
        "to_index": to_index,
        **extra,
    }
    if rung.tool == "emergency":
        detail["emergency_enabled"] = rung.params.get("enabled")
    _append(
        events,
        tool="jump",
        rung_id=rung.id,
        detail=detail,
    )


def _find_dial_primary_index(plan: CarePlan) -> int:
    for i, rung in enumerate(plan.rungs):
        if rung.tool == "dial_contact" and rung.params.get("contact") == "caregiver":
            return i
    for i, rung in enumerate(plan.rungs):
        if rung.tool == "dial_contact":
            return i
    raise ValueError("care plan has no dial_contact rung")


async def _bounded_sleep(sec: float, max_wait_sec: float) -> float:
    """Sleep up to ``max_wait_sec`` (demo/tests stay snappy; full waits optional)."""
    duration = max(0.0, float(sec))
    if max_wait_sec >= 0:
        duration = min(duration, float(max_wait_sec))
    await asyncio.sleep(duration)
    return duration


def _parse_hhmm(value: str) -> time:
    hour_s, minute_s = value.strip().split(":", 1)
    return time(hour=int(hour_s), minute=int(minute_s))


def _in_quiet_hours(now: datetime, start_s: str, end_s: str) -> bool:
    """True if ``now.time()`` falls in [start, end) (supports overnight windows)."""
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    t = now.timetz().replace(tzinfo=None) if now.tzinfo else now.time()
    # Compare as naive local clock components from the provided datetime.
    t = time(hour=t.hour, minute=t.minute, second=t.second)
    if start <= end:
        return start <= t < end
    # Overnight e.g. 22:00 → 07:00
    return t >= start or t < end


def _apply_privacy(
    frames: list[Any],
    mode: PrivacyMode,
) -> tuple[list[Any], PrivacyMode | None, int]:
    """Map frames through blur/silhouette. Non-zero count only with a privacy mode."""
    if not frames:
        return [], None, 0
    if mode == "silhouette":
        transformed = [to_silhouette(f) for f in frames]
    else:
        transformed = [blur_faces(f) for f in frames]
        mode = "blur"
    return transformed, mode, len(transformed)


async def run_incident(
    cue: CueEvent,
    plan: CarePlan,
    speaker: SpeakerChannel,
    dialer: StubDialer,
    pre_event_frames: list[Any] | None = None,
    *,
    incident_id: str | None = None,
    store: AuditStore | None = None,
    notifier=None,
    supervisor_notifier=None,
    page_router=None,
    ack_registry=None,
    bot_thread=None,
    ack_base_url: str = "",
    max_wait_sec: float = 0.05,
    max_ack_wait_sec: float | None = None,
    privacy_mode: PrivacyMode = "blur",
    now: datetime | None = None,
) -> Incident:
    """Run the care-plan rung loop for one cue; return an Incident with audit events.

    Rung outcomes:
    - speaker ``ok`` → resolve
    - speaker ``call_caregiver`` → jump to dial primary (log skipped rungs)
    - speaker ``silence`` → continue
    - dial ``answered`` → resolve
    - dial ``no_answer`` → ``next_rung_after_no_answer`` (log jumps over skipped rungs)
    - ``notify_and_await_ack`` → page caretakers over the channel router, wait
      up to ``ack_timeout_sec`` for a signed-token acknowledgment; ack → resolve
      (``reason: caretaker_ack``), timeout → continue escalating to next rungs
    - ``emergency`` with ``enabled`` not True → fail-closed skip (never real 911)

    Pre-event frames are privacy-transformed (default blur) before attach count.
    """
    private_frames, privacy, frame_count = _apply_privacy(
        list(pre_event_frames or []), privacy_mode
    )
    # Refuse non-zero attach without a privacy transform flag.
    if frame_count > 0 and privacy not in {"blur", "silhouette"}:
        private_frames, privacy, frame_count = [], None, 0

    incident = Incident(
        id=incident_id or uuid.uuid4().hex,
        household_id=plan.household_id,
        cue=cue,
        events=[],
        status="open",
        pre_event_frame_count=frame_count,
        privacy=privacy,
    )
    # Keep transformed frames available to callers that need a clip snapshot
    # without serializing numpy into the pydantic model / JSON timeline.
    incident.__dict__["_private_pre_event_frames"] = private_frames

    # Allow ack scripts (and tests) to arm against the incident id before the
    # notify rung fires: run_incident accepts an optional incident_id.
    events = incident.events
    cue_detail: dict[str, Any] = {
        "confidence": cue.confidence,
        "detail": cue.detail,
    }
    if privacy is not None:
        cue_detail["privacy"] = privacy
        cue_detail["pre_event_frame_count"] = frame_count
    _append(
        events,
        tool="cue",
        cue_kind=cue.kind,
        detail=cue_detail,
    )

    clock = now or datetime.now(timezone.utc)
    if (
        plan.quiet_hours is not None
        and plan.quiet_hours.policy == "soft_suppress_non_distress"
        and cue.kind != "distress_heuristic"
        and _in_quiet_hours(clock, plan.quiet_hours.start, plan.quiet_hours.end)
    ):
        _append(
            events,
            tool="suppress",
            cue_kind=cue.kind,
            detail={
                "reason": "quiet_hours",
                "policy": plan.quiet_hours.policy,
                "quiet_hours_start": plan.quiet_hours.start,
                "quiet_hours_end": plan.quiet_hours.end,
            },
        )
        incident.status = "suppressed"
        if store is not None:
            store.save(incident)
        return incident

    from care_ladder.channels.bot import is_family_channel
    from care_ladder.channels.router import PageRouter as _PageRouter

    family_page = any(
        r.tool == "notify_and_await_ack"
        and is_family_channel(str(r.params.get("channel", "")))
        for r in plan.rungs
    )
    router = page_router
    registry = ack_registry
    thread = bot_thread
    if family_page or bot_thread is not None:
        if router is None:
            router = _PageRouter()
        if registry is None:
            from care_ladder.channels.ack import AckRegistry

            registry = AckRegistry()
        thread = _family_thread_for_plan(
            plan, bot_thread, page_router=router, ack_registry=registry, clock=clock
        )
        if thread is not None:
            thread.on_cue(cue)

    idx = 0
    n = len(plan.rungs)
    skip_next_wait = False
    # Common zones (shared spaces) never get a spoken check-in: the person on
    # camera may not be the monitored subject, and speaker-asking a shared
    # room is a privacy intrusion. Cue detail carries zone_id; kind comes
    # from the plan. Cues without zone info keep the check-in (back-compat).
    zone_id = cue.detail.get("zone_id")
    zone = next((z for z in plan.zones if z.id == zone_id), None)
    common_zone = bool(zone is not None and getattr(zone, "kind", "private") == "common")
    while idx < n:
        rung = plan.rungs[idx]
        tool = rung.tool

        if tool == "reperceive":
            _append(
                events,
                tool="reperceive",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={"params": dict(rung.params), "result": "stub_ok"},
            )
            idx += 1
            continue

        if tool == "speaker_prompt" and common_zone:
            _append(
                events,
                tool="speaker_prompt",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    "skipped": True,
                    "reason": "common_zone_no_spoken_checkin",
                    "zone_id": zone_id,
                },
            )
            idx += 1
            continue

        if tool == "speaker_prompt":
            text = str(rung.params.get("text", "Are you okay?"))
            wait_sec = float(rung.params.get("wait_sec", 0))
            consumed_follow_wait = False
            # Prefer following wait rung as listen window when speaker has no wait_sec.
            if "wait_sec" not in rung.params and idx + 1 < n and plan.rungs[idx + 1].tool == "wait":
                wait_sec = float(plan.rungs[idx + 1].params.get("sec", wait_sec))
                consumed_follow_wait = True
            # Bound the speaker listen window for demo/tests.
            listen = wait_sec
            if max_wait_sec >= 0:
                listen = min(listen, float(max_wait_sec))
            reply = await speaker.prompt(text, listen)
            _append(
                events,
                tool="speaker_prompt",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    "text": text,
                    "reply_kind": reply.kind,
                    "reply_raw": reply.raw,
                    "wait_sec": listen,
                },
            )
            if thread is not None:
                thread.on_speaker(reply)
                _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
            if reply.kind == "ok":
                incident.status = "resolved"
                _append(
                    events,
                    tool="resolve",
                    cue_kind=cue.kind,
                    detail={"reason": "speaker_ok"},
                )
                break
            if reply.kind == "call_caregiver":
                target = _find_dial_primary_index(plan)
                for k in range(idx + 1, target):
                    _log_jump(
                        events,
                        plan.rungs[k],
                        reason="call_caregiver",
                        from_index=idx,
                        to_index=target,
                    )
                idx = target
                continue
            # silence → continue; skip wait if it was already the listen window
            if consumed_follow_wait:
                skip_next_wait = True
            idx += 1
            continue

        if tool == "wait":
            if skip_next_wait:
                _log_jump(
                    events,
                    rung,
                    reason="listen_window_already_consumed",
                    from_index=idx,
                    to_index=idx + 1 if idx + 1 < n else None,
                )
                skip_next_wait = False
                idx += 1
                continue
            sec = float(rung.params.get("sec", 0))
            slept = await _bounded_sleep(sec, max_wait_sec)
            _append(
                events,
                tool="wait",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={"sec": sec, "slept_sec": slept},
            )
            idx += 1
            continue

        if tool in ("notify_channel", "notify_supervisor"):
            from care_ladder.channels.notify import NotifyChannelAdapter

            if tool == "notify_channel":
                adapter = notifier
            else:
                adapter = supervisor_notifier if supervisor_notifier is not None else notifier
            if adapter is None:
                adapter = NotifyChannelAdapter()  # honest stub; audit records adapter
            message = str(rung.params.get("message", f"{tool} triggered by {cue.kind}"))
            try:
                result = adapter.notify(message)
            except Exception as exc:
                result = {"adapter": "stub", "delivered": False, "error": str(exc), "message": message}
            _append(
                events,
                tool=tool,
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail=dict(result),
            )
            idx += 1
            continue

        if tool == "notify_and_await_ack":
            from care_ladder.channels.bot import adapter_channel
            from care_ladder.channels.router import PageRouter

            channel_id = str(rung.params.get("channel", "slack"))
            message = str(
                rung.params.get("message", f"check-in needed ({cue.kind})")
            )
            ack_timeout = float(rung.params.get("ack_timeout_sec", 300))
            # Ack-wait bounding: inherit the demo max_wait_sec bound unless the
            # caller overrides with max_ack_wait_sec (fixtures demoing real ack
            # windows pass a few seconds; -1 = full plan window). This keeps
            # existing tests/demos snappy while allowing real deadlines.
            cap = max_ack_wait_sec if max_ack_wait_sec is not None else max_wait_sec
            wait_budget = ack_timeout if cap < 0 else min(ack_timeout, float(cap))

            if router is None:
                router = page_router or PageRouter()
            adapter = router.get(adapter_channel(channel_id))
            family = is_family_channel(channel_id)

            if registry is None:
                from care_ladder.channels.ack import AckRegistry

                registry = ack_registry or AckRegistry()

            base_url = ack_base_url or ""
            pending = registry.create_pending(
                incident.id,
                rung.id,
                adapter_channel(channel_id) if family else channel_id,
                message,
                wait_budget,
                base_url,
            )
            if family:
                if thread is None:
                    thread = _family_thread_for_plan(
                        plan, None, page_router=router, ack_registry=registry, clock=clock
                    )
                    if thread is not None:
                        thread.on_cue(cue)
                try:
                    result = thread.page(
                        incident_id=incident.id,
                        rung_id=rung.id,
                        message=message,
                        timeout_sec=wait_budget,
                        ack_url=pending.ack_url,
                        pending=pending,
                        base_url=base_url,
                    )
                except Exception as exc:
                    result = {
                        "adapter": "stub",
                        "channel": adapter_channel(channel_id),
                        "delivered": False,
                        "error": str(exc),
                        "message": message,
                    }
                _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
            else:
                paged = f"{message}\nAcknowledge (stops escalation): {pending.ack_url}"
                try:
                    result = adapter.notify(paged)
                except Exception as exc:
                    result = {
                        "adapter": "stub",
                        "channel": channel_id,
                        "delivered": False,
                        "error": str(exc),
                        "message": message,
                    }
            _append(
                events,
                tool="notify_and_await_ack",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    **dict(result),
                    "ack_timeout_sec": ack_timeout,
                    "waited_sec": wait_budget,
                    "ack_deadline": pending.deadline.isoformat(),
                },
            )

            if family:
                outcome = await _wait_ack_ticking(
                    registry, thread, incident.id, rung.id, wait_budget
                )
                _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
            else:
                outcome = await registry.wait_for_ack(
                    incident.id, rung.id, wait_budget
                )
            if outcome is None:
                # Close the race: an ack recorded in the last poll interval
                # still wins over escalation.
                outcome = registry.outcome_for(incident.id, rung.id)
            if outcome is not None:
                if thread is not None and family:
                    thread.record_ack(outcome)
                    _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
                registry.close_pending(incident.id, rung.id, reason="acked")
                incident.status = "resolved"
                _append(
                    events,
                    tool="resolve",
                    cue_kind=cue.kind,
                    detail={
                        "reason": "caretaker_ack",
                        "acked_by": outcome.acked_by,
                        "ack_channel": outcome.channel,
                        "ack_at": outcome.acked_at.isoformat(),
                        "rung_id": rung.id,
                    },
                )
                break
            if thread is not None and family:
                thread.tick()
                _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
            registry.close_pending(incident.id, rung.id, reason="ack_timeout")
            _append(
                events,
                tool="ack_timeout",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    "reason": "no_ack_before_deadline",
                    "ack_timeout_sec": ack_timeout,
                    "next": "escalating to next rung",
                },
            )
            idx += 1
            continue

        if tool == "dial_contact":
            role = str(rung.params.get("contact", "caregiver"))
            contact = _contact_for_role(plan, role)
            ring_sec = float(rung.params.get("ring_sec", 1.0))
            if max_wait_sec >= 0:
                ring_sec = min(ring_sec, float(max_wait_sec))
            result = dialer.dial(contact, ring_sec=ring_sec)
            _append(
                events,
                tool="dial_contact",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    "contact": role,
                    "contact_id": result.contact_id,
                    "status": result.status,
                    "phone_e164": contact.phone_e164,
                },
            )
            if thread is not None:
                nxt = plan.secondary.display_name if plan.secondary is not None else "the next contact"
                thread.on_call_result(result.status, contact_id=result.contact_id, next_contact=nxt)
                _flush_bot_audit(events, thread, cue_kind=cue.kind, rung_id=rung.id)
            if result.status == "answered":
                incident.status = "resolved"
                _append(
                    events,
                    tool="resolve",
                    cue_kind=cue.kind,
                    detail={"reason": "dial_answered", "contact_id": result.contact_id},
                )
                break
            if result.status in {"no_answer", "skipped"}:
                nxt = next_rung_after_no_answer(plan, idx)
                if nxt is None:
                    for k in range(idx + 1, n):
                        _log_jump(
                            events,
                            plan.rungs[k],
                            reason="no_answer_fail_closed_or_exhausted",
                            from_index=idx,
                            to_index=None,
                        )
                    incident.status = "exhausted"
                    break
                for k in range(idx + 1, nxt):
                    _log_jump(
                        events,
                        plan.rungs[k],
                        reason="no_answer_escalation",
                        from_index=idx,
                        to_index=nxt,
                    )
                idx = nxt
                continue
            idx += 1
            continue

        if tool == "emergency":
            enabled = rung.params.get("enabled") is True
            if not enabled:
                _log_jump(
                    events,
                    rung,
                    reason="emergency_disabled_fail_closed",
                    from_index=idx,
                    to_index=idx + 1 if idx + 1 < n else None,
                )
                idx += 1
                continue
            # Enabled emergency: audit only in demo — never place a real 911 call.
            _append(
                events,
                tool="emergency",
                cue_kind=cue.kind,
                rung_id=rung.id,
                detail={
                    "executed": False,
                    "enabled": True,
                    "note": "demo_stub_no_real_911",
                },
            )
            incident.status = "exhausted"
            break

        # Unknown tool: log and continue
        _append(
            events,
            tool=tool,
            cue_kind=cue.kind,
            rung_id=rung.id,
            detail={"params": dict(rung.params), "result": "unknown_tool_skipped"},
        )
        idx += 1

    if incident.status == "open":
        incident.status = "exhausted"

    if store is not None:
        store.save(incident)
    return incident
