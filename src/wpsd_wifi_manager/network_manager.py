from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Protocol, Sequence


class CommandRunner(Protocol):
    def run(self, args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
        ...


class SubprocessRunner:
    def run(self, args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


@dataclass(frozen=True)
class WifiProfile:
    name: str
    uuid: str
    connection_type: str
    device: str
    autoconnect: bool
    ssid: str = ""
    priority: int | None = None
    retries: int | None = None
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WifiAccessPoint:
    ssid: str
    bssid: str
    signal: int | None
    channel: int | None
    security: str
    in_use: bool = False
    saved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WifiStatus:
    interface: str
    state: str
    connection: str
    ssid: str
    ip4_address: str
    gateway: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NetworkManagerError(RuntimeError):
    def __init__(self, message: str, *, command: Iterable[str] = (), stderr: str = ""):
        self.command = list(command)
        self.stderr = sanitize_output(stderr)
        super().__init__(message)


class NetworkManagerClient:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        nmcli: str | Sequence[str] = "nmcli",
        interface: str | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.command_prefix = [nmcli] if isinstance(nmcli, str) else list(nmcli)
        self.interface = interface

    def is_available(self) -> bool:
        result = self._run(["--version"], check=False)
        return result.returncode == 0

    def detect_wifi_interface(self) -> str | None:
        result = self._nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
        fallback: str | None = None
        for row in _parse_terse_rows(result.stdout):
            if len(row) < 3 or row[1] != "wifi" or row[0].startswith("p2p-dev-"):
                continue
            if row[2].lower() == "connected":
                return row[0]
            fallback = fallback or row[0]
        return fallback

    def list_wifi_profiles(self) -> list[WifiProfile]:
        rows = self._nmcli(
            [
                "-t",
                "-f",
                "NAME,UUID,TYPE,DEVICE,AUTOCONNECT",
                "connection",
                "show",
            ]
        )
        active_uuids = self._active_connection_uuids()
        profiles: list[WifiProfile] = []
        for row in _parse_terse_rows(rows.stdout):
            if len(row) < 5 or row[2] != "802-11-wireless":
                continue
            profile = WifiProfile(
                name=row[0],
                uuid=row[1],
                connection_type=row[2],
                device=row[3],
                autoconnect=_parse_bool(row[4]),
                active=row[1] in active_uuids,
            )
            profiles.append(self._with_profile_settings(profile))
        return profiles

    def scan(self, rescan: bool = True) -> list[WifiAccessPoint]:
        if rescan:
            self.rescan()
        args = [
            "-t",
            "-f",
            "IN-USE,BSSID,SSID,CHAN,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
        ]
        if self.interface:
            args.extend(["ifname", self.interface])
        rows = self._nmcli(args, timeout=30)
        saved_ssids = {profile.ssid or profile.name for profile in self.list_wifi_profiles()}
        aps: list[WifiAccessPoint] = []
        for row in _parse_terse_rows(rows.stdout):
            if len(row) < 6:
                continue
            aps.append(
                WifiAccessPoint(
                    in_use=row[0] == "*",
                    bssid=row[1],
                    ssid=row[2],
                    channel=_parse_int(row[3]),
                    signal=_parse_int(row[4]),
                    security=row[5],
                    saved=row[2] in saved_ssids,
                )
            )
        return aps

    def rescan(self) -> None:
        args = ["device", "wifi", "rescan"]
        if self.interface:
            args.extend(["ifname", self.interface])
        self._nmcli(args, timeout=30)

    def status(self) -> WifiStatus:
        interface = self.interface or self.detect_wifi_interface()
        args = [
            "-t",
            "-f",
            "GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY",
            "device",
            "show",
        ]
        if interface:
            args.append(interface)
        result = self._nmcli(args)
        values: dict[str, str] = {}
        for row in _parse_terse_rows(result.stdout):
            if len(row) >= 2:
                values[row[0]] = row[1]
        connection = values.get("GENERAL.CONNECTION", "")
        return WifiStatus(
            interface=values.get("GENERAL.DEVICE", interface or ""),
            state=values.get("GENERAL.STATE", "unknown"),
            connection=connection,
            ssid=connection,
            ip4_address=values.get("IP4.ADDRESS[1]", values.get("IP4.ADDRESS", "")),
            gateway=values.get("IP4.GATEWAY", ""),
        )

    def add_profile(
        self,
        ssid: str,
        password: str,
        *,
        profile_name: str | None = None,
        priority: int | None = None,
        autoconnect: bool = True,
        connect: bool = False,
        hidden: bool = False,
    ) -> None:
        if not ssid:
            raise ValueError("SSID is required")

        target = profile_name or ssid
        args = [
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            self.interface or "*",
            "con-name",
            target,
            "ssid",
            ssid,
        ]
        self._nmcli(args, timeout=30)
        if hidden:
            self._nmcli(["connection", "modify", target, "802-11-wireless.hidden", "yes"])
        if password:
            self._nmcli(
                [
                    "connection",
                    "modify",
                    target,
                    "wifi-sec.key-mgmt",
                    "wpa-psk",
                    "wifi-sec.psk",
                    password,
                ],
                sensitive=[password],
            )

        self.set_autoconnect(target, autoconnect)
        if priority is not None:
            self.set_priority(target, priority)
        if connect:
            self.connect(target)

    def connect_visible_network(
        self,
        ssid: str,
        password: str,
        *,
        profile_name: str | None = None,
        priority: int | None = None,
        autoconnect: bool = True,
    ) -> None:
        if not ssid:
            raise ValueError("SSID is required")
        if not password:
            raise ValueError("password is required")

        args = ["device", "wifi", "connect", ssid, "password", password]
        if self.interface:
            args.extend(["ifname", self.interface])
        if profile_name:
            args.extend(["name", profile_name])
        self._nmcli(args, timeout=60, sensitive=[password])

        target = profile_name or ssid
        self.set_autoconnect(target, autoconnect)
        if priority is not None:
            self.set_priority(target, priority)

    def connect(self, uuid_or_name: str) -> None:
        self._nmcli(["connection", "up", uuid_or_name], timeout=60)

    def disconnect(self) -> None:
        args = ["device", "disconnect"]
        if not self.interface:
            interface = self.detect_wifi_interface()
            if not interface:
                raise ValueError("interface is required when no active Wi-Fi device is detected")
            args.append(interface)
        else:
            args.append(self.interface)
        self._nmcli(args, timeout=30)

    def forget(self, uuid_or_name: str) -> None:
        self._nmcli(["connection", "delete", uuid_or_name], timeout=30)

    def set_priority(self, uuid_or_name: str, priority: int) -> None:
        self._nmcli(
            [
                "connection",
                "modify",
                uuid_or_name,
                "connection.autoconnect-priority",
                str(priority),
            ]
        )

    def set_autoconnect(self, uuid_or_name: str, enabled: bool) -> None:
        self._nmcli(
            [
                "connection",
                "modify",
                uuid_or_name,
                "connection.autoconnect",
                "yes" if enabled else "no",
            ]
        )

    def set_retries(self, uuid_or_name: str, retries: int) -> None:
        self._nmcli(
            [
                "connection",
                "modify",
                uuid_or_name,
                "connection.autoconnect-retries",
                str(retries),
            ]
        )

    def update_password(self, uuid_or_name: str, password: str) -> None:
        if not password:
            raise ValueError("password is required")
        self._nmcli(
            [
                "connection",
                "modify",
                uuid_or_name,
                "802-11-wireless-security.psk",
                password,
            ],
            sensitive=[password],
        )

    def _with_profile_settings(self, profile: WifiProfile) -> WifiProfile:
        result = self._run(
            [
                "-g",
                "connection.autoconnect-priority,connection.autoconnect-retries,802-11-wireless.ssid",
                "connection",
                "show",
                profile.uuid,
            ],
            check=False,
        )
        if result.returncode != 0:
            return profile
        values = [line.strip() for line in result.stdout.splitlines()]
        return WifiProfile(
            name=profile.name,
            uuid=profile.uuid,
            connection_type=profile.connection_type,
            device=profile.device,
            autoconnect=profile.autoconnect,
            ssid=values[2] if len(values) > 2 and values[2] else profile.name,
            priority=_parse_int(values[0]) if len(values) > 0 else None,
            retries=_parse_int(values[1]) if len(values) > 1 else None,
            active=profile.active,
        )

    def _active_connection_uuids(self) -> set[str]:
        result = self._run(
            ["-t", "-f", "UUID,TYPE", "connection", "show", "--active"],
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {
            row[0]
            for row in _parse_terse_rows(result.stdout)
            if len(row) >= 2 and row[1] == "802-11-wireless"
        }

    def _nmcli(
        self,
        args: list[str],
        *,
        timeout: int = 20,
        sensitive: Iterable[str] = (),
    ) -> subprocess.CompletedProcess[str]:
        return self._run(args, timeout=timeout, sensitive=sensitive)

    def _run(
        self,
        args: list[str],
        *,
        timeout: int = 20,
        check: bool = True,
        sensitive: Iterable[str] = (),
    ) -> subprocess.CompletedProcess[str]:
        command = [*self.command_prefix, *args]
        result = self.runner.run(command, timeout=timeout)
        if check and result.returncode != 0:
            safe_command = _redact_args(command, sensitive)
            raise NetworkManagerError(
                f"nmcli exited {result.returncode}: {sanitize_output(result.stderr, sensitive)}",
                command=safe_command,
                stderr=result.stderr,
            )
        return result


def profiles_to_json(profiles: list[WifiProfile]) -> str:
    return json.dumps([profile.to_dict() for profile in profiles], indent=2)


def access_points_to_json(access_points: list[WifiAccessPoint]) -> str:
    return json.dumps([access_point.to_dict() for access_point in access_points], indent=2)


def sanitize_output(text: str, sensitive: Iterable[str] = ()) -> str:
    sanitized = text
    for value in sensitive:
        if value:
            sanitized = sanitized.replace(value, "[redacted]")
    return sanitized


def _redact_args(args: list[str], sensitive: Iterable[str]) -> list[str]:
    sensitive_values = {value for value in sensitive if value}
    return ["[redacted]" if arg in sensitive_values else arg for arg in args]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"yes", "true", "1"}


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _parse_terse_rows(text: str) -> list[list[str]]:
    return [_split_nmcli_terse(line) for line in text.splitlines() if line.strip()]


def _split_nmcli_terse(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields
