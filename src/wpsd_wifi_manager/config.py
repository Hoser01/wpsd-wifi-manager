from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = "/opt/wpsd-wifi-manager/config/config.json"


@dataclass(frozen=True)
class WatchdogConfig:
    enabled: bool = True
    interval_seconds: int = 30
    failure_threshold: int = 2
    maximum_backoff_seconds: int = 60
    internet_test: bool = True
    internet_targets: list[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])


@dataclass(frozen=True)
class WifiManagerConfig:
    interface: str | None = None
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> WifiManagerConfig:
    config_path = Path(path)
    if not config_path.exists():
        return WifiManagerConfig()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Wi-Fi manager config must be a JSON object")
    watchdog = data.get("watchdog", {})
    if not isinstance(watchdog, dict):
        watchdog = {}
    return WifiManagerConfig(
        interface=_optional_str(data.get("interface")),
        watchdog=WatchdogConfig(
            enabled=bool(watchdog.get("enabled", True)),
            interval_seconds=max(5, int(watchdog.get("interval_seconds", 30))),
            failure_threshold=max(1, int(watchdog.get("failure_threshold", 2))),
            maximum_backoff_seconds=max(5, int(watchdog.get("maximum_backoff_seconds", 60))),
            internet_test=bool(watchdog.get("internet_test", True)),
            internet_targets=_string_list(watchdog.get("internet_targets"), ["1.1.1.1", "8.8.8.8"]),
        ),
    )


def write_default_config(path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(json.dumps(WifiManagerConfig().to_dict(), indent=2) + "\n", encoding="utf-8")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return default
    out = [str(item) for item in value if str(item)]
    return out or default
