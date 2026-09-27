from __future__ import annotations

import argparse
import json
import logging

from .network_manager import NetworkManagerClient, access_points_to_json, profiles_to_json


def main() -> int:
    parser = argparse.ArgumentParser(prog="wpsd-wifi-manager")
    parser.add_argument("--interface", help="Wi-Fi interface, for example wlan0.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("profiles", help="List saved NetworkManager Wi-Fi profiles.")
    scan_parser = subparsers.add_parser("scan", help="Scan visible Wi-Fi networks.")
    scan_parser.add_argument("--no-rescan", action="store_true", help="Use cached scan results.")
    subparsers.add_parser("status", help="Show current Wi-Fi status.")

    connect_parser = subparsers.add_parser("connect", help="Connect a saved profile.")
    connect_parser.add_argument("uuid_or_name")

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = NetworkManagerClient(interface=args.interface)
    if args.command == "profiles":
        print(profiles_to_json(client.list_wifi_profiles()))
        return 0
    if args.command == "scan":
        print(access_points_to_json(client.scan(rescan=not args.no_rescan)))
        return 0
    if args.command == "status":
        print(json.dumps(client.status().to_dict(), indent=2))
        return 0
    if args.command == "connect":
        client.connect(args.uuid_or_name)
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
