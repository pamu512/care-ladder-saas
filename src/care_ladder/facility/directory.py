"""Read-only People / Places / Channels rows for the facility console.

Seeded from demo plans + fixture subjects already used by /demo/run.
Live status comes from open cases, resident-resolved rows, and audit events.
No invented delivery metrics, camera ids, check-in counts, or pendants.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from care_ladder.models import CarePlan

_REPO = Path(__file__).resolve().parents[3]
_PLAN_BY_TYPE = {
    "assisted_living": _REPO / "configs" / "demo_facility.yaml",
    "old_age_home": _REPO / "configs" / "demo_facility.yaml",
    "daycare_kids": _REPO / "configs" / "demo_daycare.yaml",
    "rehab": _REPO / "configs" / "demo_rehab.yaml",
}

_SUBJECT_SEEDS: dict[str, list[dict[str, str]]] = {
    "assisted_living": [
        {
            "id": "res-204",
            "display_name": "Margaret Hale",
            "kind": "resident",
            "place_label": "204",
            "room_label": "204",
        }
    ],
    "old_age_home": [
        {
            "id": "res-204",
            "display_name": "Margaret Hale",
            "kind": "resident",
            "place_label": "204",
            "room_label": "204",
        }
    ],
    "daycare_kids": [
        {
            "id": "child-nk-1",
            "display_name": "Nora Kim",
            "kind": "child",
            "place_label": "Classroom 1",
            "room_label": "classroom_1",
        }
    ],
    "rehab": [
        {
            "id": "pt-dp-4",
            "display_name": "Dana Patel",
            "kind": "patient",
            "place_label": "Gym",
            "room_label": "gym",
        }
    ],
}

_CHANNEL_CATALOG = (
    {"id": "slack", "label": "Slack", "tile": "S"},
    {"id": "teams", "label": "Microsoft Teams", "tile": "T"},
    {"id": "whatsapp", "label": "WhatsApp", "tile": "W"},
    {"id": "telegram", "label": "Telegram", "tile": "TG"},
)

_ORIGIN_RESPONSE = {
    "from_negative_reply": "negative",
    "from_silence": "silence",
}

_PAGE_TOOLS = frozenset({"notify_and_await_ack", "notify_channel", "notify_supervisor"})


def plan_for_type(facility_type: str) -> Path:
    return _PLAN_BY_TYPE.get(facility_type) or _PLAN_BY_TYPE["assisted_living"]


def seed_people(facility_type: str) -> list[dict[str, str]]:
    rows = _SUBJECT_SEEDS.get(facility_type) or _SUBJECT_SEEDS["assisted_living"]
    return [dict(r) for r in rows]


def _humanize(raw: str) -> str:
    text = (raw or "").replace("_", " ").strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _person_key(row: dict[str, Any]) -> str:
    sid = (row.get("id") or row.get("subject_id") or "").strip()
    name = (row.get("display_name") or row.get("subject_display_name") or "").strip().lower()
    if sid:
        return f"id:{sid}"
    return f"name:{name}"


def _find_person(merged: dict[str, dict[str, Any]], row: dict[str, Any]) -> str | None:
    key = _person_key(row)
    if key in merged:
        return key
    name = (row.get("display_name") or "").strip().lower()
    if not name:
        return None
    for existing_key, existing in merged.items():
        if (existing.get("display_name") or "").strip().lower() == name:
            return existing_key
    return None


def _status_rank(status: str) -> int:
    return {"incident open": 3, "case open": 2, "ok": 1, "no incidents": 0}.get(status, 0)


def _case_person_status(case) -> str:
    if case.state == "closed":
        return "ok" if case.origin == "from_cue" else "no incidents"
    if case.state == "paged" and not case.ack_at:
        return "incident open"
    return "case open"


def build_people(state, *, facility_type: str) -> list[dict[str, Any]]:
    """Merge type seed + live case/resolved subjects. Honest columns only."""
    merged: dict[str, dict[str, Any]] = {}

    def upsert(row: dict[str, Any]) -> None:
        key = _find_person(merged, row) or _person_key(row)
        if not key or key.endswith(":"):
            return
        cur = merged.get(key)
        if cur is None:
            merged[key] = row
            return
        if _status_rank(row.get("status") or "") >= _status_rank(cur.get("status") or ""):
            if row.get("place_label"):
                cur["place_label"] = row["place_label"]
            if row.get("last_response"):
                cur["last_response"] = row["last_response"]
            if row.get("status"):
                cur["status"] = row["status"]
            if row.get("kind"):
                cur["kind"] = row["kind"]
            if row.get("id"):
                cur["id"] = row["id"]

    for seed in seed_people(facility_type):
        upsert(
            {
                "id": seed["id"],
                "display_name": seed["display_name"],
                "kind": seed["kind"],
                "place_label": seed["place_label"],
                "status": "no incidents",
                "last_response": "",
            }
        )

    cases = list(getattr(state, "cases", {}).values()) if state is not None else []
    for case in cases:
        name = getattr(case, "subject_display_name", None)
        if not name:
            continue
        upsert(
            {
                "id": getattr(case, "subject_id", None) or "",
                "display_name": name,
                "kind": getattr(case, "subject_kind", None) or "",
                "place_label": (getattr(case, "place_label", "") or "") or case.room_label,
                "status": _case_person_status(case),
                "last_response": _ORIGIN_RESPONSE.get(case.origin, ""),
            }
        )

    resolved = list(getattr(state, "resident_resolved", []) or []) if state is not None else []
    for row in resolved:
        name = row.get("subject_display_name")
        if not name:
            continue
        reply = row.get("reply_class") or ""
        upsert(
            {
                "id": row.get("subject_id") or "",
                "display_name": name,
                "kind": row.get("subject_kind") or "",
                "place_label": row.get("place_label") or row.get("room_label") or "",
                "status": "ok" if reply == "positive" else "no incidents",
                "last_response": reply,
            }
        )

    out = [merged[k] for k in sorted(merged, key=lambda k: (merged[k].get("display_name") or "").lower())]
    for row in out:
        row.setdefault("status", "no incidents")
        row.setdefault("last_response", "")
        row.setdefault("kind", "")
        row.setdefault("place_label", "")
    return out


def _place_match_keys(place_id: str, label: str, room: str = "") -> set[str]:
    keys = {place_id, label, room, _humanize(place_id), place_id.replace("_", " ")}
    return {k.strip().lower() for k in keys if k and str(k).strip()}


def _open_case_status(cases, keys: set[str]) -> str:
    hit = "configured"
    for case in cases:
        if getattr(case, "state", None) == "closed":
            continue
        case_keys = _place_match_keys(
            getattr(case, "room_label", "") or "",
            getattr(case, "place_label", "") or "",
        )
        if not (keys & case_keys):
            continue
        if case.state == "paged" and not case.ack_at:
            return "incident open"
        hit = "case open"
    return hit


def _last_cue_for(store, cases, keys: set[str]) -> str:
    if store is None:
        return ""
    try:
        incidents = list(store.list_incidents())
    except Exception:
        return ""
    case_by_inc = {}
    for case in cases:
        case_by_inc[case.incident_id] = case
    for inc in reversed(incidents):
        zone = ""
        cue = getattr(inc, "cue", None)
        if cue is not None:
            zone = str((cue.detail or {}).get("zone_id") or "")
        case = case_by_inc.get(inc.id)
        inc_keys = _place_match_keys(zone, zone, zone)
        if case is not None:
            inc_keys |= _place_match_keys(case.room_label, getattr(case, "place_label", "") or "")
        if keys & inc_keys and cue is not None:
            return cue.kind
    return ""


def build_places(state, store, plan: CarePlan) -> list[dict[str, Any]]:
    """Plan zones plus live case places. No invented camera inventory."""
    cases = list(getattr(state, "cases", {}).values()) if state is not None else []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for zone in getattr(plan, "zones", []) or []:
        zid = zone.id
        label = _humanize(zid)
        keys = _place_match_keys(zid, label)
        privacy = "silhouette" if getattr(zone, "kind", "private") == "common" else "blur"
        rows.append(
            {
                "id": zid,
                "place_label": label,
                "zone_kind": getattr(zone, "kind", "private"),
                "privacy": privacy,
                "status": _open_case_status(cases, keys),
                "last_cue": _last_cue_for(store, cases, keys),
                "camera_label": "",
            }
        )
        seen.update(keys)

    for case in cases:
        label = (getattr(case, "place_label", "") or "") or case.room_label
        rid = case.room_label or label
        keys = _place_match_keys(rid, label)
        if keys & seen:
            continue
        rows.append(
            {
                "id": rid,
                "place_label": label,
                "zone_kind": "private",
                "privacy": "blur",
                "status": _open_case_status(cases, keys),
                "last_cue": _last_cue_for(store, cases, keys),
                "camera_label": "",
            }
        )
        seen.update(keys)

    return rows


def _channel_state(cid: str, *, live: bool, plan_enabled: bool, primary: bool) -> str:
    if live:
        return "connected · primary" if primary else "connected"
    if plan_enabled:
        return "configured · stub"
    return "not configured"


def _channel_target(plan: CarePlan, cid: str) -> str:
    notes = getattr(plan, "notifications", None)
    if notes is None:
        return ""
    block = getattr(notes, cid, None)
    if block is None:
        return ""
    if cid == "slack":
        return getattr(block, "channel", None) or ""
    if cid == "telegram":
        return getattr(block, "chat_id", None) or ""
    if cid == "whatsapp":
        return getattr(block, "to", None) or ""
    return ""


def _page_label(inc, state) -> str:
    if state is not None:
        for case in getattr(state, "cases", {}).values():
            if case.incident_id == inc.id:
                place = (getattr(case, "place_label", "") or "") or case.room_label
                hid = case.human_id or ""
                if hid and place:
                    return f"{hid} · {place}"
                return hid or place or f"inc {inc.id[:6]}"
    return f"inc {inc.id[:6]}"


def _delivery_result(detail: dict[str, Any]) -> str:
    if detail.get("adapter") == "stub":
        return "stub"
    if detail.get("delivered") is True:
        return "delivered"
    if detail.get("delivered") is False:
        return "failed"
    return "stub"


def _ack_for_incident(events) -> str:
    for ev in events:
        if ev.tool == "resolve" and (ev.detail or {}).get("reason") == "caretaker_ack":
            who = (ev.detail or {}).get("acked_by")
            return who or "acked"
    if any(ev.tool == "ack_timeout" for ev in events):
        return "window missed"
    return ""


def build_channels(
    plan: CarePlan,
    *,
    live_envs: list[str],
    store,
    pending: list[dict[str, Any]] | None = None,
    state=None,
) -> dict[str, Any]:
    live = set(live_envs or [])
    enabled = []
    notes = getattr(plan, "notifications", None)
    if notes is not None:
        enabled = list(notes.enabled_channels())
    primary = enabled[0] if enabled else ""
    channels = []
    for spec in _CHANNEL_CATALOG:
        cid = spec["id"]
        is_live = cid in live
        plan_on = cid in enabled
        channels.append(
            {
                "id": cid,
                "label": spec["label"],
                "tile": spec["tile"],
                "live": is_live,
                "plan_enabled": plan_on,
                "target": _channel_target(plan, cid) if plan_on else "",
                "state": _channel_state(cid, live=is_live, plan_enabled=plan_on, primary=cid == primary),
            }
        )

    deliveries: list[dict[str, Any]] = []
    if store is not None:
        try:
            incidents = list(store.list_incidents())
        except Exception:
            incidents = []
        for inc in incidents:
            ack = _ack_for_incident(inc.events)
            page = _page_label(inc, state)
            for ev in inc.events:
                if ev.tool not in _PAGE_TOOLS and ev.tool != "staff_page":
                    continue
                detail = ev.detail or {}
                at = ev.at.isoformat() if getattr(ev, "at", None) else None
                if ev.tool == "staff_page":
                    # Layer 2 staff page: who was paged + stub vs delivered.
                    who = detail.get("paged_staff_name") or detail.get("paged_staff_id") or "staff"
                    kind = detail.get("page_kind") or "on_duty"
                    deliveries.append(
                        {
                            "at": at,
                            "page": f"{page} · {kind.replace('_', ' ')} · {who}",
                            "channel": detail.get("adapter") or "stub",
                            "result": _delivery_result(detail),
                            "ack": ack,
                        }
                    )
                    continue
                deliveries.append(
                    {
                        "at": at,
                        "page": page,
                        "channel": detail.get("channel") or ev.tool.replace("notify_", ""),
                        "result": _delivery_result(detail),
                        "ack": ack,
                    }
                )
    for item in pending or []:
        deliveries.append(
            {
                "at": item.get("created_at"),
                "page": f"inc {str(item.get('incident_id') or '')[:6]}",
                "channel": item.get("channel") or "",
                "result": "waiting for ack",
                "ack": "",
            }
        )
    deliveries.sort(key=lambda r: r.get("at") or "", reverse=True)
    return {"channels": channels, "deliveries": deliveries}
