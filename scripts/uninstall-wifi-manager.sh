#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wpsd-wifi-manager}"
ADMIN_SERVICE_NAME="wpsd-wifi-manager-admin.service"
WATCHDOG_SERVICE_NAME="wpsd-wifi-watchdog.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/uninstall-wifi-manager.sh" >&2
  exit 1
fi

read -r -p "Preserve saved NetworkManager Wi-Fi profiles? [Y/n] " PRESERVE_PROFILES
PRESERVE_PROFILES="${PRESERVE_PROFILES:-Y}"

systemctl disable --now "${ADMIN_SERVICE_NAME}" "${WATCHDOG_SERVICE_NAME}" 2>/dev/null || true
rm -f "/etc/systemd/system/${ADMIN_SERVICE_NAME}"
rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}"
rm -f "/etc/sudoers.d/wpsd-wifi-manager"
rm -f "/etc/logrotate.d/wpsd-wifi-manager"
rm -f "/etc/nginx/default.d/wpsd-wifi-manager.conf"
systemctl daemon-reload
if command -v nginx >/dev/null 2>&1 && nginx -t; then
  systemctl reload nginx || true
elif [[ -x /usr/sbin/nginx ]] && /usr/sbin/nginx -t; then
  systemctl reload nginx || true
fi

rm -rf "${APP_DIR}"

if [[ ! "${PRESERVE_PROFILES}" =~ ^[Yy]$ ]]; then
  echo "Saved Wi-Fi profiles are managed by NetworkManager and were not removed automatically."
  echo "Remove unwanted profiles manually with: sudo nmcli connection delete <uuid-or-name>"
else
  echo "Preserved saved NetworkManager Wi-Fi profiles."
fi

echo "Uninstalled WPSD Wi-Fi Manager."
