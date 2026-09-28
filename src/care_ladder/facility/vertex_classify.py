"""Vertex LLM adapter for reply classification (env-gated).

Uses the Google GenAI SDK when installed and credentials are configured.
The prompt forces a JSON enum response; any parse/transport failure returns
None so the caller falls back to keyword classification (never crashes a run).
"""
from __future__ import annotations

import json
import os
import re

VALID = {"positive", "negative", "silence", "unclear"}

PROMPT = (
    "You classify an elderly resident's reply to a check-in speaker. "
    "Reply with JSON only: {\"reply_class\": \"positive|negative|silence|unclear\", "
    "\"rationale\": \"<short reason>\"}. "
    "positive = resident is fine; negative = resident needs help or reports "
    "distress; silence = no reply; unclear = cannot tell. "
    "Resident reply: {reply!r}"
)


def parse_vertex_reply(text: str) -> tuple[str, str] | None:
    """Extract (reply_class, rationale) from a model response; None if unusable."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    reply_class = data.get("reply_class")
    if reply_class not in VALID:
        return None
    return reply_class, str(data.get("rationale", ""))


def vertex_classify(raw: str):  # pragma: no cover - needs GCP credentials
    """Call Vertex/Gemini. Returns Classification or None on any failure."""
    project = os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        return None
    try:
        from google import genai  # type: ignore

        model = os.environ.get("VERTEX_REPLY_MODEL", "gemini-2.0-flash")
        client = genai.Client(vertexai=True, project=project,
                              location=os.environ.get("VERTEX_LOCATION", "global"))
        resp = client.models.generate_content(model=model, contents=PROMPT.format(reply=raw))
        parsed = parse_vertex_reply(resp.text or "")
        if parsed is None:
            return None
        from care_ladder.facility.classify import Classification

        return Classification(parsed[0], "llm", parsed[1])
    except Exception:
        return None  # transport/quota/SDK failures degrade to keyword fallback
