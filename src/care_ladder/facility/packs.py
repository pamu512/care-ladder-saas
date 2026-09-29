"""Facility packs: YAML packs per facility_type + Zone.kind loading."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

_PACK_DIR = Path(__file__).resolve().parents[3] / "configs" / "facility_packs"

VALID_TYPES = ("daycare_kids", "assisted_living", "rehab", "old_age_home")


class FacilityPack(BaseModel):
    facility_type: str
    vocabulary: dict[str, str]  # subject / place / lead labels
    sla_ack_sec: int
    sla_handling_sec: int
    cue_allowlist: list[str]
    roles: list[dict[str, Any]]
    concurrency: dict[str, Any]


def load_pack(facility_type: str) -> FacilityPack:
    """Load configs/facility_packs/{facility_type}.yaml (assisted_living fallback)."""
    path = _PACK_DIR / f"{facility_type}.yaml"
    if not path.exists():
        path = _PACK_DIR / "assisted_living.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return FacilityPack(**data)
