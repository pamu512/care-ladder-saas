from __future__ import annotations

from pathlib import Path

import yaml

from care_ladder.models import CarePlan


def load_care_plan(path: Path) -> CarePlan:
    """Load a household care plan YAML into a validated CarePlan model."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CarePlan.model_validate(data)
