from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import pytest

from wpsd_wifi_manager.network_manager import NetworkManagerClient, NetworkManagerError
from wpsd_wifi_manager.network_manager import _split_nmcli_terse


@dataclass
class FakeRunner:
    responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]]
    calls: list[list[str]] = field(default_factory=list)

    def run(self, args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        key = tuple(args)
        if key in self.responses:
            return self.responses[key]
        return subprocess.CompletedProcess(args, 1, "", f"unexpected command: {args}")


def completed(args: list[str], stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_split_nmcli_terse_handles_escaped_colons() -> None:
    assert _split_nmcli_terse(r"Home\:Lab:uuid:802-11-wireless") == [
        "Home:Lab",
        "uuid",
        "802-11-wireless",
    ]


def test_list_wifi_profiles_filters_wifi_and_loads_settings() -> None:
    runner = FakeRunner(
        {
            (
                "nmcli",
                "-t",
                "-f",
                "NAME,UUID,TYPE,DEVICE,AUTOCONNECT",
                "connection",
                "show",
            ): completed(
                [],
                "Home Profile:u1:802-11-wireless:wlan0:yes\nWired:u2:802-3-ethernet:eth0:yes\n",
            ),
            ("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show", "--active"): completed(
                [],
                "u1:802-11-wireless\n",
            ),
            (
                "nmcli",
                "-g",
                "connection.autoconnect-priority,connection.autoconnect-retries,802-11-wireless.ssid",
                "connection",
                "show",
                "u1",
            ): completed([], "100\n0\nERIS\n"),
        }
    )

    profiles = NetworkManagerClient(runner=runner).list_wifi_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "Home Profile"
    assert profiles[0].ssid == "ERIS"
    assert profiles[0].active is True
    assert profiles[0].priority == 100
    assert profiles[0].retries == 0


def test_scan_marks_saved_networks() -> None:
    runner = FakeRunner(
        {
            ("nmcli", "device", "wifi", "rescan", "ifname", "wlan0"): completed([]),
            (
                "nmcli",
                "-t",
                "-f",
                "IN-USE,BSSID,SSID,CHAN,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "ifname",
                "wlan0",
            ): completed([], "*:AA\\:BB\\:CC\\:DD\\:EE\\:FF:ERIS:6:61:WPA2\n"),
            (
                "nmcli",
                "-t",
                "-f",
                "NAME,UUID,TYPE,DEVICE,AUTOCONNECT",
                "connection",
                "show",
            ): completed(
                [],
                "Home Profile:u1:802-11-wireless:wlan0:yes\n",
            ),
            ("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show", "--active"): completed(
                [],
                "u1:802-11-wireless\n",
            ),
            (
                "nmcli",
                "-g",
                "connection.autoconnect-priority,connection.autoconnect-retries,802-11-wireless.ssid",
                "connection",
                "show",
                "u1",
            ): completed([], "100\n0\nERIS\n"),
        }
    )

    aps = NetworkManagerClient(runner=runner, interface="wlan0").scan()

    assert aps[0].ssid == "ERIS"
    assert aps[0].in_use is True
    assert aps[0].saved is True
    assert aps[0].signal == 61


def test_password_is_redacted_from_errors() -> None:
    password = "super-secret"
    runner = FakeRunner(
        {
            (
                "nmcli",
                "connection",
                "modify",
                "u1",
                "802-11-wireless-security.psk",
                password,
            ): completed([], stderr=f"bad password {password}", returncode=4),
        }
    )

    with pytest.raises(NetworkManagerError) as exc_info:
        NetworkManagerClient(runner=runner).update_password("u1", password)

    assert password not in str(exc_info.value)
    assert password not in " ".join(exc_info.value.command)
    assert "[redacted]" in str(exc_info.value)


def test_add_profile_saves_without_connecting_by_default() -> None:
    password = "super-secret"
    runner = FakeRunner(
        {
            (
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                "wlan0",
                "con-name",
                "iPhone",
                "ssid",
                "iPhone",
            ): completed([]),
            (
                "nmcli",
                "connection",
                "modify",
                "iPhone",
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ): completed([]),
            (
                "nmcli",
                "connection",
                "modify",
                "iPhone",
                "connection.autoconnect",
                "yes",
            ): completed([]),
            (
                "nmcli",
                "connection",
                "modify",
                "iPhone",
                "connection.autoconnect-priority",
                "50",
            ): completed([]),
        }
    )

    NetworkManagerClient(runner=runner, interface="wlan0").add_profile(
        "iPhone",
        password,
        priority=50,
    )

    flattened_calls = [" ".join(call) for call in runner.calls]
    assert not any("connection up" in call for call in flattened_calls)
    assert not any("device disconnect" in call for call in flattened_calls)
