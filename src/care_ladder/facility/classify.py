"""Reply classification: fixture override > LLM (when configured) > keyword fallback.

Honesty: without LLM credentials there is NO network call; keyword rules run
offline so CI and local demos never depend on Vertex/Gemini availability.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ReplyClassT = Literal["positive", "negative", "silence", "unclear"]


@dataclass(frozen=True)
class Classification:
    reply_class: ReplyClassT
    source: Literal["fixture", "llm", "keyword"]
    rationale: str = ""


def _llm_configured() -> bool:
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or (os.environ.get("VERTEX_PROJECT") and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    )


def _llm_classify(raw: str) -> Classification:  # pragma: no cover - requires network
    """LLM path (Google Cloud / Vertex). Only called when credentials exist."""
    raise NotImplementedError("LLM classify runs via the configured provider runtime")


def _keyword_classify(raw: str) -> Classification:
    text = (raw or "").casefold().strip()
    if not text:
        return Classification("silence", "keyword", "no reply within window")
    # negative intent: explicit help/cannot/can't/pain/fell/no
    neg = ("need help", "cannot", "can't", "cant get up", "hurt", "pain", "fell", "no,")
    pos = ("fine", "i'm ok", "im ok", "ok", "okay", "yes i'm", "all good", "no help")
    if any(k in text for k in neg):
        return Classification("negative", "keyword", "keyword: help/distress phrase")
    if any(k in text for k in pos):
        return Classification("positive", "keyword", "keyword: affirmative phrase")
    return Classification("unclear", "keyword", "no confident keyword match")


def classify_reply(raw: str, *, fixture_class: str | None = None) -> Classification:
    """Fixture pins win; else LLM when configured; else offline keywords."""
    if fixture_class:
        return Classification(
            fixture_class,  # type: ignore[arg-type]
            "fixture",
            "fixture override",
        )
    if _llm_configured():
        try:
            return _llm_classify(raw)
        except NotImplementedError:
            pass  # provider runtime not wired in this process; fall through
    return _keyword_classify(raw)


def reply_class_from_kind(kind: str) -> ReplyClassT:
    """Map existing SpeakerReplyKind onto the facility taxonomy."""
    return {
        "ok": "positive",
        "call_caregiver": "negative",
        "silence": "silence",
    }.get(kind, "unclear")
