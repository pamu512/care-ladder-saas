"""Communication channels: speaker check-in, dial stubs, pages + acks."""

from care_ladder.channels.ack import AckOutcome, AckRegistry, PendingAck, parse_chat_reply, render_ack_page
from care_ladder.channels.bot import BotThread, BotThreadRegistry
from care_ladder.channels.dial import DialResult, StubDialer, next_rung_after_no_answer
from care_ladder.channels.router import PageRouter, telegram_mode
from care_ladder.channels.speaker import SpeakerChannel, SpeakerReply, SpeakerSimulator

__all__ = [
    "AckOutcome",
    "AckRegistry",
    "BotThread",
    "BotThreadRegistry",
    "DialResult",
    "PageRouter",
    "PendingAck",
    "SpeakerChannel",
    "SpeakerReply",
    "SpeakerSimulator",
    "StubDialer",
    "next_rung_after_no_answer",
    "parse_chat_reply",
    "render_ack_page",
    "telegram_mode",
]
