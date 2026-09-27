# WPSD Wi-Fi Manager

NetworkManager-based Wi-Fi profile manager and failover watchdog for WPSD hotspots.

This project runs as a sidecar service outside WPSD core files. It provides a WPSD-themed admin UI for saved Wi-Fi profiles, manual network switching, live status/logs, and automatic recovery to the highest-priority visible saved network.

## Features

- Scan visible Wi-Fi networks.
- Add visible or hidden Wi-Fi profiles.
- Save credentials through NetworkManager, not a plugin password database.
- Save profiles without switching networks by default.
- Connect saved profiles from the admin UI.
- Set autoconnect, priority, and persistent retry behavior.
- Update saved Wi-Fi passwords.
- Protect the active profile from accidental deletion.
- Show live connection status and recent event-log lines.
- Match WPSD dashboard theme colors from `/etc/wpsd-css.ini`.
- Run admin and watchdog services as `pi-star`.
- Use a restricted sudo helper for privileged NetworkManager operations.

## Install

On the WPSD hotspot:

```bash
sudo ./scripts/install-wifi-manager.sh
```

Default admin URL:

```text
http://wpsd.local:8093/
```

Service checks:

```bash
sudo systemctl status wpsd-wifi-manager-admin.service
sudo systemctl status wpsd-wifi-watchdog.service
```

## Uninstall

```bash
sudo /opt/wpsd-wifi-manager/scripts/uninstall-wifi-manager.sh
```

The uninstaller preserves NetworkManager Wi-Fi profiles by default.

## Development

```bash
python -m pytest
```

More detail is in [docs/WIFI-MANAGER.md](docs/WIFI-MANAGER.md).
