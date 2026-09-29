"""Multi-channel page router: Slack / Teams / WhatsApp / Telegram.

One routing surface for caretaker pages. Each channel follows the repo's
honesty convention: real HTTP delivery only when that channel's credentials
are present in the environment; otherwise the result records
``adapter: stub`` so the audit trail never claims a delivery that did not
happen.

All adapters return a ``dict`` result shaped like ``NotifyChannelAdapter``:
``{adapter, channel, delivered, message, ...}`` so the orchestrator/audit
trail stays uniform.

Bot-API notes (MVP, honest):
- Slack: incoming webhook (existing surface). Supervisor mentions stay in
  ``NotifySupervisorAdapter`` (``<@U...>`` composed before routing).
- Teams: Workflows "when a webhook request is received" URL posts JSON
  ``{"text": ...}`` (same shape as legacy O365 connectors).
- WhatsApp / Telegram: Bot-API style send-message POSTs to a known chat id.
  WhatsApp Cloud API requires an approved template for business-initiated
  messages outside a 24h reply window; this MVP sends plain text and records
  failures honestly instead of retry loops.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT = 10.0

ChannelId = str  # "slack" | "teams" | "whatsapp" | "telegram"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def telegram_mode() -> str:
    """``TELEGRAM_MODE=poll|hook``. Default poll (demo). hook is the production path."""
    mode = _env("TELEGRAM_MODE").lower()
    if mode in {"hook", "webhook"}:
        return "hook"
    return "poll"


def telegram_inline_keyboard(
    buttons: list[tuple[str, str]],
    callback_id: str,
) -> dict[str, Any]:
    """Telegram ``reply_markup`` for an alert card. ``callback_data`` stays under 64 bytes."""
    cid = (callback_id or "x")[:24]
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": f"cl:{action}:{cid}"}]
            for action, label in buttons
        ]
    }


@dataclass(frozen=True)
class TelegramInbound:
    action: str | None
    callback_id: str | None
    msg_ref: str
    by: str | None
    chat_ref: str
    origin: str
    text: str = ""


def _post_sync(fn, message: str) -> dict[str, Any]:
    """Run the async post in a fresh loop / worker thread (tests + ladder)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, fn(message)).result()
    return asyncio.run(fn(message))


def _result(
    channel: str,
    delivered: bool,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "adapter": channel,
        "channel": channel,
        "delivered": delivered,
        "message": message,
    }
    out.update(extra)
    return out


class _UnknownChannelStub:
    """Honest stub for channel ids with no configured adapter."""

    def __init__(self, channel_id: str) -> None:
        self.id = channel_id

    def notify(self, message: str) -> dict[str, Any]:
        return {
            "adapter": "stub",
            "channel": self.id,
            "delivered": False,
            "error": f"unknown channel {self.id!r}; no adapter configured",
            "message": message,
        }


class _WebhookAdapter:
    """Shared implementation for ``{"text": ...}`` webhook channels."""

    id = "webhook"
    env_name = ""

    def __init__(self, webhook_url: str | None = None) -> None:
        self._webhook_url = webhook_url or _env(self.env_name)

    def _stub(self, message: str) -> dict[str, Any]:
        # Honesty convention (repo-wide): no credentials → adapter "stub" in audit.
        return {
            "adapter": "stub",
            "channel": self.id,
            "delivered": True,
            "message": message,
        }

    async def _send(self, message: str) -> dict[str, Any]:
        import httpx2 as httpx

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(self._webhook_url, json={"text": message})
        return _result(
            self.id,
            delivered=resp.status_code in (200, 201, 202, 204),
            message=message,
            status_code=resp.status_code,
        )

    def notify(self, message: str) -> dict[str, Any]:
        if not self._webhook_url:
            return self._stub(message)
        try:
            return _post_sync(self._send, message)
        except Exception as exc:  # network errors never break the ladder
            return _result(self.id, delivered=False, message=message, error=str(exc))


