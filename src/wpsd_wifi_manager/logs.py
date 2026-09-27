from __future__ import annotations

from collections import deque
from pathlib import Path


DEFAULT_LOG_PATH = "/opt/wpsd-wifi-manager/logs/wifi-manager.log"


def tail_log(path: str | Path = DEFAULT_LOG_PATH, lines: int = 120) -> dict[str, object]:
    log_path = Path(path)
    if not log_path.exists():
        return {
            "path": str(log_path),
            "exists": False,
            "lines": [],
        }

    count = max(1, min(lines, 500))
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        entries = deque(handle, maxlen=count)
    return {
        "path": str(log_path),
        "exists": True,
        "lines": [entry.rstrip("\n") for entry in entries],
    }
