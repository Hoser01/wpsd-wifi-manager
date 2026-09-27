# WPSD Wi-Fi Manager

`wpsd-wifi-manager` is a sidecar admin service for NetworkManager-managed Wi-Fi profiles on WPSD hotspots.

It follows the same deployment style as `ysf-bm-router`:

- Install under `/opt/wpsd-wifi-manager`.
- Run independently from WPSD core services.
- Expose a small LAN admin UI.
- Use NetworkManager and `nmcli` as the source of truth.
- Avoid storing Wi-Fi passwords in plugin configuration.

Default admin URL:

```text
http://wpsd.local:8093/
```

## Implemented Slice

The current slice includes:

- NetworkManager availability checks.
- Saved Wi-Fi profile discovery.
- Active Wi-Fi profile detection.
- Wi-Fi scan parsing.
- Status discovery for interface, connection, IP address, and gateway.
- Profile creation through NetworkManager.
- Connect, disconnect, forget, priority, autoconnect, retry, and password-update commands.
- A minimal admin UI and JSON API.
- Live status and recent event-log display on the admin page.
- WPSD dashboard theme color matching via `/etc/wpsd-css.ini`.
- A restricted privileged helper for NetworkManager operations.
- A sudoers policy that allows `pi-star` to run only that helper.
- A watchdog service with progressive failure counting, rescans, and highest-priority saved-network recovery.
- An installer for `/opt/wpsd-wifi-manager`.
- Log rotation.
- A clean uninstaller that preserves NetworkManager Wi-Fi profiles by default.

Install on WPSD with:

```bash
sudo ./scripts/install-wifi-manager.sh
```

Installed services:

```bash
sudo systemctl status wpsd-wifi-manager-admin.service
sudo systemctl status wpsd-wifi-watchdog.service
```

Uninstall:

```bash
sudo /opt/wpsd-wifi-manager/scripts/uninstall-wifi-manager.sh
```

## WPSD Wi-Fi Feature Parity

The stock WPSD Wi-Fi page supports scanning for networks, selecting a visible SSID, manually entering an SSID/passphrase, and connecting immediately after entering credentials. This manager keeps those flows and adds saved-profile management for multiple NetworkManager profiles.

Baseline flows:

- Scan for visible networks.
- Select a scanned network and prefill the SSID field.
- Manually enter an SSID and passphrase.
- Save credentials without switching networks.
- Save and connect immediately, with a warning that the browser session may disconnect.

Extended flows:

- Show saved profiles.
- Switch among saved profiles.
- Manage priority, autoconnect, persistent retries, and password updates.
- Protect the active profile from accidental deletion.
- Show live connection status and recent log lines.

## Safety

The admin UI warns before connecting another Wi-Fi profile because the browser session may disconnect or the hotspot may receive a different IP address.

Passwords are passed directly to `nmcli` without shell expansion and are redacted from structured command errors. The plugin should not log raw request bodies.

The admin service should run as `pi-star`. Operations that require elevated NetworkManager privileges should move through the restricted helper rather than running the web process as root.

The installer creates:

```text
/opt/wpsd-wifi-manager/bin/wifi-helper
/etc/sudoers.d/wpsd-wifi-manager
```

The sudoers rule permits `pi-star` to run the helper only. The helper validates requested `nmcli` arguments before invoking NetworkManager, and rejects operations outside the Wi-Fi profile/scan/connect scope.

## Watchdog

The watchdog reads:

```text
/opt/wpsd-wifi-manager/config/config.json
```

Default behavior:

- Check connectivity every 30 seconds.
- Treat two consecutive failures as actionable.
- Rescan visible networks.
- Compare visible SSIDs against saved NetworkManager Wi-Fi profiles.
- Ask NetworkManager to bring up the highest-priority visible saved profile.

It does not reboot WPSD, restart NetworkManager, or delete/modify unrelated routes.

## Theme

The admin page reads WPSD's selected dashboard color config from:

```text
/etc/wpsd-css.ini
```

Those colors are mapped into CSS variables so the page follows the WPSD dashboard theme, matching the YSF-BM router admin UI behavior.
