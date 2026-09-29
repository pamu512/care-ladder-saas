"""P1 ack registry: chat-origin first-wins across button, numbered reply, link."""

from __future__ import annotations

from care_ladder.channels.ack import AckRegistry, parse_chat_reply


def _reg() -> AckRegistry:
    return AckRegistry(secret="family-ack")


def test_parse_chat_reply_maps_numbers_and_button_words():
    assert parse_chat_reply("1") == "ack"
    assert parse_chat_reply("1 - on it, calling her now") == "ack"
    assert parse_chat_reply("I'm on it. I'll call her myself") == "ack"
    assert parse_chat_reply("2") == "call_now"
    assert parse_chat_reply("Call Mom now") == "call_now"
    assert parse_chat_reply("3") == "pass"
    assert parse_chat_reply("Can't take it. Go to Sarah") == "pass"
    assert parse_chat_reply("she's fine - balcony again") is None


def test_chat_origin_ack_records_channel_and_msg_ref():
    reg = _reg()
    p = reg.create_pending("inc1", "page_family", "telegram", "page", 300, "https://x")
    outcome, reason = reg.acknowledge(
        p.token,
        by="James",
        channel="telegram",
        msg_ref="tg:77",
        origin="button",
    )
    assert reason == "ok" and outcome is not None
    assert outcome.channel == "telegram"
    assert outcome.msg_ref == "tg:77"
    assert outcome.origin == "button"
    summary = outcome.summary()
    assert summary["msg_ref"] == "tg:77"
    assert summary["origin"] == "button"


def test_first_wins_across_button_link_and_reply():
    reg = _reg()
    p = reg.create_pending("inc1", "page_family", "telegram", "page", 300, "https://x")
    first, r1 = reg.acknowledge(
        p.token, by="James", channel="telegram", msg_ref="btn-1", origin="button"
    )
    assert first is not None and r1 == "ok"
    link, r2 = reg.acknowledge(
        p.token, by="Sarah", channel="web", msg_ref=None, origin="link"
    )
    assert link is None and r2 == "already acknowledged"
    reply, r3 = reg.acknowledge(
        p.token, by="Neighbor", channel="telegram", msg_ref="txt-9", origin="reply"
    )
    assert reply is None and r3 == "already acknowledged"
    kept = reg.outcome_for("inc1", "page_family")
    assert kept is not None
    assert kept.acked_by == "James"
    assert kept.origin == "button"
    assert kept.msg_ref == "btn-1"
