"""Caretaker acknowledgment registry: signed capability tokens + wait loop.

The registry backs the ``notify_and_await_ack`` rung: when the ladder pages
floor staff, it creates a *pending acknowledgment* bound to the incident and
rung, delivers a signed one-tap link over the notify channel, and waits for
``POST /acks/{token}`` (Slack/Teams/WhatsApp/Telegram link tap, or the
console's Acknowledge button) before escalating.

Honesty notes (MVP):
- Process-local state (same honesty note as the upload-job map): a restart
  clears pending acks. Tokens are signed with ``SESSION_SECRET`` when set,
  otherwise a random per-process secret, so stale links fail closed after a
  restart instead of being replayable forever.
- Tokens are capability URLs: possession == authorization to acknowledge.
  They expire with the rung's ack window (+ grace) and are single-use.
"""

from __future__ import annotations

import asyncio
import html
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

AckChannel = Literal["slack", "teams", "whatsapp", "telegram", "web", "call"]
AckAction = Literal["ack", "call_now", "pass"]

# Numbered-reply / button-word map used in the open family chat window.
_REPLY_ACK = frozenset({"1", "ack", "on it", "im on it", "i'm on it"})
_REPLY_CALL = frozenset({"2", "call", "call now", "call mom", "call mom now"})
_REPLY_PASS = frozenset({"3", "pass", "cant", "can't", "go to"})

# Extra slack after the ack deadline before a token is fully invalid, so a
# caretaker opening the page right at the deadline can still record the ack.
_GRACE_SEC = 60.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PendingAck:
    incident_id: str
    rung_id: str
    channel: str
    message: str
    created_at: datetime
    deadline: datetime
    token: str
    ack_url: str
    tenant_id: str | None = None  # set by the API layer for tenant-scoped views

    def summary(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "incident_id": self.incident_id,
            "rung_id": self.rung_id,
            "channel": self.channel,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
            "deadline": self.deadline.isoformat(),
            "ack_url": self.ack_url,
        }


@dataclass(frozen=True)
class AckOutcome:
    token: str
    incident_id: str
    rung_id: str
    channel: str
    acked_by: str | None
    note: str | None
    acked_at: datetime
    msg_ref: str | None = None
    origin: str | None = None

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "token": self.token,
            "incident_id": self.incident_id,
            "rung_id": self.rung_id,
            "channel": self.channel,
            "acked_by": self.acked_by,
            "note": self.note,
            "acked_at": self.acked_at.isoformat(),
        }
        if self.msg_ref is not None:
            out["msg_ref"] = self.msg_ref
        if self.origin is not None:
            out["origin"] = self.origin
        return out


def parse_chat_reply(text: str) -> AckAction | None:
    """Map ``1|2|3`` or button words to ack / call_now / pass. None if free text."""
    raw = (text or "").strip().casefold()
    if not raw:
        return None
    # Leading numeral wins ("1 - on it, calling her now").
    first = raw.split()[0].rstrip(".)-:;")
    if first == "1":
        return "ack"
    if first == "2":
        return "call_now"
    if first == "3":
        return "pass"
    if raw in _REPLY_ACK or raw.startswith("i'm on it") or raw.startswith("im on it") or raw.startswith("on it"):
        return "ack"
    if raw in _REPLY_CALL or raw.startswith("call mom"):
        return "call_now"
    if raw in _REPLY_PASS or raw.startswith("can't take") or raw.startswith("cant take") or raw.startswith("go to"):
        return "pass"
    return None


@dataclass
class _AutoAck:
    incident_id: str
    after_sec: float
    by: str
    channel: str
    note: str | None
    task: asyncio.Task | None = field(default=None, repr=False)


