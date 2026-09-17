"""Supervisor escalation adapter: Slack DM-style mention of the floor lead.

Extends NotifyChannelAdapter with supervisor addressing: display name plus
<@slack_user_id> mention when the supervisor has a Slack identity.
"""
from __future__ import annotations

from care_ladder.channels.notify import NotifyChannelAdapter


class NotifySupervisorAdapter(NotifyChannelAdapter):
    def __init__(self, supervisor=None, webhook_url: str | None = None) -> None:
        super().__init__(webhook_url=webhook_url)
        self._supervisor = supervisor

    def _compose(self, message: str) -> str:
        sup = self._supervisor
        if sup is None:
            return message
        name = getattr(sup, "display_name", "Supervisor")
        mention = ""
        slack_id = getattr(sup, "slack_user_id", None)
        if slack_id:
            mention = f" <@{slack_id}>"
        return f"{name}{mention}: {message}"

    def notify(self, message: str) -> dict:
        return super().notify(self._compose(message))
