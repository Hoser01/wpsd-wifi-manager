from __future__ import annotations

import argparse
import json
import logging
import shlex
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote

from .logs import DEFAULT_LOG_PATH, tail_log
from .network_manager import NetworkManagerClient, NetworkManagerError
from .theme import DEFAULT_WPSD_CSS_PATH, read_wpsd_theme


LOGGER = logging.getLogger(__name__)
WPSD_WIFI_FEATURES = [
    "Scan for visible Wi-Fi networks",
    "Select a scanned network and enter its PSK",
    "Manually add a network by SSID and passphrase",
    "Connect immediately after saving credentials",
    "Manage Wi-Fi after initial setup from the dashboard",
    "Keep the current connection untouched when saving only",
    "Manage multiple saved NetworkManager profiles",
    "Set autoconnect priority and persistent retries",
    "Switch between saved networks without SSH",
    "Show live connection status and recent manager log lines",
]


def run_admin_server(
    host: str = "0.0.0.0",
    port: int = 8093,
    interface: str | None = None,
    wpsd_css_path: str = DEFAULT_WPSD_CSS_PATH,
    log_path: str = DEFAULT_LOG_PATH,
    helper_command: str | None = None,
) -> None:
    handler = _make_handler(interface, wpsd_css_path, log_path, helper_command)
    server = ThreadingHTTPServer((host, port), handler)
    LOGGER.info("wifi manager admin listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _make_handler(interface: str | None, wpsd_css_path: str, log_path: str, helper_command: str | None):
    command = shlex.split(helper_command) if helper_command else "nmcli"

    class WifiAdminHandler(BaseHTTPRequestHandler):
        server_version = "WPSDWifiManagerAdmin/0.1"

        def do_GET(self) -> None:
            client = NetworkManagerClient(interface=interface, nmcli=command)
            try:
                if self.path in {"/", "/index.html"}:
                    self._send_text(INDEX_HTML, "text/html; charset=utf-8")
                    return
                if self.path == "/api/status":
                    self._send_json({"ok": True, "status": client.status().to_dict()})
                    return
                if self.path == "/api/theme":
                    self._send_json({"ok": True, "theme": read_wpsd_theme(wpsd_css_path)})
                    return
                if self.path == "/api/logs":
                    self._send_json({"ok": True, "log": tail_log(log_path)})
                    return
                if self.path == "/api/features":
                    self._send_json({"ok": True, "features": WPSD_WIFI_FEATURES})
                    return
                if self.path == "/api/networks":
                    self._send_json(
                        {
                            "ok": True,
                            "networks": [profile.to_dict() for profile in client.list_wifi_profiles()],
                        }
                    )
                    return
                if self.path == "/api/scan":
                    self._send_json(
                        {
                            "ok": True,
                            "access_points": [ap.to_dict() for ap in client.scan()],
                        }
                    )
                    return
            except Exception as exc:
                self._send_error_payload(exc)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.send_header("cache-control", "no-store")
            self.end_headers()

        def do_POST(self) -> None:
            client = NetworkManagerClient(interface=interface, nmcli=command)
            try:
                if self.path == "/api/networks":
                    payload = self._read_json()
                    client.add_profile(
                        str(payload.get("ssid", "")),
                        str(payload.get("password", "")),
                        profile_name=_optional_str(payload.get("profile_name")),
                        priority=_optional_int(payload.get("priority")),
                        autoconnect=bool(payload.get("autoconnect", True)),
                        connect=bool(payload.get("connect", False)),
                        hidden=bool(payload.get("hidden", False)),
                    )
                    self._send_json({"ok": True, "message": "Profile saved."})
                    return
                password_target = _password_update_target(self.path)
                if password_target is not None:
                    payload = self._read_json()
                    client.update_password(password_target, str(payload.get("password", "")))
                    self._send_json({"ok": True, "message": "Password updated."})
                    return
                if self.path.startswith("/api/connect/"):
                    client.connect(_last_path_segment(self.path))
                    self._send_json({"ok": True, "message": "Connection requested."})
                    return
                if self.path == "/api/disconnect":
                    client.disconnect()
                    self._send_json({"ok": True, "message": "Disconnect requested."})
                    return
            except Exception as exc:
                self._send_error_payload(exc)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:
            client = NetworkManagerClient(interface=interface, nmcli=command)
            try:
                if self.path.startswith("/api/networks/"):
                    uuid_or_name = _last_path_segment(self.path)
                    payload = self._read_json()
                    if "priority" in payload:
                        client.set_priority(uuid_or_name, int(payload["priority"]))
                    if "autoconnect" in payload:
                        client.set_autoconnect(uuid_or_name, bool(payload["autoconnect"]))
                    if "retries" in payload:
                        client.set_retries(uuid_or_name, int(payload["retries"]))
                    self._send_json({"ok": True, "message": "Profile updated."})
                    return
            except Exception as exc:
                self._send_error_payload(exc)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:
            client = NetworkManagerClient(interface=interface, nmcli=command)
            try:
                if self.path.startswith("/api/networks/"):
                    uuid_or_name = _last_path_segment(self.path)
                    _reject_active_forget(client, uuid_or_name)
                    client.forget(uuid_or_name)
                    self._send_json({"ok": True, "message": "Profile removed."})
                    return
            except Exception as exc:
                self._send_error_payload(exc)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), format % args)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self._send_cors_headers()
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, content_type: str) -> None:
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_cors_headers(self) -> None:
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")

        def _send_error_payload(self, exc: Exception) -> None:
            LOGGER.exception("wifi admin request failed")
            status = HTTPStatus.BAD_REQUEST
            payload: dict[str, Any] = {"ok": False, "message": str(exc)}
            if isinstance(exc, NetworkManagerError):
                payload["command"] = exc.command
                payload["stderr"] = exc.stderr
            self._send_json(payload, status)

    return WifiAdminHandler


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _last_path_segment(path: str) -> str:
    return unquote(path.rstrip("/").rsplit("/", 1)[-1])


