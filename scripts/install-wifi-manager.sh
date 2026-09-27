#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wpsd-wifi-manager}"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN_SERVICE_NAME="wpsd-wifi-manager-admin.service"
WATCHDOG_SERVICE_NAME="wpsd-wifi-watchdog.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-wifi-manager.sh" >&2
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli is required but was not found." >&2
  exit 1
fi

if ! id pi-star >/dev/null 2>&1; then
  echo "The pi-star user was not found. Is this a WPSD system?" >&2
  exit 1
fi

install -d -m 0755 "${APP_DIR}"
install -d -m 0755 "${APP_DIR}/bin"
install -d -m 0755 "${APP_DIR}/config"
install -d -m 0755 "${APP_DIR}/logs"

rm -rf "${APP_DIR}/src"
cp -a "${SOURCE_ROOT}/src" "${APP_DIR}/src"

if [[ -d "${SOURCE_ROOT}/docs" ]]; then
  rm -rf "${APP_DIR}/docs"
  cp -a "${SOURCE_ROOT}/docs" "${APP_DIR}/docs"
fi

if [[ -d "${SOURCE_ROOT}/scripts" ]]; then
  rm -rf "${APP_DIR}/scripts"
  cp -a "${SOURCE_ROOT}/scripts" "${APP_DIR}/scripts"
fi

cat > "${APP_DIR}/bin/wifi-helper" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/wpsd-wifi-manager/src
exec /usr/bin/python3 -m wpsd_wifi_manager.helper "$@"
EOF
chmod 0755 "${APP_DIR}/bin/wifi-helper"

PYTHONPATH="${APP_DIR}/src" python3 - <<'PY'
from wpsd_wifi_manager.config import write_default_config
write_default_config("/opt/wpsd-wifi-manager/config/config.json")
PY

install -m 0644 "${SOURCE_ROOT}/deploy/systemd/${ADMIN_SERVICE_NAME}" "/etc/systemd/system/${ADMIN_SERVICE_NAME}"
install -m 0644 "${SOURCE_ROOT}/deploy/systemd/${WATCHDOG_SERVICE_NAME}" "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}"
install -m 0440 "${SOURCE_ROOT}/deploy/sudoers/wpsd-wifi-manager" "/etc/sudoers.d/wpsd-wifi-manager"
install -m 0644 "${SOURCE_ROOT}/deploy/logrotate/wpsd-wifi-manager" "/etc/logrotate.d/wpsd-wifi-manager"

if [[ -d /etc/nginx/default.d && -f "${SOURCE_ROOT}/deploy/nginx/wpsd-wifi-manager.conf" ]]; then
  install -m 0644 "${SOURCE_ROOT}/deploy/nginx/wpsd-wifi-manager.conf" "/etc/nginx/default.d/wpsd-wifi-manager.conf"
  if command -v nginx >/dev/null 2>&1 && nginx -t; then
    systemctl reload nginx || systemctl restart nginx || true
  elif [[ -x /usr/sbin/nginx ]] && /usr/sbin/nginx -t; then
    systemctl reload nginx || systemctl restart nginx || true
  else
    echo "Installed nginx /wifi route, but nginx config test was not available or did not pass." >&2
  fi
fi

if command -v visudo >/dev/null 2>&1; then
  visudo -cf "/etc/sudoers.d/wpsd-wifi-manager"
fi

chown -R pi-star:pi-star "${APP_DIR}/src" "${APP_DIR}/docs" "${APP_DIR}/scripts" "${APP_DIR}/config" "${APP_DIR}/logs" 2>/dev/null || true
chown root:root "${APP_DIR}/bin/wifi-helper"

systemctl daemon-reload
systemctl enable --now "${ADMIN_SERVICE_NAME}"
systemctl enable --now "${WATCHDOG_SERVICE_NAME}"

echo "Installed WPSD Wi-Fi Manager."
echo
echo "Admin UI:"
echo "  http://<hotspot-hostname-or-ip>:8093/"
echo "  http://<hotspot-hostname-or-ip>/wifi/"
echo
echo "Services:"
echo "  sudo systemctl status ${ADMIN_SERVICE_NAME}"
echo "  sudo systemctl status ${WATCHDOG_SERVICE_NAME}"
echo
echo "To uninstall:"
echo "  sudo ${APP_DIR}/scripts/uninstall-wifi-manager.sh"
