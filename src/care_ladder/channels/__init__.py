"""Communication channels: speaker check-in, dial stubs, pages + acks."""

from care_ladder.channels.ack import AckOutcome, AckRegistry, PendingAck, render_ack_page
from care_ladder.channels.dial import DialResult, StubDialer, next_rung_after_no_answer
from care_ladder.channels.router import PageRouter
from care_ladder.channels.speaker import SpeakerChannel, SpeakerReply, SpeakerSimulator

__all__ = [
    "AckOutcome",
    "AckRegistry",
    "DialResult",
    "PageRouter",
    "PendingAck",
    "SpeakerChannel",
    "SpeakerReply",
    "SpeakerSimulator",
    "StubDialer",
    "next_rung_after_no_answer",
    "render_ack_page",
]