class AckRegistry:
    """Thread-safe, process-local pending/outcome store for caretaker acks."""

    def __init__(self, *, secret: str | None = None, now: Callable[[], datetime] = _utcnow) -> None:
        self._now = now
        self._secret = secret or self._default_secret()
        self._serializer = URLSafeTimedSerializer(self._secret, salt="care-ladder-ack")
        self._lock = threading.Lock()
        self._pending_by_token: dict[str, PendingAck] = {}
        self._pending_by_incident: dict[tuple[str, str], PendingAck] = {}
        self._outcomes_by_token: dict[str, AckOutcome] = {}
        self._auto_acks: list[_AutoAck] = []

    @staticmethod
    def _default_secret() -> str:
        import os

        env = os.environ.get("SESSION_SECRET", "")
        if env:
            return env
        # Random per-process secret: pending state dies with the process, so
        # token validity dying with it is the consistent (fail-closed) choice.
        return secrets.token_urlsafe(32)

    # ---- pending lifecycle -------------------------------------------------

    def create_pending(
        self,
        incident_id: str,
        rung_id: str,
        channel: str,
        message: str,
        timeout_sec: float,
        base_url: str,
        *,
        created_at: datetime | None = None,
    ) -> PendingAck:
        now = created_at or self._now()
        deadline = now + timedelta(seconds=max(1.0, float(timeout_sec)))
        ttl = int(max(1.0, float(timeout_sec)) + _GRACE_SEC)
        token = self._serializer.dumps(
            {"i": incident_id, "r": rung_id, "c": channel, "ttl": ttl}
        )
        pending = PendingAck(
            incident_id=incident_id,
            rung_id=rung_id,
            channel=channel,
            message=message,
            created_at=now,
            deadline=deadline,
            token=token,
            ack_url=f"{base_url.rstrip('/')}/ack/{token}",
        )
        with self._lock:
            self._pending_by_token[token] = pending
            self._pending_by_incident[(incident_id, rung_id)] = pending
        self._fire_auto_acks_locked_free(incident_id)
        return pending

    def peek(self, token: str) -> PendingAck | None:
        """Pending entry for a still-valid, un-consumed token (no state change)."""
        with self._lock:
            return self._pending_by_token.get(token)

    def close_pending(self, incident_id: str, rung_id: str, *, reason: str) -> PendingAck | None:
        """Remove a pending window without recording an ack (e.g. ladder timed out)."""
        with self._lock:
            pending = self._pending_by_incident.pop((incident_id, rung_id), None)
            if pending is not None:
                self._pending_by_token.pop(pending.token, None)
            return pending

    def pending_list(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """All pending summaries, or only those for one tenant when given."""
        now = self._now()
        out: list[dict[str, Any]] = []
        with self._lock:
            stale: list[str] = []
            for token, p in self._pending_by_token.items():
                if p.deadline <= now:
                    stale.append(token)
                    continue
                if tenant_id is None or p.tenant_id in (None, tenant_id):
                    out.append(p.summary())
            for token in stale:
                p = self._pending_by_token.pop(token)
                self._pending_by_incident.pop((p.incident_id, p.rung_id), None)
        out.sort(key=lambda s: s["created_at"])
        return out

    # ---- acknowledging -----------------------------------------------------

    def acknowledge(
        self,
        token: str,
        *,
        by: str | None = None,
        note: str | None = None,
        channel: str = "web",
        msg_ref: str | None = None,
        origin: str | None = None,
    ) -> tuple[AckOutcome | None, str]:
        """Record an ack for a signed token. Returns (outcome, reason).

        First writer wins: a later button / numbered reply / ack-link for the
        same token returns ``already acknowledged``.
        """
        now = self._now()
        try:
            payload = self._serializer.loads(token)
        except SignatureExpired:
            return None, "token expired"
        except BadSignature:
            return None, "invalid token signature"
        if not isinstance(payload, dict):
            return None, "malformed token"

        with self._lock:
            pending = self._pending_by_token.get(token)
            if pending is None:
                if token in self._outcomes_by_token:
                    return None, "already acknowledged"
                return None, "unknown or closed acknowledgment"
            if now > pending.deadline + timedelta(seconds=_GRACE_SEC):
                return None, "ack window closed"
            self._pending_by_token.pop(token, None)
            self._pending_by_incident.pop((pending.incident_id, pending.rung_id), None)
            outcome = AckOutcome(
                token=token,
                incident_id=pending.incident_id,
                rung_id=pending.rung_id,
                channel=channel,
                acked_by=by,
                note=note,
                acked_at=now,
                msg_ref=msg_ref,
                origin=origin,
            )
            self._outcomes_by_token[token] = outcome
        return outcome, "ok"

    def outcome_for(self, incident_id: str, rung_id: str) -> AckOutcome | None:
        with self._lock:
            for outcome in self._outcomes_by_token.values():
                if outcome.incident_id == incident_id and outcome.rung_id == rung_id:
                    return outcome
        return None

    # ---- waiting (orchestrator side) ----------------------------------------

    async def wait_for_ack(
        self,
        incident_id: str,
        rung_id: str,
        timeout_sec: float,
        *,
        poll_sec: float = 0.25,
    ) -> AckOutcome | None:
        """Await an ack for up to ``timeout_sec``; None on timeout."""
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while True:
            outcome = self.outcome_for(incident_id, rung_id)
            if outcome is not None:
                return outcome
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(poll_sec, remaining))

    # ---- scripted acks (demos / tests) --------------------------------------

    def schedule_auto_ack(
        self,
        incident_id: str,
        *,
        after_sec: float,
        by: str,
        channel: str = "slack",
        note: str | None = None,
        max_wait_pending_sec: float = 30.0,
    ) -> bool:
        """Arm a scripted caretaker ack (same spirit as SpeakerSimulator lines).

        Waits ``after_sec``, then polls until the incident's pending window
        exists, then acknowledges it. Runs as a task on the current event loop
        so it interleaves with ``run_incident``'s bounded wait.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        async def _task() -> None:
            await asyncio.sleep(max(0.0, after_sec))
            give_up = time.monotonic() + max_wait_pending_sec
            while time.monotonic() < give_up:
                with self._lock:
                    pending = next(
                        (
                            p
                            for p in self._pending_by_token.values()
                            if p.incident_id == incident_id
                        ),
                        None,
                    )
                if pending is not None:
                    self.acknowledge(pending.token, by=by, note=note, channel=channel)
                    return
                await asyncio.sleep(0.02)

        auto = _AutoAck(
            incident_id=incident_id,
            after_sec=after_sec,
            by=by,
            channel=channel,
            note=note,
            task=loop.create_task(_task()),
        )
        with self._lock:
            self._auto_acks.append(auto)
        return True

    def _fire_auto_acks_locked_free(self, incident_id: str) -> None:
        # Auto acks poll for pending entries themselves; nothing to push.
        _ = incident_id


def render_ack_page(pending: PendingAck | None, *, status_note: str = "") -> str:
    """Minimal mobile-first confirm page served at ``GET /ack/{token}``.

    One tap posts to ``/acks/{token}``; the signed token is the capability
    (no console session required for caretakers arriving from IM links).
    """
    if pending is None:
        body = f"""
        <h1>Link unavailable</h1>
        <p class="meta">{html.escape(status_note or 'This acknowledgment link is invalid, expired, or already used.')}</p>
        <p class="meta">If a resident still needs help, contact the floor supervisor directly.</p>
        """
        button = ""
    else:
        msg = html.escape(pending.message)
        short_id = html.escape(pending.incident_id[:10])
        dl = html.escape(pending.deadline.strftime("%H:%M UTC"))
        body = f"""
        <h1>Acknowledgment requested</h1>
        <p class="msg">{msg}</p>
        <p class="meta">incident {short_id} · respond by {dl}</p>
        """
        button = '<button id="ack">&#10003; I&#8217;m on it</button><p class="state" id="state"></p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Care Ladder: Acknowledge</title>
<style>
  :root {{ --fg:#0f172a; --muted:#64748b; --accent:#0e7490; --border:#e2e8f0; --ok:#15803d; --bad:#b91c1c; }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px;
         background:#f8fafc; color:var(--fg); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .card {{ background:#fff; border:1px solid var(--border); border-radius:16px; padding:28px 24px; max-width:420px; width:100%;
          box-shadow:0 1px 3px rgba(15,23,42,.06); text-align:center; }}
  .brand {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); font-weight:700; margin-bottom:14px; }}
  h1 {{ font-size:20px; margin-bottom:10px; }}
  .msg {{ font-size:15px; margin-bottom:6px; }}
  .meta {{ font-size:12.5px; color:var(--muted); margin-bottom:18px; }}
  button {{ width:100%; border:0; border-radius:10px; background:var(--accent); color:#fff; font-size:16px; font-weight:600;
           padding:14px; cursor:pointer; }}
  button:hover {{ filter:brightness(1.07); }}
  button:disabled {{ opacity:.5; cursor:default; }}
  .state {{ font-size:13.5px; margin-top:14px; min-height:20px; color:var(--ok); }}
  .state.err {{ color:var(--bad); }}
</style>
</head>
<body>
  <div class="card">
    <div class="brand">Care Ladder</div>
    {body}
    {button}
  </div>
<script>
const token = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
const btn = document.getElementById("ack");
if (btn) btn.addEventListener("click", async () => {{
  btn.disabled = true;
  const st = document.getElementById("state");
  try {{
    const r = await fetch("/acks/" + encodeURIComponent(token), {{
      method: "POST",
      headers: {{"content-type": "application/json"}},
      body: JSON.stringify({{ by: "caretaker (ack link)" }})
    }});
    const b = await r.json().catch(() => ({{}}));
    if (r.ok) {{
      st.textContent = "\\u2713 Recorded. Thank you. The escalation ladder has stopped for this incident.";
      st.classList.remove("err");
    }} else {{
      st.textContent = "\\u26a0 " + (b.detail || "could not record acknowledgment");
      st.classList.add("err");
      btn.disabled = false;
    }}
  }} catch (e) {{
    st.textContent = "\\u26a0 " + e.message;
    st.classList.add("err");
    btn.disabled = false;
  }}
}});
</script>
</body>
</html>"""
