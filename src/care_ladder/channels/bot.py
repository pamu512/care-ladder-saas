"""Family bot thread: conversation FSM for Telegram / WhatsApp household chats.

P1 owns the thread model and first-wins ack from chat (button, numbered reply,
or the signed ack-link fallback). Voice hops reuse the dial stub. Every
send/receive is an audit event with an ``at`` timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from care_ladder.channels.ack import AckRegistry, PendingAck, parse_chat_reply
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerReply
from care_ladder.models import CueEvent

BotState = Literal[
    "idle",
    "speaker_window",
    "family_paged",
    "pressure",
    "calling_1",
    "calling_2",
    "calling_3",
    "closed",
]

FAMILY_CHANNELS = frozenset({"telegram_family", "whatsapp_family"})
PRESSURE_LEAD_SEC = 180.0  # family_paged at t-3:00 -> pressure

# Served copy: ASCII hyphen / period only. No em dashes.
BTN_ACK = "I'm on it. I'll call her myself"
BTN_CALL = "Call Mom now"
BTN_PASS = "Can't take it. Go to {next}"
INFORM_HINT = 'Tap a button, or reply 1 / 2 / 3. Ack link (fallback): {ack_url}'
PRESSURE_TEXT = "No acknowledgment in 3:00. Calling you in 2:00 unless someone taps."
CALLING_TEXT = "Calling you now. {next} is next if you can't take it."
CALL_ANSWERED = "You answered. {next} was not contacted."
HOW_DID_IT_GO = "Noted, {name}. Escalation stopped. How did it go?"
CLOSE_CARD = "Closed. All fine. {docs}"
SPEAKER_ASKED = "Mom asked. Family is not paged unless she stays silent."


def is_family_channel(channel_id: str) -> bool:
    cid = (channel_id or "").strip()
    return cid in FAMILY_CHANNELS or cid.endswith("_family")


def adapter_channel(channel_id: str) -> str:
    """Map telegram_family / whatsapp_family onto the live adapter id."""
    cid = (channel_id or "").strip()
    if cid in {"telegram_family", "telegram"}:
        return "telegram"
    if cid in {"whatsapp_family", "whatsapp"}:
        return "whatsapp"
    if cid.endswith("_family"):
        return cid[: -len("_family")]
    return cid


def family_alert_buttons(next_contact: str = "the next contact") -> list[tuple[str, str]]:
    """Inline-button (action, label) rows. Labels never contain em dashes."""
    return [
        ("ack", BTN_ACK),
        ("call_now", BTN_CALL),
        ("pass", BTN_PASS.format(next=next_contact)),
    ]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assert_copy(text: str) -> str:
    if "\u2014" in text:
        raise ValueError("served copy must not contain em dashes")
    return text


Sender = Callable[..., dict[str, Any]]


@dataclass
class BotThread:
    """One active conversation per household."""

    household_id: str
    channel: str
    chat_ref: str
    members: list[dict[str, str]] = field(default_factory=list)
    now: Callable[[], datetime] = field(default=_utcnow)
    sender: Sender | None = None
    dialer: StubDialer | None = None
    ack_registry: AckRegistry | None = None
    state: BotState = "idle"
    owner: str | None = None
    documentation: str | None = None
    escalation_stopped: bool = False
    audit: list[dict[str, Any]] = field(default_factory=list)
    page_at: datetime | None = None
    pressure_at: datetime | None = None
    deadline: datetime | None = None
    call_deadline_1: datetime | None = None
    incident_id: str | None = None
    rung_id: str | None = None
    pending_token: str | None = None
    ack_url: str | None = None
    next_contact: str = "Sarah"
    callback_id: str | None = None
    _pressure_sent: bool = False
    _call_announced: int = 0

    @property
    def active_count(self) -> int:
        return 0 if self.state in {"idle", "closed"} else 1

    def next_member_name(self) -> str:
        for m in self.members:
            if m.get("role") == "next":
                return m.get("display_name") or self.next_contact
        return self.next_contact

    def on_cue(self, cue: CueEvent) -> None:
        """Start or join the household thread. One conversation at a time."""
        _ = cue
        if self.state not in {"idle", "closed"}:
            return
        self.state = "speaker_window"
        self.escalation_stopped = False
        self.owner = None
        self.documentation = None
        self._pressure_sent = False
        self._call_announced = 0
        self.page_at = None
        self.pressure_at = None
        self.deadline = None
        self.call_deadline_1 = None
        self.pending_token = None

    def on_speaker(self, reply: SpeakerReply) -> None:
        if self.state != "speaker_window":
            return
        if reply.kind == "ok":
            self.documentation = reply.raw or "speaker ok"
            self._audit("close", f"Mom answered. Family was never paged. {self.documentation}")
            self.state = "closed"
            return
        self._audit("speaker_window", SPEAKER_ASKED)

    def page(
        self,
        *,
        incident_id: str,
        rung_id: str,
        message: str,
        timeout_sec: float,
        ack_url: str = "",
        next_contact: str | None = None,
        pending: PendingAck | None = None,
        base_url: str = "",
    ) -> dict[str, Any]:
        """Send the inform card and open the first-wins ack window."""
        if next_contact:
            self.next_contact = next_contact
        else:
            self.next_contact = self.next_member_name()
        self.incident_id = incident_id
        self.rung_id = rung_id
        now = self.now()
        timeout = max(1.0, float(timeout_sec))
        if pending is None and self.ack_registry is not None:
            pending = self.ack_registry.create_pending(
                incident_id,
                rung_id,
                adapter_channel(self.channel),
                message,
                timeout,
                base_url or "https://local",
                created_at=now,
            )
        if pending is not None:
            self.pending_token = pending.token
            self.ack_url = pending.ack_url
            self.callback_id = pending.token[:12]
        else:
            self.ack_url = ack_url
            self.callback_id = f"{incident_id[:8]}{rung_id[:4]}"
        self.page_at = now
        self.deadline = now + timedelta(seconds=timeout)
        pressure_at = self.deadline - timedelta(seconds=PRESSURE_LEAD_SEC)
        self.pressure_at = pressure_at if pressure_at > now else now
        self.state = "family_paged"
        self._pressure_sent = False
        text = _assert_copy(
            f"{message}\n{INFORM_HINT.format(ack_url=self.ack_url or ack_url)}"
        )
        extra = {
            "buttons": family_alert_buttons(self.next_contact),
            "callback_id": self.callback_id,
            "ack_url": self.ack_url,
        }
        result = self._send(text, extra)
        self._audit("inform_card", text, msg_id=str(result.get("msg_id") or ""))
        return result

    def tick(self, at: datetime | None = None) -> None:
        if self.escalation_stopped or self.state in {"idle", "closed", "speaker_window"}:
            return
        clock = at or self.now()
        if (
            self.state == "family_paged"
            and self.pressure_at is not None
            and clock >= self.pressure_at
            and not self._pressure_sent
        ):
            self._pressure_sent = True
            self.state = "pressure"
            result = self._send(_assert_copy(PRESSURE_TEXT), {})
            self._audit("pressure", PRESSURE_TEXT, msg_id=str(result.get("msg_id") or ""))
        if (
            self.state in {"family_paged", "pressure"}
            and self.deadline is not None
            and clock >= self.deadline
        ):
            self._begin_call(1)

    def handle_button(self, action: str, *, by: str | None = None, msg_ref: str | None = None) -> dict[str, Any]:
        self._audit("inbound", f"button:{action}", msg_id=msg_ref)
        return self._accept_action(action, by=by, msg_ref=msg_ref, origin="button")

    def handle_inbound(self, text: str, *, by: str | None = None, msg_ref: str | None = None) -> dict[str, Any]:
        self._audit("inbound", text, msg_id=msg_ref)
        action = parse_chat_reply(text)
        if not self.escalation_stopped:
            if action:
                return self._accept_action(action, by=by, msg_ref=msg_ref, origin="reply")
            return {"accepted": False, "reason": "not an ack"}
        if action:
            return {"accepted": False, "reason": "already acknowledged"}
        self._close_with_docs(text)
        return {"accepted": True, "reason": "outcome"}

    def record_ack(self, outcome: Any, *, origin: str | None = None) -> None:
        """Apply a registry outcome (ack-link or chat) onto the thread."""
        if self.escalation_stopped:
            return
        self.escalation_stopped = True
        self.owner = getattr(outcome, "acked_by", None)
        name = self.owner or "you"
        msg = _assert_copy(HOW_DID_IT_GO.format(name=name))
        result = self._send(msg, {})
        self._audit("how_did_it_go", msg, msg_id=str(result.get("msg_id") or ""))
        if origin == "call_now" or getattr(outcome, "note", None) == "call_now":
            self._begin_call(1)

    def on_call_result(
        self,
        status: str,
        *,
        contact_id: str,
        next_contact: str | None = None,
    ) -> None:
        nxt = next_contact or self.next_contact
        if status == "answered":
            self.documentation = f"answered on call ({contact_id})"
            msg = _assert_copy(CALL_ANSWERED.format(next=nxt))
            result = self._send(msg, {})
            self._audit("close", msg, msg_id=str(result.get("msg_id") or ""))
            self.escalation_stopped = True
            self.state = "closed"
            return
        # no_answer / skipped: climb to the next calling_N slot
        current = 1
        if self.state.startswith("calling_"):
            try:
                current = int(self.state.split("_", 1)[1])
            except ValueError:
                current = 1
        nxt_n = current + 1
        if nxt_n <= 3:
            self._begin_call(nxt_n)

    def drain_audit_events(self) -> list[dict[str, Any]]:
        """Copy of audit rows for the incident timeline (tool=bot)."""
        return [dict(e) for e in self.audit]

    def _accept_action(
        self,
        action: str,
        *,
        by: str | None,
        msg_ref: str | None,
        origin: str,
    ) -> dict[str, Any]:
        if action == "pass":
            # Does not consume the window; next contact can still ack.
            self._audit("pass", f"{by or 'member'} passed. Next is {self.next_contact}.")
            return {"accepted": False, "reason": "passed"}
        if self.escalation_stopped:
            return {"accepted": False, "reason": "already acknowledged"}
        if self.ack_registry is not None and self.pending_token:
            outcome, reason = self.ack_registry.acknowledge(
                self.pending_token,
                by=by,
                note=action,
                channel=adapter_channel(self.channel),
                msg_ref=msg_ref,
                origin=origin,
            )
            if outcome is None:
                return {"accepted": False, "reason": reason}
            self.record_ack(outcome, origin=action)
            return {"accepted": True, "reason": "ok", "action": action}
        # Registry-less (pure FSM tests still need first-wins on the thread).
        class _Fake:
            acked_by = by
            note = action

        self.record_ack(_Fake(), origin=action)
        return {"accepted": True, "reason": "ok", "action": action}

    def _begin_call(self, n: int) -> None:
        if self.escalation_stopped and n == 1 and self.state == "closed":
            return
        if self._call_announced >= n and self.state.startswith("calling_"):
            return
        self._call_announced = max(self._call_announced, n)
        state: BotState = "calling_1" if n <= 1 else ("calling_2" if n == 2 else "calling_3")
        self.state = state
        msg = _assert_copy(CALLING_TEXT.format(next=self.next_contact))
        result = self._send(msg, {})
        self._audit("call", msg, msg_id=str(result.get("msg_id") or ""))
        self.call_deadline_1 = self.now() + timedelta(seconds=120)

    def _close_with_docs(self, text: str) -> None:
        self.documentation = text
        msg = _assert_copy(CLOSE_CARD.format(docs=text))
        result = self._send(msg, {})
        self._audit("close", msg, msg_id=str(result.get("msg_id") or ""))
        self.state = "closed"

    def _send(self, text: str, extra: dict[str, Any]) -> dict[str, Any]:
        _assert_copy(text)
        if self.sender is None:
            return {
                "adapter": "stub",
                "channel": adapter_channel(self.channel),
                "delivered": True,
                "message": text,
            }
        try:
            return self.sender(text, extra)
        except TypeError:
            return self.sender(text)

    def _audit(self, message_kind: str, text: str, *, msg_id: str | None = None) -> None:
        self.audit.append(
            {
                "channel": adapter_channel(self.channel) if self.channel.endswith("_family") else self.channel,
                "chat_ref": self.chat_ref,
                "message_kind": message_kind,
                "text": _assert_copy(text),
                "msg_id": msg_id,
                "at": self.now().isoformat(),
            }
        )


@dataclass
class BotThreadRegistry:
    """Process-local household → thread map (one active conversation)."""

    now: Callable[[], datetime] = field(default=_utcnow)
    _threads: dict[str, BotThread] = field(default_factory=dict)

    def get(self, household_id: str) -> BotThread | None:
        return self._threads.get(household_id)

    def get_or_create(
        self,
        household_id: str,
        *,
        channel: str,
        chat_ref: str,
        members: list[dict[str, str]] | None = None,
        sender: Sender | None = None,
        dialer: StubDialer | None = None,
        ack_registry: AckRegistry | None = None,
    ) -> BotThread:
        existing = self._threads.get(household_id)
        if existing is not None:
            return existing
        thread = BotThread(
            household_id=household_id,
            channel=channel,
            chat_ref=chat_ref,
            members=list(members or []),
            now=self.now,
            sender=sender,
            dialer=dialer,
            ack_registry=ack_registry,
        )
        self._threads[household_id] = thread
        return thread

    def by_chat_ref(self, chat_ref: str) -> BotThread | None:
        for thread in self._threads.values():
            if thread.chat_ref == str(chat_ref):
                return thread
        return None

    def drop(self, household_id: str) -> None:
        self._threads.pop(household_id, None)


def token_for_callback(registry: AckRegistry, callback_id: str) -> str | None:
    if not callback_id:
        return None
    for row in registry.pending_list():
        token = str(row.get("token") or "")
        if token[:12] == callback_id or token.startswith(callback_id):
            return token
    return None


def dispatch_inbound(
    inbound,
    registry: AckRegistry,
    threads: BotThreadRegistry | None = None,
) -> dict[str, Any]:
    """Route a Telegram inbound (button or numbered reply) into thread + registry."""
    thread = threads.by_chat_ref(inbound.chat_ref) if threads is not None else None
    if thread is not None:
        if inbound.origin == "button" and inbound.action:
            return thread.handle_button(inbound.action, by=inbound.by, msg_ref=inbound.msg_ref)
        return thread.handle_inbound(inbound.text or "", by=inbound.by, msg_ref=inbound.msg_ref)
    token = token_for_callback(registry, getattr(inbound, "callback_id", None) or "")
    if token and inbound.action in {"ack", "call_now"}:
        outcome, reason = registry.acknowledge(
            token,
            by=inbound.by,
            channel="telegram",
            msg_ref=inbound.msg_ref,
            origin=inbound.origin,
        )
        return {"accepted": outcome is not None, "reason": reason}
    return {"accepted": False, "reason": "ignored"}