class SlackAdapter(_WebhookAdapter):
    id = "slack"
    env_name = "SLACK_WEBHOOK_URL"


class TeamsAdapter(_WebhookAdapter):
    id = "teams"
    env_name = "TEAMS_WEBHOOK_URL"


class TelegramAdapter:
    """Telegram Bot API ``sendMessage`` page (env: bot token + chat id).

    v2: optional inline keyboard on family alert cards. Without token+chat_id
    every send stays an honest stub. Inbound updates (poll or webhook) parse
    into ``TelegramInbound`` and first-wins the ack registry.
    """

    id = "telegram"

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        self._token = bot_token or _env("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or _env("TELEGRAM_CHAT_ID")

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def _stub(self, message: str) -> dict[str, Any]:
        return {
            "adapter": "stub",
            "channel": "telegram",
            "delivered": True,
            "message": message,
        }

    async def _send(self, message: str, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx2 as httpx

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        ok = resp.status_code == 200
        error = None
        msg_id = None
        if not ok:
            try:
                error = str(resp.json().get("description", ""))
            except Exception:
                error = f"status {resp.status_code}"
        else:
            try:
                msg_id = str((resp.json().get("result") or {}).get("message_id") or "") or None
            except Exception:
                msg_id = None
        return _result(
            "telegram",
            delivered=ok,
            message=message,
            status_code=resp.status_code,
            error=error,
            msg_id=msg_id,
        )

    def notify(self, message: str, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            return self._stub(message)
        try:
            if reply_markup is None:
                return _post_sync(self._send, message)
            return _post_sync(lambda m: self._send(m, reply_markup), message)
        except Exception as exc:  # network errors never break the ladder
            return _result("telegram", delivered=False, message=message, error=str(exc))

    def notify_alert(
        self,
        message: str,
        *,
        callback_id: str,
        next_contact: str = "Sarah",
    ) -> dict[str, Any]:
        from care_ladder.channels.bot import family_alert_buttons

        markup = telegram_inline_keyboard(family_alert_buttons(next_contact), callback_id)
        return self.notify(message, reply_markup=markup)

    @staticmethod
    def parse_update(update: dict[str, Any]) -> TelegramInbound | None:
        """Turn a Bot API update into an inbound ack/reply, or None if irrelevant."""
        from care_ladder.channels.ack import parse_chat_reply

        if not isinstance(update, dict):
            return None
        cq = update.get("callback_query")
        if isinstance(cq, dict):
            data = str(cq.get("data") or "")
            action = None
            callback_id = None
            if data.startswith("cl:"):
                rest = data[3:]
                action, _, callback_id = rest.partition(":")
                action = action or None
                callback_id = callback_id or None
            msg = cq.get("message") if isinstance(cq.get("message"), dict) else {}
            from_user = cq.get("from") if isinstance(cq.get("from"), dict) else {}
            chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
            return TelegramInbound(
                action=action,
                callback_id=callback_id,
                msg_ref=str(msg.get("message_id") or cq.get("id") or ""),
                by=str(from_user.get("first_name") or from_user.get("username") or "") or None,
                chat_ref=str(chat.get("id") or ""),
                origin="button",
                text=data,
            )
        message = update.get("message")
        if isinstance(message, dict):
            text = str(message.get("text") or "")
            if not text:
                return None
            from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
            chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
            return TelegramInbound(
                action=parse_chat_reply(text),
                callback_id=None,
                msg_ref=str(message.get("message_id") or ""),
                by=str(from_user.get("first_name") or from_user.get("username") or "") or None,
                chat_ref=str(chat.get("id") or ""),
                origin="reply",
                text=text,
            )
        return None

    def ack_from_inbound(
        self,
        inbound: TelegramInbound,
        registry: Any,
        *,
        token: str,
    ) -> tuple[Any, str]:
        return registry.acknowledge(
            token,
            by=inbound.by,
            channel="telegram",
            msg_ref=inbound.msg_ref,
            origin=inbound.origin,
        )

    async def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        """Long-poll ``getUpdates``. Caller must be configured; errors return []."""
        if not self.configured:
            return []
        import httpx2 as httpx

        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        try:
            async with httpx.AsyncClient(timeout=float(timeout) + 5.0) as client:
                resp = await client.get(
                    url,
                    params={"offset": offset, "timeout": timeout},
                )
            body = resp.json()
            if not body.get("ok"):
                return []
            result = body.get("result") or []
            return list(result) if isinstance(result, list) else []
        except Exception:
            return []

    def set_webhook(self, hook_url: str) -> dict[str, Any]:
        if not self.configured or not hook_url:
            return {"adapter": "stub", "delivered": False, "error": "missing token or hook url"}
        import httpx2 as httpx

        url = f"https://api.telegram.org/bot{self._token}/setWebhook"

        async def _set(_message: str) -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json={"url": hook_url})
            ok = resp.status_code == 200
            return _result("telegram", delivered=ok, message=hook_url, status_code=resp.status_code)

        try:
            return _post_sync(_set, hook_url)
        except Exception as exc:
            return _result("telegram", delivered=False, message=hook_url, error=str(exc))


class WhatsAppAdapter:
    """WhatsApp Cloud API text page (env: token, phone id, to number).

    Demo honesty: ``to`` must be a reserved NANP 555-01XX fiction number in
    demo mode; real sends require a WhatsApp Business account, an approved
    template for business-initiated messages, and an opted-in recipient.
    """

    id = "whatsapp"

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        to: str | None = None,
    ) -> None:
        self._token = access_token or _env("WHATSAPP_TOKEN")
        self._phone_id = phone_number_id or _env("WHATSAPP_PHONE_NUMBER_ID")
        self._to = to or _env("WHATSAPP_TO")

    async def _send(self, message: str) -> dict[str, Any]:
        import httpx2 as httpx

        url = f"https://graph.facebook.com/v20.0/{self._phone_id}/messages"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": self._to,
                    "type": "text",
                    "text": {"preview_url": False, "body": message},
                },
            )
        ok = resp.status_code == 200
        error = None
        if not ok:
            try:
                error = str(resp.json().get("error", {}).get("message", ""))
            except Exception:
                error = f"status {resp.status_code}"
        return _result(
            "whatsapp",
            delivered=ok,
            message=message,
            status_code=resp.status_code,
            error=error,
        )

    def notify(self, message: str) -> dict[str, Any]:
        if not (self._token and self._phone_id and self._to):
            return {
                "adapter": "stub",
                "channel": "whatsapp",
                "delivered": True,
                "message": message,
            }
        try:
            return _post_sync(self._send, message)
        except Exception as exc:  # network errors never break the ladder
            return _result("whatsapp", delivered=False, message=message, error=str(exc))


class PageRouter:
    """Route one page to a channel adapter chosen by plan config or env."""

    def __init__(self, channels: dict[ChannelId, Any] | None = None) -> None:
        self._channels: dict[ChannelId, Any] = dict(channels or {})
        for default in (SlackAdapter, TeamsAdapter, TelegramAdapter, WhatsAppAdapter):
            if default.id not in self._channels:
                self._channels[default.id] = default()

    def get(self, channel_id: ChannelId):
        adapter = self._channels.get(channel_id)
        if adapter is not None:
            return adapter
        # Unknown channel id: route to a plain honest stub, never raise.
        return _UnknownChannelStub(channel_id)


def channel_active_envs() -> list[str]:
    """Human-readable list of channels with credentials present (for UI)."""
    active: list[str] = []
    checks = (
        ("slack", ("SLACK_WEBHOOK_URL",)),
        ("teams", ("TEAMS_WEBHOOK_URL",)),
        ("telegram", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")),
        ("whatsapp", ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TO")),
    )
    for cid, names in checks:
        if all(_env(n) for n in names):
            active.append(cid)
    return active
