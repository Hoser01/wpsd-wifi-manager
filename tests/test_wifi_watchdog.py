from __future__ import annotations

from dataclasses import dataclass, field

from wpsd_wifi_manager.network_manager import WifiAccessPoint, WifiProfile, WifiStatus
from wpsd_wifi_manager.watchdog import WifiWatchdog


@dataclass
class FakeClient:
    statuses: list[WifiStatus]
    profiles: list[WifiProfile]
    access_points: list[WifiAccessPoint]
    connected: list[str] = field(default_factory=list)

    def status(self) -> WifiStatus:
        return self.statuses[0]

    def scan(self) -> list[WifiAccessPoint]:
        return self.access_points

    def list_wifi_profiles(self) -> list[WifiProfile]:
        return self.profiles

    def connect(self, uuid_or_name: str) -> None:
        self.connected.append(uuid_or_name)


def test_watchdog_connects_highest_priority_visible_saved_network() -> None:
    client = FakeClient(
        statuses=[
            WifiStatus(
                interface="wlan0",
                state="30 (disconnected)",
                connection="",
                ssid="",
                ip4_address="",
                gateway="",
            )
        ],
        access_points=[
            WifiAccessPoint(ssid="Travel", bssid="aa", signal=50, channel=6, security="WPA2"),
            WifiAccessPoint(ssid="iPhone", bssid="bb", signal=70, channel=6, security="WPA2"),
        ],
        profiles=[
            WifiProfile(
                name="Travel profile",
                uuid="travel-uuid",
                connection_type="802-11-wireless",
                device="--",
                autoconnect=True,
                ssid="Travel",
                priority=25,
            ),
            WifiProfile(
                name="Phone profile",
                uuid="phone-uuid",
                connection_type="802-11-wireless",
                device="--",
                autoconnect=True,
                ssid="iPhone",
                priority=50,
            ),
        ],
    )
    watchdog = WifiWatchdog(client, failure_threshold=1, internet_test=False)

    watchdog.run_once()

    assert client.connected == ["phone-uuid"]
