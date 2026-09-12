"""Nest/Alexa-style spoken check-in channel (simulator only for v1)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


SpeakerReplyKind = Literal["ok", "call_caregiver", "silence"]


@dataclass(frozen=True)
class SpeakerReply:
    kind: SpeakerReplyKind
    raw: str


@runtime_checkable
class SpeakerChannel(Protocol):
    async def prompt(self, text: str, wait_sec: float) -> SpeakerReply:
        """Speak ``text`` and wait up to ``wait_sec`` for a spoken reply."""
        ...


def classify_utterance(raw: str) -> SpeakerReplyKind:
    """Map a free-form reply to ok / call_caregiver / silence.

    Rules (case-insensitive substring):
    - contains call / yes call → call_caregiver
    - contains fine / ok / yes i'm → ok
    - else → silence
    """
    text = raw.casefold().strip()
    if not text:
        return "silence"
    # Prefer call intent when "call" is present (covers "yes call", "call Alex").
    if "call" in text:
        return "call_caregiver"
    if "fine" in text or "ok" in text or "yes i'm" in text or "yes i’m" in text:
        return "ok"
    return "silence"


class SpeakerSimulator:
    """Injectable scripted replies for Nest/Alexa-style check-in demos/tests.

    Empty queue or unmatched utterance after ``wait_sec`` → ``silence``.
    Real Nest/Alexa device integration is out of scope.
    """

    def __init__(self, scripted: Sequence[str] | None = None) -> None:
        self._queue: list[str] = list(scripted or [])

    async def prompt(self, text: str, wait_sec: float) -> SpeakerReply:
        _ = text  # spoken prompt; real devices would TTS this
        if self._queue:
            raw = self._queue.pop(0)
            kind = classify_utterance(raw)
            return SpeakerReply(kind=kind, raw=raw)
        await asyncio.sleep(max(0.0, wait_sec))
        return SpeakerReply(kind="silence", raw="")
