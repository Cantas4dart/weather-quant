from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CityConfig


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data["cities"] = [CityConfig(**city) for city in data.get("cities", [])]
    return data

