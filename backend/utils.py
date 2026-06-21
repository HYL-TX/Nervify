# backend/utils.py
#
# Tiny, dependency-free helpers shared across modules.

from datetime import datetime, timezone
from typing import Any, Optional


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_float(payload: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
