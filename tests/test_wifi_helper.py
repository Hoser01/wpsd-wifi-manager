from __future__ import annotations

import pytest

from wpsd_wifi_manager.helper import validate_nmcli_args


@pytest.mark.parametrize(
    "args",
    [
        ["--version"],
        ["device", "wifi", "rescan", "ifname", "wlan0"],
        ["connection", "up", "ad1d9b97-2ef3-44d8-a028-c0d3ef625001"],
        [
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
        ],
        [
            "connection",
            "modify",
            "iPhone",
            "connection.autoconnect-priority",
            "50",
            "connection.autoconnect-retries",
            "0",
        ],
        [
            "-t",
            "-f",
            "NAME,UUID,TYPE,DEVICE,AUTOCONNECT,802-11-wireless.ssid",
            "connection",
            "show",
        ],
    ],
)
def test_helper_allows_expected_nmcli_shapes(args: list[str]) -> None:
    validate_nmcli_args(args)


@pytest.mark.parametrize(
    "args",
    [
        ["general", "reload"],
        ["connection", "modify", "iPhone", "ipv4.gateway", "10.0.0.1"],
        ["connection", "add", "type", "ethernet", "ifname", "eth0"],
        ["device", "wifi", "connect", "SSID", "password", "secret"],
        ["connection", "modify", "iPhone", "wifi-sec.psk", "bad\nsecret"],
    ],
)
def test_helper_rejects_unapproved_nmcli_shapes(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        validate_nmcli_args(args)
