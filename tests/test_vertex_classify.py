"""Task 1b: Vertex LLM reply classifier adapter (env-gated, offline-safe)."""
import pytest

from care_ladder.facility.classify import Classification, _llm_configured, classify_reply


def test_llm_configured_gate(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "VERTEX_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(var, raising=False)
    assert _llm_configured() is False
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/sa.json")
    assert _llm_configured() is True


def test_classify_uses_llm_when_configured(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/sa.json")

    import care_ladder.facility.classify as C

    def fake_llm(raw: str) -> Classification:
        return Classification("negative", "llm", "mocked vertex response")

    monkeypatch.setattr(C, "_llm_classify", fake_llm)
    got = classify_reply("I think maybe the floor is wet")
    assert got.reply_class == "negative" and got.source == "llm"


def test_llm_failure_falls_back_to_keywords(monkeypatch):
    """Vertex errors must degrade to keyword classification, never crash a run."""
    monkeypatch.setenv("VERTEX_PROJECT", "proj")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/sa.json")

    import care_ladder.facility.classify as C

    def boom(raw: str) -> Classification:
        raise RuntimeError("vertex unavailable")

    monkeypatch.setattr(C, "_llm_classify", boom)
    got = classify_reply("I need help")
    assert got.reply_class == "negative" and got.source == "keyword"


def test_vertex_adapter_builds_prompt_and_parses_json(monkeypatch):
    """The adapter posts a forced-JSON prompt and parses the enum out."""
    from care_ladder.facility.vertex_classify import parse_vertex_reply

    assert parse_vertex_reply('{"reply_class": "positive", "rationale": "fine"}') == (
        "positive",
        "fine",
    )
    # tolerant: code fences, extra keys, invalid enum -> None (caller falls back)
    assert parse_vertex_reply('```json\\n{"reply_class": "silence"}\\n```') == ("silence", "")
    assert parse_vertex_reply('{"reply_class": "banana"}') is None
    assert parse_vertex_reply("not json") is None
