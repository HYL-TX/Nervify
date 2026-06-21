# backend/storage.py
#
# Persistence of completed session results to the on-disk JSON log.

import json
from typing import Any

from . import config


def load_sessions() -> list[dict[str, Any]]:
    if not config.SESSION_LOG_PATH.exists():
        return []
    try:
        return json.loads(config.SESSION_LOG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_session_result(result: dict[str, Any]) -> None:
    sessions = load_sessions()
    sessions.append(result)
    config.SESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SESSION_LOG_PATH.write_text(json.dumps(sessions, indent=2))
