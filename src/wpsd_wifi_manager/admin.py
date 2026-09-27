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
    header, main { padding: 1rem clamp(1rem, 4vw, 2rem); }
    header { border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; gap: 1rem; align-items: center; background: var(--banner); }
    h1 { margin: 0; font-size: 1.1rem; }
    h2 { margin: 0 0 0.75rem; font-size: 0.95rem; }
    main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(18rem, 24rem); gap: 1rem; }
    section { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 1rem; }
    .stack { display: grid; gap: 1rem; }
    table { width: 100%; border-collapse: collapse; min-width: 42rem; }
    th, td { border-bottom: 1px solid var(--line); padding: 0.45rem; text-align: left; }
    th { color: var(--accent-2); font-size: 0.75rem; background: var(--banner); }
    tbody tr:nth-child(even) { background: var(--row-even); }
    tbody tr:nth-child(odd) { background: var(--row-odd); }
    button, input { border: 1px solid var(--line); border-radius: 6px; background: var(--field); color: var(--text); padding: 0.5rem 0.65rem; font: inherit; }
    button { cursor: pointer; font-weight: 700; }
    button.primary { border-color: #088a50; background: #047846; }
    button.danger { border-color: #8e2630; background: #621a22; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .table-wrap { overflow-x: auto; }
    .form { display: grid; gap: 0.6rem; }
    label { display: grid; gap: 0.3rem; color: var(--muted); font-size: 0.78rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--field); padding: 0.75rem; min-height: 7rem; }
    .muted { color: var(--muted); }
    .live-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .tiny { font-size: 0.75rem; }
    td input[type="number"] { width: 5.5rem; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>WPSD Wi-Fi Manager</h1>
      <div class="muted">Saved NetworkManager profiles and hotspot failover foundation</div>
    </div>
    <div class="actions">
      <button onclick="refreshAll()">Refresh</button>
      <button class="primary" onclick="scan()">Scan</button>
    </div>
  </header>
  <main>
    <div class="stack">
      <section>
        <h2>Live</h2>
        <div class="live-grid">
          <pre id="status">Loading...</pre>
          <pre id="logs">Loading log...</pre>
        </div>
        <div class="muted tiny" id="themeState">Theme: loading</div>
      </section>
      <section>
        <h2>Saved Networks</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Active</th><th>Priority</th><th>Autoconnect</th><th>Retries</th><th>Actions</th></tr></thead>
            <tbody id="networks"></tbody>
          </table>
        </div>
      </section>
      <section>
        <h2>Visible Networks</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>SSID</th><th>Signal</th><th>Channel</th><th>Security</th><th>Saved</th></tr></thead>
            <tbody id="aps"></tbody>
          </table>
        </div>
      </section>
    </div>
    <div class="stack">
      <section>
        <h2>Add Network</h2>
        <div class="form">
          <label>SSID<input id="ssid"></label>
          <label>Password<input id="password" type="password"></label>
          <label>Priority<input id="priority" type="number" value="50"></label>
          <label><span><input id="hidden" type="checkbox"> Hidden network</span></label>
          <label><span><input id="connectNow" type="checkbox"> Save & Connect</span></label>
          <button class="primary" onclick="addNetwork()">Save Profile</button>
        </div>
      </section>
      <section>
        <h2>Feature Coverage</h2>
        <ul id="features" class="muted"></ul>
      </section>
    </div>
  </main>
  <script>
    function setStatus(value) {
      document.getElementById("status").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }
    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!data.ok) throw new Error(data.message || "request failed");
      return data;
    }
    async function refreshAll() {
      try {
        await loadTheme();
        const status = await fetchJson("/api/status");
        setStatus(status.status);
        await refreshLogs();
        await loadFeatures();
        const networks = await fetchJson("/api/networks");
        renderNetworks(networks.networks || []);
      } catch (error) {
        setStatus(`Refresh failed: ${error}`);
      }
    }
    async function loadTheme() {
      const data = await fetchJson("/api/theme");
      const theme = data.theme || {};
      Object.entries(theme.variables || {}).forEach(([key, value]) => {
        if (key.startsWith("--") && /^#[0-9a-fA-F]{6}$/.test(value)) {
          document.documentElement.style.setProperty(key, value);
        }
      });
      document.getElementById("themeState").textContent = theme.source === "wpsd" ? `Theme: WPSD (${theme.path})` : "Theme: fallback";
    }
    async function refreshLogs() {
      const data = await fetchJson("/api/logs");
      const log = data.log || {};
      const lines = log.exists ? log.lines || [] : [`No log yet at ${log.path || ""}`];
      document.getElementById("logs").textContent = lines.join("\n");
    }
    async function loadFeatures() {
      const data = await fetchJson("/api/features");
      const list = document.getElementById("features");
      list.innerHTML = "";
      (data.features || []).forEach((feature) => {
        const item = document.createElement("li");
        item.textContent = feature;
        list.appendChild(item);
      });
    }
    function renderNetworks(networks) {
      const body = document.getElementById("networks");
      body.innerHTML = "";
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
        connect.onclick = () => connectNetwork(network.uuid);
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
      try {
        const data = await fetchJson("/api/scan");
        const body = document.getElementById("aps");
        body.innerHTML = "";
        (data.access_points || []).forEach((ap) => {
          const row = document.createElement("tr");
          appendCell(row, ap.ssid);
          appendCell(row, ap.signal ?? "");
          appendCell(row, ap.channel ?? "");
          appendCell(row, ap.security);
          appendCell(row, ap.saved ? "yes" : "no");
          row.onclick = () => { document.getElementById("ssid").value = ap.ssid; };
          body.appendChild(row);
        });
        setStatus(`Found ${(data.access_points || []).length} access points.`);
      } catch (error) {
        setStatus(`Scan failed: ${error}`);
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
      if (payload.connect && !confirm("Changing Wi-Fi networks may disconnect this browser session. Continue?")) return;
      try {
        const data = await fetchJson("/api/networks", {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify(payload)
        });
        document.getElementById("password").value = "";
        setStatus(data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Save failed: ${error}`);
      }
    }
    async function connectNetwork(uuid) {
      if (!confirm("Changing Wi-Fi networks may disconnect this browser session. Continue?")) return;
      try {
        const data = await fetchJson(`/api/connect/${encodeURIComponent(uuid)}`, {method: "POST"});
        setStatus(data.message);
      } catch (error) {
        setStatus(`Connect failed: ${error}`);
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
        const data = await fetchJson(`/api/networks/${encodeURIComponent(uuid)}`, {
          method: "PUT",
          headers: {"content-type": "application/json"},
          body: JSON.stringify(payload)
        });
        setStatus(data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Update failed: ${error}`);
      }
    }
    async function updatePassword(uuid) {
      const password = prompt("Enter the new Wi-Fi password for this profile.");
      if (password === null) return;
      try {
        const data = await fetchJson(`/api/networks/${encodeURIComponent(uuid)}/password`, {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify({password})
        });
        setStatus(data.message);
      } catch (error) {
        setStatus(`Password update failed: ${error}`);
      }
    }
    async function forgetNetwork(uuid, name) {
      if (!confirm(`Forget saved Wi-Fi profile "${name}"?`)) return;
      try {
        const data = await fetchJson(`/api/networks/${encodeURIComponent(uuid)}`, {method: "DELETE"});
        setStatus(data.message);
        refreshAll();
      } catch (error) {
        setStatus(`Forget failed: ${error}`);
      }
    }
    refreshAll();
    setInterval(async () => {
      try {
        const status = await fetchJson("/api/status");
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
