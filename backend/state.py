"""Process-wide runtime state (uptime + ring-buffer of recent request logs)."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime

START_TIME = time.time()
START_DATETIME = datetime.now().isoformat()
RECENT_LOGS: deque[dict] = deque(maxlen=50)


def log_event(level: str, message: str, details: dict | None = None) -> None:
    RECENT_LOGS.appendleft(
        {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "details": details or {},
        }
    )
