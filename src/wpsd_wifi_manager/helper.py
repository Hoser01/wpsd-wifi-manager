from __future__ import annotations

import re
import subprocess
import sys


SAFE_TOKEN_RE = re.compile(r"^[^\x00\r\n]+$")
UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,}$")


def main() -> int:
    nmcli_args = sys.argv[1:]
    if nmcli_args in (["-h"], ["--help"]):
        print("usage: wpsd-wifi-helper -- <allowed nmcli arguments>")
        return 0
    if nmcli_args[:1] == ["--"]:
        nmcli_args = nmcli_args[1:]
    validate_nmcli_args(nmcli_args)
    result = subprocess.run(["nmcli", *nmcli_args], check=False)
    return int(result.returncode)


def validate_nmcli_args(args: list[str]) -> None:
    if not args:
        raise SystemExit("missing nmcli arguments")
    if not all(_safe_token(arg) for arg in args):
        raise SystemExit("invalid control character in argument")
    if args == ["--version"]:
        return
    if _matches_read_only(args):
        return
    if _matches_wifi_scan(args):
        return
    if _matches_connection_add(args):
        return
    if _matches_connection_modify(args):
        return
    if _matches_connection_action(args):
        return
    raise SystemExit(f"operation is not allowed: {' '.join(_redact_args(args))}")


def _matches_read_only(args: list[str]) -> bool:
    if args[:3] == ["-t", "-f", "NAME,UUID,TYPE,DEVICE,AUTOCONNECT"] and args[3:] == [
        "connection",
        "show",
    ]:
        return True
    if args[:3] == ["-t", "-f", "UUID,TYPE"] and args[3:] == ["connection", "show", "--active"]:
        return True
    if args[:3] == ["-t", "-f", "DEVICE,TYPE,STATE"] and args[3:] == ["device", "status"]:
        return True
    if args[:4] == ["-g", "connection.autoconnect-priority,connection.autoconnect-retries,802-11-wireless.ssid", "connection", "show"]:
        return len(args) == 5 and _profile_ref(args[4])
    if args[:3] == ["-t", "-f", "GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY"]:
        return args[3:5] == ["device", "show"] and len(args) in {5, 6}
    if args[:3] == ["-t", "-f", "IN-USE,BSSID,SSID,CHAN,SIGNAL,SECURITY"]:
        tail = args[3:]
        return tail == ["device", "wifi", "list"] or (
            len(tail) == 5 and tail[:3] == ["device", "wifi", "list"] and tail[3] == "ifname"
        )
    return False


def _matches_wifi_scan(args: list[str]) -> bool:
    return args == ["device", "wifi", "rescan"] or (
        len(args) == 5 and args[:3] == ["device", "wifi", "rescan"] and args[3] == "ifname"
    )


def _matches_connection_add(args: list[str]) -> bool:
    return (
        len(args) == 10
        and args[:4] == ["connection", "add", "type", "wifi"]
        and args[4] == "ifname"
        and args[6] == "con-name"
        and args[8] == "ssid"
        and _interface(args[5])
        and _profile_ref(args[7])
        and _ssid(args[9])
    )


def _matches_connection_modify(args: list[str]) -> bool:
    if len(args) < 5 or args[:2] != ["connection", "modify"] or not _profile_ref(args[2]):
        return False
    pairs = args[3:]
    if len(pairs) % 2:
        return False
    allowed = {
        "wifi-sec.key-mgmt": _key_mgmt,
        "wifi-sec.psk": _secret,
        "802-11-wireless-security.psk": _secret,
        "802-11-wireless.hidden": _yes_no,
        "connection.autoconnect": _yes_no,
        "connection.autoconnect-priority": _int_value,
        "connection.autoconnect-retries": _int_value,
    }
    for key, value in zip(pairs[0::2], pairs[1::2]):
        validator = allowed.get(key)
        if validator is None or not validator(value):
            return False
    return True


def _matches_connection_action(args: list[str]) -> bool:
    if len(args) == 3 and tuple(args[:2]) in {("connection", "up"), ("connection", "delete")}:
        return _profile_ref(args[2])
    if len(args) == 3 and args[:2] == ["device", "disconnect"]:
        return _interface(args[2])
    return False


def _safe_token(value: str) -> bool:
    return bool(value) and bool(SAFE_TOKEN_RE.match(value))


def _profile_ref(value: str) -> bool:
    return _safe_token(value) and len(value) <= 128


def _ssid(value: str) -> bool:
    return _safe_token(value) and len(value.encode("utf-8")) <= 32


def _interface(value: str) -> bool:
    return value == "*" or bool(re.match(r"^[A-Za-z0-9_.:-]{1,32}$", value))


def _yes_no(value: str) -> bool:
    return value in {"yes", "no"}


def _key_mgmt(value: str) -> bool:
    return value in {"wpa-psk"}


def _int_value(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _secret(value: str) -> bool:
    return _safe_token(value) and len(value) <= 256


def _redact_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    secret_keys = {"wifi-sec.psk", "802-11-wireless-security.psk", "password"}
    for arg in args:
        if redact_next:
            redacted.append("[redacted]")
            redact_next = False
        else:
            redacted.append(arg)
            redact_next = arg in secret_keys
    return redacted


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