def _password_update_target(path: str) -> str | None:
    parts = [unquote(part) for part in path.strip("/").split("/")]
    if len(parts) == 4 and parts[0] == "api" and parts[1] == "networks" and parts[3] == "password":
        return parts[2]
    return None


def _reject_active_forget(client: NetworkManagerClient, uuid_or_name: str) -> None:
    for profile in client.list_wifi_profiles():
        if profile.active and uuid_or_name in {profile.uuid, profile.name}:
            raise ValueError("refusing to remove the active Wi-Fi profile")


def main() -> int:
    parser = argparse.ArgumentParser(prog="wpsd-wifi-manager-admin")
    parser.add_argument("--host", default="0.0.0.0", help="Admin UI bind address.")
    parser.add_argument("--port", default=8093, type=int, help="Admin UI TCP port.")
    parser.add_argument("--interface", help="Wi-Fi interface, for example wlan0.")
    parser.add_argument("--wpsd-css", default=DEFAULT_WPSD_CSS_PATH, help="Path to WPSD dashboard CSS/theme INI.")
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH, help="Path to the Wi-Fi manager event log.")
    parser.add_argument("--helper-command", help="Command prefix for privileged helper, for example: sudo /opt/wpsd-wifi-manager/bin/wifi-helper")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_admin_server(args.host, args.port, args.interface, args.wpsd_css, args.log_path, args.helper_command)
    return 0


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WPSD Wi-Fi Manager</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #050708;
      --panel: #0b1012;
      --line: #253338;
      --text: #edf6f4;
      --muted: #98aaa8;
      --accent: #00c16a;
      --accent-2: #f5a524;
      --danger: #ff5c66;
      --field: #06090a;
      --banner: #020405;
      --link: #b58cff;
      --row-even: #080e12;
      --row-odd: #04080a;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    header, main { padding: 0.85rem clamp(0.75rem, 3vw, 1.4rem); }
    header { border-bottom: 1px solid var(--line); display: grid; grid-template-columns: minmax(13rem, 1fr) auto; gap: 0.8rem; align-items: center; background: var(--banner); }
    h1 { margin: 0; font-size: 1.05rem; }
    h2 { margin: 0; font-size: 0.9rem; }
    main { display: grid; gap: 0.85rem; }
    section { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; }
    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 0.7rem; padding: 0.65rem 0.8rem; border-bottom: 1px solid var(--line); background: var(--panel-2); }
    .section-body { padding: 0.75rem; }
    .workspace { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(24rem, 0.85fr); gap: 0.85rem; align-items: start; }
    .compact-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.55rem; }
    .stat { border: 1px solid var(--line); border-radius: 6px; background: var(--field); padding: 0.5rem 0.6rem; min-height: 3.2rem; }
    .stat span { display: block; color: var(--muted); font-size: 0.72rem; }
    .stat strong { display: block; margin-top: 0.2rem; font-size: 0.9rem; overflow-wrap: anywhere; }
    .network-workflow { display: grid; gap: 0.75rem; }
    .add-row { display: grid; grid-template-columns: minmax(9rem, 1.1fr) minmax(8rem, 1fr) 5.5rem auto auto auto; gap: 0.5rem; align-items: end; }
    table { width: 100%; border-collapse: collapse; min-width: 40rem; }
    th, td { border-bottom: 1px solid var(--line); padding: 0.38rem 0.45rem; text-align: left; vertical-align: middle; }
    th { color: var(--accent-2); font-size: 0.75rem; background: var(--banner); }
    tbody tr:nth-child(even) { background: var(--row-even); }
    tbody tr:nth-child(odd) { background: var(--row-odd); }
    button, input { border: 1px solid var(--line); border-radius: 6px; background: var(--field); color: var(--text); padding: 0.45rem 0.55rem; font: inherit; }
    button { cursor: pointer; font-weight: 700; }
    button.primary { border-color: #088a50; background: #047846; }
    button.danger { border-color: #8e2630; background: #621a22; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.45rem; }
    .table-wrap { overflow-x: auto; }
    label { display: grid; gap: 0.3rem; color: var(--muted); font-size: 0.78rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--field); padding: 0.75rem; margin: 0; max-height: 16rem; overflow-y: auto; }
    .muted { color: var(--muted); }
    .tiny { font-size: 0.75rem; }
    .help-text { color: var(--muted); font-size: 0.76rem; line-height: 1.35; margin: 0; }
    .clickable { cursor: pointer; }
    .clickable:hover { outline: 1px solid var(--accent); }
    .notice {
      position: fixed;
      right: 1rem;
      bottom: 1rem;
      z-index: 10;
      max-width: min(26rem, calc(100vw - 2rem));
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-2);
      color: var(--text);
      padding: 0.75rem 0.9rem;
      box-shadow: 0 0.5rem 1.5rem rgba(0,0,0,0.35);
    }
    .notice[hidden], .modal-backdrop[hidden] { display: none; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 1rem;
      background: rgba(0,0,0,0.58);
    }
    .modal {
      width: min(28rem, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 1rem 2rem rgba(0,0,0,0.4);
      overflow: hidden;
    }
    .modal-content { padding: 1rem; display: grid; gap: 0.75rem; }
    .modal-content p { margin: 0; color: var(--muted); line-height: 1.4; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 0.75rem 1rem; border-top: 1px solid var(--line); background: var(--panel-2); }
    .reconnect {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: grid;
      place-items: center;
      padding: 1rem;
      background: var(--bg);
    }
    .reconnect[hidden] { display: none; }
    .reconnect-panel {
      width: min(34rem, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 1.2rem;
      display: grid;
      gap: 0.8rem;
      box-shadow: 0 1rem 2rem rgba(0,0,0,0.4);
    }
    .spinner {
      width: 1.5rem;
      height: 1.5rem;
      border: 3px solid var(--line);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    td input[type="number"] { width: 5.5rem; }
    @media (max-width: 1100px) {
      .workspace { grid-template-columns: 1fr; }
      .compact-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .add-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 700px) {
      header { grid-template-columns: 1fr; }
      .compact-grid, .add-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>WPSD Wi-Fi Manager</h1>
      <div class="muted">Advanced NetworkManager Wi-Fi control for WPSD</div>
    </div>
    <div class="actions">
      <button onclick="refreshAll()">Refresh</button>
    </div>
  </header>
  <main>
    <section>
      <div class="section-head">
        <h2>Connection</h2>
        <span class="muted tiny" id="themeState">Theme: loading</span>
      </div>
      <div class="section-body compact-grid" id="statusCards"></div>
    </section>
    <div class="workspace">
      <section>
        <div class="section-head">
          <h2>Networks</h2>
          <div class="actions">
            <button onclick="scan()">Scan</button>
          </div>
        </div>
        <div class="section-body network-workflow">
          <p class="help-text">Select a scanned network to fill the SSID, or enter one manually. Higher priority wins when NetworkManager autoconnects or the watchdog chooses between visible saved networks. Changing networks does not reboot WPSD; association and DHCP can still take several seconds, and the browser may disconnect if the IP changes.</p>
          <div class="add-row">
            <label>SSID<input id="ssid" autocomplete="off"></label>
            <label>Password<input id="password" type="password" autocomplete="new-password"></label>
            <label>Priority<input id="priority" type="number" value="50"></label>
            <label><span><input id="hidden" type="checkbox"> Hidden</span></label>
            <label><span><input id="connectNow" type="checkbox"> Save & connect</span></label>
            <button class="primary" onclick="addNetwork()">Save</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>SSID</th><th>Signal</th><th>Channel</th><th>Security</th><th>Saved</th></tr></thead>
              <tbody id="aps"></tbody>
            </table>
          </div>
        </div>
      </section>
      <section>
        <div class="section-head">
          <h2>Saved Profiles</h2>
          <span class="muted tiny" id="profileCount">Loading</span>
        </div>
        <div class="section-body">
          <p class="help-text">Priority is a NetworkManager autoconnect score. Larger numbers are preferred; for example, home Wi-Fi 100, vehicle hotspot 75, phone hotspot 50. Retries of 0 means keep trying indefinitely.</p>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Active</th><th>Priority</th><th>Autoconnect</th><th>Retries</th><th>Actions</th></tr></thead>
              <tbody id="networks"></tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
    <section>
      <div class="section-head">
        <h2>Event Log</h2>
        <span class="muted tiny">Daily rotation, 3 days retained</span>
      </div>
      <pre id="logs">Loading log...</pre>
    </section>
  </main>
  <div id="notice" class="notice" hidden></div>
  <div id="modalBackdrop" class="modal-backdrop" hidden>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <div class="section-head">
        <h2 id="modalTitle">Confirm</h2>
      </div>
      <div class="modal-content">
        <p id="modalMessage"></p>
        <label id="modalInputWrap" hidden><span id="modalInputLabel">Value</span><input id="modalInput" type="password"></label>
      </div>
      <div class="modal-actions">
        <button id="modalCancel" type="button">Cancel</button>
        <button id="modalOk" class="primary" type="button">Continue</button>
      </div>
    </div>
  </div>
  <div id="reconnectOverlay" class="reconnect" hidden>
    <div class="reconnect-panel">
      <div class="spinner" aria-hidden="true"></div>
      <h2 id="reconnectTitle">Connecting</h2>
      <p class="help-text" id="reconnectMessage">NetworkManager is switching Wi-Fi networks. WPSD is not rebooting; Wi-Fi association and DHCP can take several seconds.</p>
      <p class="help-text" id="reconnectProbe">Waiting for the admin page to respond...</p>
    </div>
  </div>
  <script>
    const API_BASE = window.location.pathname.startsWith("/wifi")
      ? `${window.location.protocol}//${window.location.hostname}:8093/api`
      : "/api";
    let modalResolver = null;
    function setStatus(value) {
      if (typeof value === "string") {
        renderStatusCards({message: value});
      } else {
        renderStatusCards(value || {});
      }
    }
    function showNotice(message, persist = false) {
      const node = document.getElementById("notice");
      node.textContent = message;
      node.hidden = false;
      if (!persist) {
        window.clearTimeout(showNotice.timer);
        showNotice.timer = window.setTimeout(() => { node.hidden = true; }, 4500);
      }
    }
    function showDialog({title, message, okText = "Continue", input = false, inputLabel = "Value"}) {
      const backdrop = document.getElementById("modalBackdrop");
      const inputWrap = document.getElementById("modalInputWrap");
      const inputNode = document.getElementById("modalInput");
      document.getElementById("modalTitle").textContent = title;
      document.getElementById("modalMessage").textContent = message;
      document.getElementById("modalOk").textContent = okText;
      document.getElementById("modalInputLabel").textContent = inputLabel;
      inputWrap.hidden = !input;
      inputNode.value = "";
      backdrop.hidden = false;
      if (input) inputNode.focus();
      return new Promise((resolve) => { modalResolver = resolve; });
    }
    function closeDialog(value) {
      document.getElementById("modalBackdrop").hidden = true;
      if (modalResolver) modalResolver(value);
      modalResolver = null;
    }
    document.addEventListener("click", (event) => {
      if (event.target.id === "modalCancel") closeDialog(null);
      if (event.target.id === "modalOk") {
        const inputWrap = document.getElementById("modalInputWrap");
        closeDialog(inputWrap.hidden ? true : document.getElementById("modalInput").value);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !document.getElementById("modalBackdrop").hidden) closeDialog(null);
    });
    function apiUrl(path) {
      return `${API_BASE}${path}`;
    }
    async function fetchJson(path, options) {
      const url = path.startsWith("http") ? path : apiUrl(path);
      let response;
      try {
        response = await fetch(url, options);
      } catch (error) {
        throw new Error("The request did not complete. If Wi-Fi is switching, wait for WPSD to reconnect and refresh the page.");
      }
      const data = await response.json();
      if (!data.ok) throw new Error(data.message || "request failed");
      return data;
    }
    function reconnectCandidates() {
      const paths = [apiUrl("/status")];
      if (window.location.hostname !== "wpsd.local") {
        paths.push("http://wpsd.local:8093/api/status");
      }
      return [...new Set(paths)];
    }
    function showReconnectOverlay(networkName) {
      const overlay = document.getElementById("reconnectOverlay");
      document.getElementById("reconnectTitle").textContent = `Connecting to "${networkName}"`;
      document.getElementById("reconnectMessage").textContent = "NetworkManager is switching Wi-Fi networks. WPSD is not rebooting; Wi-Fi association and DHCP can take several seconds. This page will refresh when the admin service responds again.";
      overlay.hidden = false;
      pollReconnect(networkName, Date.now());
    }
    function hideReconnectOverlay() {
      document.getElementById("reconnectOverlay").hidden = true;
    }
    async function pollReconnect(networkName, startedAt) {
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      document.getElementById("reconnectProbe").textContent = `Waiting for WPSD to reconnect... ${elapsed}s`;
      for (const url of reconnectCandidates()) {
        try {
          const response = await fetch(url, {cache: "no-store"});
          const data = await response.json();
          if (data.ok && data.status && data.status.connection) {
            document.getElementById("reconnectProbe").textContent = `Connected to ${data.status.connection}. Reloading...`;
            const target = url.includes("wpsd.local") ? "http://wpsd.local/wifi/" : window.location.href;
            window.setTimeout(() => { window.location.href = target; }, 900);
            return;
          }
        } catch (error) {
          // Keep waiting while NetworkManager settles or the browser route changes.
        }
      }
      window.setTimeout(() => pollReconnect(networkName, startedAt), 4000);
    }
    async function refreshAll() {
      try {
        await loadTheme();
        const status = await fetchJson("/status");
        setStatus(status.status);
        await refreshLogs();
        const networks = await fetchJson("/networks");
        renderNetworks(networks.networks || []);
      } catch (error) {
        setStatus(`Refresh failed: ${error}`);
      }
    }
    async function loadTheme() {
      const data = await fetchJson("/theme");
      const theme = data.theme || {};
      Object.entries(theme.variables || {}).forEach(([key, value]) => {
        if (key.startsWith("--") && /^#[0-9a-fA-F]{6}$/.test(value)) {
          document.documentElement.style.setProperty(key, value);
        }
      });
      document.getElementById("themeState").textContent = theme.source === "wpsd" ? `Theme: WPSD (${theme.path})` : "Theme: fallback";
    }
    async function refreshLogs() {
      const data = await fetchJson("/logs");
      const log = data.log || {};
      const lines = log.exists ? log.lines || [] : [`No log yet at ${log.path || ""}`];
      document.getElementById("logs").textContent = lines.join("\n");
    }
    function renderStatusCards(status) {
      const node = document.getElementById("statusCards");
      node.innerHTML = "";
      const cards = [
        ["Interface", status.interface || ""],
        ["State", status.state || status.message || ""],
        ["Connected To", status.connection || status.ssid || ""],
        ["IP / Gateway", [status.ip4_address, status.gateway].filter(Boolean).join(" / ")]
      ];
      cards.forEach(([label, value]) => {
        const card = document.createElement("div");
        card.className = "stat";
        const caption = document.createElement("span");
        caption.textContent = label;
        const text = document.createElement("strong");
        text.textContent = value || "N/A";
        card.appendChild(caption);
        card.appendChild(text);
        node.appendChild(card);
      });
    }
    function renderNetworks(networks) {
      const body = document.getElementById("networks");
      body.innerHTML = "";
      document.getElementById("profileCount").textContent = `${networks.length} saved`;
      networks.forEach((network) => {
        const row = document.createElement("tr");
        appendCell(row, network.name);
        appendCell(row, network.active ? "yes" : "no");
        const priorityCell = document.createElement("td");
        const priority = document.createElement("input");
        priority.type = "number";
        priority.value = network.priority ?? "";
        priority.dataset.field = "priority";
        priorityCell.appendChild(priority);
        row.appendChild(priorityCell);
        const autoconnectCell = document.createElement("td");
        const autoconnect = document.createElement("input");
        autoconnect.type = "checkbox";
        autoconnect.checked = Boolean(network.autoconnect);
        autoconnect.dataset.field = "autoconnect";
        autoconnectCell.appendChild(autoconnect);
        row.appendChild(autoconnectCell);
        const retriesCell = document.createElement("td");
        const retries = document.createElement("input");
        retries.type = "number";
        retries.value = network.retries ?? "";
        retries.dataset.field = "retries";
        retriesCell.appendChild(retries);
        row.appendChild(retriesCell);
        const actions = document.createElement("td");
        actions.className = "actions";
        const connect = document.createElement("button");
        connect.textContent = "Connect";
        connect.onclick = () => connectNetwork(network.uuid, network.ssid || network.name);
        actions.appendChild(connect);
        const update = document.createElement("button");
        update.textContent = "Update";
        update.onclick = () => updateNetwork(network.uuid, row);
        actions.appendChild(update);
        const password = document.createElement("button");
        password.textContent = "Password";
        password.onclick = () => updatePassword(network.uuid);
        actions.appendChild(password);
        const forget = document.createElement("button");
        forget.textContent = "Forget";
        forget.className = "danger";
        forget.disabled = Boolean(network.active);
        forget.onclick = () => forgetNetwork(network.uuid, network.name);
        actions.appendChild(forget);
        row.appendChild(actions);
        body.appendChild(row);
      });
    }
    function appendCell(row, value) {
      const cell = document.createElement("td");
      cell.textContent = value ?? "";
      row.appendChild(cell);
      return cell;
    }
    async function scan() {
      setStatus("Scanning...");
      showNotice("Scanning visible Wi-Fi networks with NetworkManager...", true);
      try {
        const data = await fetchJson("/scan");
        const body = document.getElementById("aps");
        body.innerHTML = "";
        (data.access_points || []).forEach((ap) => {
          const row = document.createElement("tr");
          row.className = "clickable";
          appendCell(row, ap.ssid);
          appendCell(row, ap.signal ?? "");
          appendCell(row, ap.channel ?? "");
          appendCell(row, ap.security);
          appendCell(row, ap.saved ? "yes" : "no");
          row.onclick = () => { document.getElementById("ssid").value = ap.ssid; };
          body.appendChild(row);
        });
        const status = await fetchJson("/status");
        setStatus(status.status);
        showNotice(`Scan complete: ${(data.access_points || []).length} networks found.`);
      } catch (error) {
        setStatus(`Scan failed: ${error}`);
        showNotice(`Scan failed: ${error}`);
      }
    }
    async function addNetwork() {
      const payload = {
        ssid: document.getElementById("ssid").value,
        password: document.getElementById("password").value,
        priority: Number(document.getElementById("priority").value),
        autoconnect: true,
        connect: document.getElementById("connectNow").checked,
        hidden: document.getElementById("hidden").checked
      };
      if (payload.connect) {
        const ok = await showDialog({
          title: "Save & Connect",
          message: "NetworkManager will save this profile and try to connect. WPSD will not reboot, but association and DHCP can take several seconds. This browser may disconnect if the hotspot receives a new IP address.",
          okText: "Save & Connect"
        });
        if (!ok) return;
        showReconnectOverlay(payload.ssid || "selected network");
      }
      showNotice(payload.connect ? "Saving profile and asking NetworkManager to connect..." : "Saving Wi-Fi profile...", true);
      try {
        const data = await fetchJson("/networks", {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify(payload)
        });
        document.getElementById("password").value = "";
        setStatus(data.message);
        showNotice(payload.connect ? "Connection request sent. Waiting for NetworkManager status to update..." : data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Save failed: ${error}`);
        if (!String(error).includes("request did not complete")) hideReconnectOverlay();
        showNotice(`Save failed: ${error}`);
      }
    }
    async function connectNetwork(uuid, networkName) {
      const ok = await showDialog({
        title: "Connect Saved Profile",
        message: "NetworkManager will switch to this saved profile. WPSD will not reboot, but Wi-Fi association and DHCP can take several seconds. This browser may disconnect if the hotspot receives a new IP address.",
        okText: "Connect"
      });
      if (!ok) return;
      showReconnectOverlay(networkName || "selected network");
      showNotice("Connection request sent to NetworkManager...", true);
      try {
        const data = await fetchJson(`/connect/${encodeURIComponent(uuid)}`, {method: "POST"});
        setStatus(data.message);
        showNotice("Connection request accepted. Watching status...");
        window.setTimeout(refreshAll, 2500);
      } catch (error) {
        setStatus(`Connect failed: ${error}`);
        if (!String(error).includes("request did not complete")) hideReconnectOverlay();
        showNotice(`Connect failed: ${error}`);
      }
    }
    async function updateNetwork(uuid, row) {
      const priorityValue = row.querySelector('input[data-field="priority"]').value;
      const retriesValue = row.querySelector('input[data-field="retries"]').value;
      const payload = {
        autoconnect: row.querySelector('input[data-field="autoconnect"]').checked
      };
      if (priorityValue !== "") payload.priority = Number(priorityValue);
      if (retriesValue !== "") payload.retries = Number(retriesValue);
      try {
        const data = await fetchJson(`/networks/${encodeURIComponent(uuid)}`, {
          method: "PUT",
          headers: {"content-type": "application/json"},
          body: JSON.stringify(payload)
        });
        setStatus(data.message);
        showNotice(data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Update failed: ${error}`);
        showNotice(`Update failed: ${error}`);
      }
    }
    async function updatePassword(uuid) {
      const password = await showDialog({
        title: "Update Password",
        message: "The password will be stored in the NetworkManager profile. It is not saved in this application's config.",
        okText: "Update",
        input: true,
        inputLabel: "New Wi-Fi password"
      });
      if (password === null) return;
      showNotice("Updating NetworkManager Wi-Fi secret...", true);
      try {
        const data = await fetchJson(`/networks/${encodeURIComponent(uuid)}/password`, {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify({password})
        });
        setStatus(data.message);
        showNotice(data.message);
      } catch (error) {
        setStatus(`Password update failed: ${error}`);
        showNotice(`Password update failed: ${error}`);
      }
    }
    async function forgetNetwork(uuid, name) {
      const ok = await showDialog({
        title: "Forget Profile",
        message: `Forget saved Wi-Fi profile "${name}"? This removes the NetworkManager profile, but does not affect other networks.`,
        okText: "Forget"
      });
      if (!ok) return;
      showNotice("Removing saved NetworkManager profile...", true);
      try {
        const data = await fetchJson(`/networks/${encodeURIComponent(uuid)}`, {method: "DELETE"});
        setStatus(data.message);
        showNotice(data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Forget failed: ${error}`);
        showNotice(`Forget failed: ${error}`);
      }
    }
    refreshAll();
    setInterval(async () => {
      try {
        const status = await fetchJson("/status");
        setStatus(status.status);
        await refreshLogs();
      } catch (error) {
        setStatus(`Live refresh failed: ${error}`);
      }
    }, 5000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
