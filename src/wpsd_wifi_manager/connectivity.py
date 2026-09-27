from __future__ import annotations

import socket
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .network_manager import NetworkManagerClient


class ConnectivityState(StrEnum):
    CONNECTED = "CONNECTED"
    LOCAL_ONLY = "LOCAL_ONLY"
    NO_GATEWAY = "NO_GATEWAY"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ConnectivityResult:
    state: ConnectivityState
    interface: str
    connection: str
    ip4_address: str
    gateway: str
    internet_reachable: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def check_connectivity(
    client: NetworkManagerClient,
    *,
    internet_test: bool = True,
    internet_targets: list[str] | None = None,
    timeout_seconds: float = 1.5,
) -> ConnectivityResult:
    status = client.status()
    if not status.connection or status.connection == "--":
        state = ConnectivityState.DISCONNECTED
        internet = False
    elif not status.ip4_address:
        state = ConnectivityState.LOCAL_ONLY
        internet = False
    elif not status.gateway:
        state = ConnectivityState.NO_GATEWAY
        internet = False
    elif internet_test:
        internet = _internet_reachable(internet_targets or ["1.1.1.1", "8.8.8.8"], timeout_seconds)
        state = ConnectivityState.CONNECTED if internet else ConnectivityState.LOCAL_ONLY
    else:
        internet = False
        state = ConnectivityState.CONNECTED
    return ConnectivityResult(
        state=state,
        interface=status.interface,
        connection=status.connection,
        ip4_address=status.ip4_address,
        gateway=status.gateway,
        internet_reachable=internet,
    )


def _internet_reachable(targets: list[str], timeout_seconds: float) -> bool:
    for target in targets:
        try:
            with socket.create_connection((target, 53), timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False
