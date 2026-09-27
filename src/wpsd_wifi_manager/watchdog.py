from __future__ import annotations

import argparse
import logging
import shlex
import time
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .connectivity import ConnectivityState, check_connectivity
from .logs import DEFAULT_LOG_PATH
from .network_manager import NetworkManagerClient


LOGGER = logging.getLogger(__name__)


class WifiWatchdog:
    def __init__(
        self,
        client: NetworkManagerClient,
        *,
        interval_seconds: int = 30,
        failure_threshold: int = 2,
        maximum_backoff_seconds: int = 60,
        internet_test: bool = True,
        internet_targets: list[str] | None = None,
    ) -> None:
        self.client = client
        self.interval_seconds = interval_seconds
        self.failure_threshold = failure_threshold
        self.maximum_backoff_seconds = maximum_backoff_seconds
        self.internet_test = internet_test
        self.internet_targets = internet_targets or ["1.1.1.1", "8.8.8.8"]
        self.failures = 0

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self._sleep_seconds())

    def run_once(self) -> ConnectivityState:
        result = check_connectivity(
            self.client,
            internet_test=self.internet_test,
            internet_targets=self.internet_targets,
        )
        LOGGER.info(
            "connectivity state=%s interface=%s connection=%s ip=%s gateway=%s",
            result.state.value,
            result.interface,
            result.connection,
            result.ip4_address,
            result.gateway,
        )
        if result.state == ConnectivityState.CONNECTED:
            self.failures = 0
            return result.state

        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.recover()
        return result.state

    def recover(self) -> None:
        LOGGER.warning("connectivity failed %s time(s); scanning for saved networks", self.failures)
        try:
            access_points = self.client.scan()
            available_ssids = {ap.ssid for ap in access_points}
            candidates = [
                profile
                for profile in self.client.list_wifi_profiles()
                if profile.autoconnect and (profile.ssid or profile.name) in available_ssids
            ]
            candidates.sort(key=lambda profile: profile.priority or 0, reverse=True)
            if not candidates:
                LOGGER.warning("no saved autoconnect networks are visible")
                return
            target = candidates[0]
            LOGGER.warning("requesting NetworkManager connection to %s priority=%s", target.name, target.priority)
            self.client.connect(target.uuid)
        except Exception:
            LOGGER.exception("watchdog recovery failed")

    def _sleep_seconds(self) -> int:
        if self.failures <= self.failure_threshold:
            return self.interval_seconds
        backoff = min(self.maximum_backoff_seconds, 10 * (self.failures - self.failure_threshold + 1))
        return max(self.interval_seconds, backoff)


def main() -> int:
    parser = argparse.ArgumentParser(prog="wpsd-wifi-watchdog")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to Wi-Fi manager JSON config.")
    parser.add_argument("--interface", help="Wi-Fi interface override.")
    parser.add_argument("--helper-command", help="Command prefix for privileged helper, for example: sudo /opt/wpsd-wifi-manager/bin/wifi-helper")
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH, help="Path to event log.")
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    config = load_config(args.config)
    _configure_logging(args.log_path, args.log_level)
    if not config.watchdog.enabled:
        LOGGER.info("watchdog disabled in config")
        return 0

    command = shlex.split(args.helper_command) if args.helper_command else "nmcli"
    client = NetworkManagerClient(nmcli=command, interface=args.interface or config.interface)
    watchdog = WifiWatchdog(
        client,
        interval_seconds=config.watchdog.interval_seconds,
        failure_threshold=config.watchdog.failure_threshold,
        maximum_backoff_seconds=config.watchdog.maximum_backoff_seconds,
        internet_test=config.watchdog.internet_test,
        internet_targets=config.watchdog.internet_targets,
    )
    if args.once:
        watchdog.run_once()
        return 0
    watchdog.run_forever()
    return 0


def _configure_logging(log_path: str, log_level: str) -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )


if __name__ == "__main__":
    raise SystemExit(main())
