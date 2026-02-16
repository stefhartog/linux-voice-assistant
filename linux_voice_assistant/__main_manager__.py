#!/usr/bin/env python3
"""Device manager entrypoint."""

import argparse
import asyncio
import json
import logging
import os
import platform
from pathlib import Path

from .device_manager import DeviceManager, DeviceManagerProtocol, ManagerConfig
from .util import get_mac
from .zeroconf import HomeAssistantZeroconf

_LOGGER = logging.getLogger(__name__)
_MODULE_DIR = Path(__file__).parent
_REPO_DIR = _MODULE_DIR.parent


def _normalize_mac(mac: str) -> str:
    return mac.replace(":", "").lower()


def _get_system_info() -> dict:
    info = {
        "os": platform.system(),
        "machine": platform.machine(),
        "architecture": platform.architecture()[0],
    }
    return info


def _load_cli_config(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj) or {}
    except Exception:
        return {}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6152)
    parser.add_argument("--mac")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--refresh-seconds", type=float, default=10.0)

    args, _ = parser.parse_known_args()

    prefs_dir = _REPO_DIR / "preferences" / "user"
    cli_path = prefs_dir / f"{args.name}_manager.json"
    legacy_cli_path = prefs_dir / f"{args.name}_manager_cli.json"
    cli_config = {}
    if cli_path.exists():
        cli_config = _load_cli_config(cli_path)
    elif legacy_cli_path.exists():
        cli_config = _load_cli_config(legacy_cli_path)
    if cli_config:
        defaults = {k.replace("_", "-"): v for k, v in cli_config.items() if not k.startswith("_")}
        parser.set_defaults(**defaults)

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug("Manager args: %s", args)

    mac = args.mac or get_mac()
    manager_name = f"{args.name} Manager"

    config = ManagerConfig(
        name=manager_name,
        base_name=args.name,
        mac_address=mac,
        prefs_dir=prefs_dir,
        refresh_seconds=args.refresh_seconds,
        restart_script=_REPO_DIR / "script" / "restart",
        deploy_script=_REPO_DIR / "script" / "deploy",
        manager_service=f"{args.name}_manager.service",
        remove_script=_REPO_DIR / "script" / "remove",
    )

    manager = DeviceManager(config)
    manager.start_updates()

    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: DeviceManagerProtocol(manager), host=args.host, port=args.port
    )

    zeroconf = HomeAssistantZeroconf(
        port=args.port,
        name=manager_name,
        mac=_normalize_mac(mac),
    )
    await zeroconf.register_server()

    try:
        async with server:
            _LOGGER.info("Manager started (host=%s, port=%s)", args.host, args.port)
            await server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
