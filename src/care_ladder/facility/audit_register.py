"""Audit register builder (UI polish Task 1): closed-case register rows + drill-down."""
from __future__ import annotations

from typing import Any

TOOL_LABELS = {
    "cue": "Cue",
    "speaker_prompt": "Voice check-in",
    "notify_supervisor": "Page group",
    "notify_and_await_ack": "Page caretakers",
    "notify_channel": "Page group",
    "wait": "Wait",
    "jump": "Ladder jump",
    "resolve": "Resolved",
    "dial_contact": "Call contact",
    "reperceive": "Re-check",
    "ack_timeout": "Ack window expired",
    "suppress": "Suppressed",
    "priority_override": "Priority override",
}

ORIGIN_MAP = {
    "from_negative_reply": ("negative", "negative reply"),
    "from_silence": ("silence", "silence"),
    "from_cue": ("cue", "cue"),
    "manual": ("manual", "manual"),
}


def _origin_pair(case) -> tuple[str, str]:
    return ORIGIN_MAP.get(case.origin, ("cue", case.origin))


def build_register(state, store) -> list[dict[str, Any]]:
    """Closed cases + resident-resolved incidents for today's register."""
    rows: list[dict[str, Any]] = []
    for c in state.cases.values():
        if c.state != "closed":
            continue
        owner = state.staff.get(c.owner_staff_id or "")
        opened = state._case_open_dt(c.id)
        ack_sec = (c.ack_at - opened).total_seconds() if (opened and c.ack_at) else None
        handling_sec = (c.closed_at - c.ack_at).total_seconds() if (c.ack_at and c.closed_at) else None
        origin_key, origin_label = _origin_pair(c)
        rows.append(
            {
                "kind": "staff_case",
                "incident_id": c.incident_id,
                "case_id": c.id,
                "human_id": c.human_id,
                "room_label": c.room_label,
                "title": c.title,
                "origin_key": origin_key,
                "origin_label": origin_label,
                "owner_display_name": owner.display_name if owner else None,
                "owner_initials": owner.initials if owner else None,
                "ack_sec": int(ack_sec) if ack_sec is not None else None,
                "handling_sec": int(handling_sec) if handling_sec is not None else None,
                "response_sec": None,
                "missed": ack_sec is not None and ack_sec > c.sla_ack_sec,
                "state": c.state,
                "priority": c.priority,
            }
        )
    # resident-resolved from incidents (positive reply_class)
    try:
        for inc in store.list_incidents():
            if inc.status != "resolved":
                continue
            sp = next((e for e in inc.events if e.tool == "speaker_prompt"), None)
            if sp is None or sp.detail.get("reply_class") != "positive":
                continue
            cue = inc.events[0] if inc.events else None
            cue_at = cue.at if (cue and cue.at) else None
            resp_sec = None
            if cue_at and sp.at:
                resp_sec = int(max(0, (sp.at - cue_at).total_seconds()))
            rows.append(
                {
                    "kind": "resident_resolved",
                    "incident_id": inc.id,
                    "case_id": None,
                    "human_id": f"inc {inc.id[:4]}",
                    "room_label": "204",
                    "title": "Resolved by resident response",
                    "origin_key": "resident",
                    "origin_label": "resolved by response",
                    "owner_display_name": None,
                    "owner_initials": None,
                    "ack_sec": None,
                    "handling_sec": None,
                    "response_sec": resp_sec,
                    "missed": False,
                    "state": "resolved",
                    "priority": None,
                }
            )
    except Exception:
        pass
    return rows


def _event_kind(tool: str) -> str:
    if tool.startswith("notify") or tool == "dial_contact":
        return "key"
    if tool in ("resolve", "suppress"):
        return "stop"
    if tool in ("jump", "priority_override", "ack_timeout"):
        return "jump"
    return "normal"


def build_register_detail(state, store, incident_id: str, case_out) -> dict[str, Any] | None:
    row = next((r for r in build_register(state, store) if r["incident_id"] == incident_id), None)
    if row is None:
        return None
    inc = store.get(incident_id)
    timeline: list[dict[str, Any]] = []
    prev_at = None
    if inc is not None:
        for e in inc.events:
            delta = None
            if e.at and prev_at:
                delta = int(max(0, (e.at - prev_at).total_seconds()))
            if e.at:
                prev_at = e.at
            timeline.append(
                {
                    "tool": e.tool,
                    "label": TOOL_LABELS.get(e.tool, e.tool.replace("_", " ").title()),
                    "detail": ", ".join(f"{k}={v}" for k, v in e.detail.items())[:140] if e.detail else "",
                    "quote": e.detail.get("reply") if isinstance(e.detail.get("reply"), str) else None,
                    "at": e.at.isoformat() if e.at else None,
                    "delta_sec": delta,
                    "kind": _event_kind(e.tool),
                }
            )
    case = None
    documentation = None
    doc_meta = None
    timing: dict[str, Any] = {"ack_sec": None, "ack_target_sec": 120,
                              "handling_sec": None, "handling_target_sec": 900,
                              "cue_to_page_sec": None, "nudges": 0, "nudge_response_sec": None}
    c = state.cases.get(row["case_id"]) if row["case_id"] else None
    if c is not None:
        case = case_out(c, state)
        documentation = c.documentation
        owner = state.staff.get(c.owner_staff_id or "")
        doc_meta = {
            "owner_display_name": owner.display_name if owner else None,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "via": "console",
        }
        timing["ack_sec"] = row["ack_sec"]
        timing["handling_sec"] = row["handling_sec"]
        timing["ack_target_sec"] = c.sla_ack_sec
        timing["handling_target_sec"] = c.sla_handling_sec
        first_page = next((e for e in (inc.events if inc else []) if e.tool.startswith("notify")), None)
        cue = inc.events[0] if inc and inc.events else None
        if first_page and cue and first_page.at and cue.at:
            timing["cue_to_page_sec"] = int(max(0, (first_page.at - cue.at).total_seconds()))
    if row["kind"] == "resident_resolved":
        timing["ack_sec"] = row["response_sec"]
        timing["ack_target_sec"] = 0  # response time displayed directly
    overrides = [o for o in state.overrides if o.get("case_id") == (row["case_id"] or "")] if row["case_id"] else []
    evidence = {
        "frame_count": len(getattr(inc, "frames", []) or []) if inc else 0,
        "privacy": (getattr(inc, "privacy_mode", None) if inc else None),
        "frame_urls": [],
        "slack_thread_url": c.slack_thread_url if c else None,
    }
    return {
        "row": row,
        "case": case,
        "timeline": timeline,
        "documentation": documentation,
        "documentation_meta": doc_meta,
        "timing": timing,
        "evidence": evidence,
        "overrides": overrides,
    }
