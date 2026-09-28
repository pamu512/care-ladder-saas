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


def _llm_classify(raw: str) -> Classification | None:
    """LLM path (Google Cloud / Vertex). Only called when credentials exist.

    Returns None on any failure (SDK missing, transport, unparseable) so the
    caller falls back to keywords; never raises into a run.
    """
    from care_ladder.facility.vertex_classify import vertex_classify

    return vertex_classify(raw)


def _keyword_classify(raw: str) -> Classification:
    text = (raw or "").casefold().strip()
    if not text:
        return Classification("silence", "keyword", "no reply within window")
    # Negation guard FIRST: negated distress phrases must never page P1.
    negations = (
        "don't need", "dont need", "do not need", "not need",
        "no need", "not pain", "not hurt", "not feeling pain",
        "not sick", "not dizzy", "no pain", "no hurt",
        "don't want help", "dont want help", "not calling",
    )
    if any(n in text for n in negations):
        return Classification("positive", "keyword", "keyword: negated distress phrase")
    # negative intent: explicit help/cannot/pain/fell (word-ish boundaries)
    neg = ("need help", "cannot get up", "can't get up", "cant get up", "hurt",
           "in pain", "i fell", "have fallen", "help me", "i'm falling", "call for help")
    pos = ("fine", "i'm ok", "im ok", "okay", "all good", "yes i'm", "doing well")
    if any(k in text for k in neg):
        return Classification("negative", "keyword", "keyword: help/distress phrase")
    if any(k in text for k in pos):
        return Classification("positive", "keyword", "keyword: affirmative phrase")
    if text in ("ok", "yes", "no") or text.startswith(("ok ", "yes,", "no,")) and "help" not in text:
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
            result = _llm_classify(raw)
        except Exception:
            result = None  # provider failures never crash a run
        if result is not None:
            return result
    return _keyword_classify(raw)


def reply_class_from_kind(kind: str) -> ReplyClassT:
    """Map existing SpeakerReplyKind onto the facility taxonomy."""
    return {
        "ok": "positive",
        "call_caregiver": "negative",
        "silence": "silence",
    }.get(kind, "unclear")
