"""ESPHome device manager protocol and metrics."""

import asyncio
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    ButtonCommandRequest,
    DeviceInfoRequest,
    DeviceInfoResponse,
    ListEntitiesRequest,
    ListEntitiesDoneResponse,
    SelectCommandRequest,
    SubscribeHomeAssistantStatesRequest,
    SwitchCommandRequest,
)
from google.protobuf import message

from .api_server import APIServer
from .bluetooth import BlueZHelper
from .entity import ButtonEntity, ESPHomeEntity, SelectEntity, SwitchEntity, TextAttributeEntity

_LOGGER = logging.getLogger(__name__)


@dataclass
class ManagerConfig:
    name: str
    base_name: str
    mac_address: str
    prefs_dir: Path
    refresh_seconds: float
    restart_script: Path
    deploy_script: Path
    manager_service: str
    remove_script: Path


class DeviceManager:
    def __init__(self, config: ManagerConfig) -> None:
        self.config = config
        self.entities: List[ESPHomeEntity] = []
        self.protocol: Optional[DeviceManagerProtocol] = None
        self._cpu_totals: Optional[tuple[int, int]] = None
        self._instance_switches: Dict[str, SwitchEntity] = {}
        self._instance_status_sensors: Dict[str, TextAttributeEntity] = {}
        self._instance_remove_buttons: Dict[str, ButtonEntity] = {}
        self._mute_switch: Optional[SwitchEntity] = None
        self._bluetooth_helper: Optional[BlueZHelper] = None
        self._bluetooth_devices_text = ""
        self._bluetooth_refresh_at = 0.0
        self._bluetooth_device_select: Optional[SelectEntity] = None
        self._bluetooth_device_options: List[str] = ["none"]
        self._bluetooth_device_map: Dict[str, str] = {}

        self.cpu_sensor = self._add_text("System CPU", "system_cpu")
        self.temp_sensor = self._add_text("System Temp", "system_temp")
        self.mem_sensor = self._add_text("System Memory", "system_memory")
        self.disk_sensor = self._add_text("System Disk", "system_disk")
        self.squeezelite_sensor = self._add_text("Squeezelite Status", "squeezelite_status")
        self.led_feedback_sensor = self._add_text("LED Feedback Status", "led_feedback_status")
        self.bluetooth_devices_sensor = self._add_text(
            "Bluetooth Devices", "bluetooth_devices"
        )

        self.restart_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Restart All VA",
            object_id="va_restart",
            on_press=self._restart_services,
            icon="mdi:restart",
        )
        self.entities.append(self.restart_button)

        self.deploy_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Deploy New VA",
            object_id="va_deploy",
            on_press=self._deploy_new_instance,
            icon="mdi:plus-box",
        )
        self.entities.append(self.deploy_button)

        self.bluetooth_scan_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Bluetooth Scan",
            object_id="bluetooth_scan",
            on_press=self._scan_bluetooth,
            icon="mdi:bluetooth",
        )
        self.entities.append(self.bluetooth_scan_button)

        self.bluetooth_refresh_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Bluetooth Refresh",
            object_id="bluetooth_refresh",
            on_press=self._refresh_bluetooth,
            icon="mdi:bluetooth-settings",
        )
        self.entities.append(self.bluetooth_refresh_button)

        self._add_bluetooth_select()

        self.bluetooth_forget_all_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Bluetooth Forget All",
            object_id="bluetooth_forget_all",
            on_press=self._forget_all_bluetooth,
            icon="mdi:bluetooth-off",
        )
        self.entities.append(self.bluetooth_forget_all_button)

        self._add_mute_switch()

        self.restart_manager_button = ButtonEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Restart Manager",
            object_id="manager_restart",
            on_press=self._restart_manager,
            icon="mdi:restart",
        )
        self.entities.append(self.restart_manager_button)

        self._add_instance_switches()
        self._add_instance_status_sensors()
        self._add_instance_remove_buttons()

    def _add_text(self, name: str, object_id: str) -> TextAttributeEntity:
        sensor = TextAttributeEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name=name,
            object_id=object_id,
        )
        self.entities.append(sensor)
        return sensor

    def attach_protocol(self, protocol: "DeviceManagerProtocol") -> None:
        self.protocol = protocol

    def detach_protocol(self, protocol: "DeviceManagerProtocol") -> None:
        if self.protocol is protocol:
            self.protocol = None

    def start_updates(self) -> None:
        asyncio.create_task(self._update_loop())
        asyncio.create_task(self._autoconnect_bluetooth_audio())

    async def _update_loop(self) -> None:
        while True:
            try:
                self.refresh()
            except Exception:
                _LOGGER.exception("Manager refresh failed")
            await asyncio.sleep(self.config.refresh_seconds)

    def refresh(self) -> None:
        messages = []
        messages.append(self.cpu_sensor.update(self._cpu_usage()))
        messages.append(self.temp_sensor.update(self._temp_c()))
        messages.append(self.mem_sensor.update(self._mem_usage()))
        messages.append(self.disk_sensor.update(self._disk_usage()))
        messages.append(self.squeezelite_sensor.update(_systemd_unit_status("squeezelite.service")))
        messages.append(self.led_feedback_sensor.update(_systemd_unit_status("led_feedback.service")))
        messages.append(self.bluetooth_devices_sensor.update(self._bluetooth_devices_text or "n/a"))
        messages.extend(self._refresh_bluetooth_select())
        messages.extend(self._refresh_instance_status_sensors())
        messages.extend(self._refresh_instance_switches())
        self._add_instance_remove_buttons()
        messages.extend(self._refresh_mute_switch())

        if self.protocol is not None:
            self.protocol.send_messages(messages)

    def _cpu_usage(self) -> str:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as stat_file:
                fields = stat_file.readline().split()
            if fields[0] != "cpu":
                return "n/a"
            values = [int(val) for val in fields[1:]]
            total = sum(values)
            idle = values[3] + values[4] if len(values) > 4 else values[3]
            if self._cpu_totals is None:
                self._cpu_totals = (total, idle)
                return "0%"
            last_total, last_idle = self._cpu_totals
            self._cpu_totals = (total, idle)
            total_delta = total - last_total
            idle_delta = idle - last_idle
            if total_delta <= 0:
                return "0%"
            usage = (1.0 - (idle_delta / total_delta)) * 100.0
            return f"{usage:.1f}%"
        except Exception:
            return "n/a"

    def _temp_c(self) -> str:
        for path in (
            Path("/sys/class/thermal/thermal_zone0/temp"),
            Path("/sys/class/thermal/thermal_zone1/temp"),
        ):
            if path.exists():
                try:
                    raw = path.read_text(encoding="utf-8").strip()
                    temp_c = int(raw) / 1000.0
                    return f"{temp_c:.1f}C"
                except Exception:
                    continue
        return "n/a"

    def _mem_usage(self) -> str:
        try:
            total = None
            available = None
            with open("/proc/meminfo", "r", encoding="utf-8") as meminfo:
                for line in meminfo:
                    if line.startswith("MemTotal"):
                        total = int(line.split()[1])
                    elif line.startswith("MemAvailable"):
                        available = int(line.split()[1])
            if total is None or available is None:
                return "n/a"
            used = total - available
            percent = (used / total) * 100.0
            return f"{percent:.1f}%"
        except Exception:
            return "n/a"

    def _disk_usage(self) -> str:
        try:
            usage = shutil.disk_usage("/")
            percent = (usage.used / usage.total) * 100.0
            return f"{percent:.1f}%"
        except Exception:
            return "n/a"

    def _iter_instance_cli_files(self) -> List[Path]:
        return sorted(
            [
                path
                for path in self.config.prefs_dir.glob("*_cli.json")
                if not path.stem.endswith("_manager_cli")
            ]
        )

    def _add_instance_status_sensors(self) -> None:
        for cli_file in self._iter_instance_cli_files():
            name = cli_file.stem.replace("_cli", "")
            if name in self._instance_status_sensors:
                continue
            sensor = self._add_text(
                f"{name} Status",
                f"{_slugify(name)}_status",
            )
            self._instance_status_sensors[name] = sensor

    def _refresh_instance_status_sensors(self) -> List[message.Message]:
        self._add_instance_status_sensors()
        muted = self._read_shared_mute()
        messages: List[message.Message] = []
        for name, sensor in self._instance_status_sensors.items():
            status = _systemd_status(name)
            if muted:
                status = f"{status} / Muted"
            messages.append(sensor.update(status))
        return messages

    def _add_instance_switches(self) -> None:
        for cli_file in self._iter_instance_cli_files():
            name = cli_file.stem.replace("_cli", "")
            if name in self._instance_switches:
                continue
            initial = _load_autostart(cli_file)
            switch = SwitchEntity(
                server=self,  # type: ignore[arg-type]
                key=len(self.entities),
                name=f"{name} Autostart",
                object_id=f"{_slugify(name)}_autostart",
                initial_state=initial,
                on_change=lambda state, target=name: self._set_autostart(target, state),
                icon="mdi:power",
            )
            self.entities.append(switch)
            self._instance_switches[name] = switch

    def _add_instance_remove_buttons(self) -> None:
        for cli_file in self._iter_instance_cli_files():
            name = cli_file.stem.replace("_cli", "")
            if name in self._instance_remove_buttons:
                continue
            button = ButtonEntity(
                server=self,  # type: ignore[arg-type]
                key=len(self.entities),
                name=f"{name} Remove",
                object_id=f"{_slugify(name)}_remove",
                on_press=lambda target=name: self._remove_instance(target),
                icon="mdi:trash-can-outline",
            )
            self.entities.append(button)
            self._instance_remove_buttons[name] = button

    def _add_mute_switch(self) -> None:
        if self._mute_switch is not None:
            return
        initial = self._read_shared_mute()
        self._mute_switch = SwitchEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Mute all VA",
            object_id="va_mute_all",
            initial_state=initial,
            on_change=self._set_shared_mute,
            icon="mdi:microphone-off",
        )
        self.entities.append(self._mute_switch)

    def _refresh_mute_switch(self) -> List[message.Message]:
        if self._mute_switch is None:
            return []
        desired = self._read_shared_mute()
        if desired != self._mute_switch.state:
            return [self._mute_switch.set_state(desired)]
        return []

    def _add_bluetooth_select(self) -> None:
        if self._bluetooth_device_select is not None:
            return
        self._bluetooth_device_select = SelectEntity(
            server=self,  # type: ignore[arg-type]
            key=len(self.entities),
            name="Bluetooth Device",
            object_id="bluetooth_device",
            options=self._bluetooth_device_options,
            initial_state="none",
            on_change=self._pair_selected_bluetooth,
        )
        self.entities.append(self._bluetooth_device_select)

    def _refresh_bluetooth_select(self) -> List[message.Message]:
        if self._bluetooth_device_select is None:
            return []
        if self._bluetooth_device_select.options != self._bluetooth_device_options:
            self._bluetooth_device_select.options = list(self._bluetooth_device_options)
        if self._bluetooth_device_select.state not in self._bluetooth_device_options:
            return [self._bluetooth_device_select.set_state("none")]
        return []

    def _scan_bluetooth(self) -> None:
        asyncio.create_task(self._scan_and_refresh_bluetooth())

    def _refresh_bluetooth(self) -> None:
        asyncio.create_task(self._update_bluetooth_devices())

    def _forget_all_bluetooth(self) -> None:
        asyncio.create_task(self._forget_all_devices())

    def _pair_selected_bluetooth(self, option: str) -> None:
        if option == "none":
            return
        device_path = self._bluetooth_device_map.get(option)
        if not device_path:
            _LOGGER.warning("Bluetooth selection not found: %s", option)
            return
        asyncio.create_task(self._pair_selected_device(device_path))

    def _refresh_instance_switches(self) -> List[message.Message]:
        messages: List[message.Message] = []
        for cli_file in self._iter_instance_cli_files():
            name = cli_file.stem.replace("_cli", "")
            switch = self._instance_switches.get(name)
            if switch is None:
                continue
            current = _load_autostart(cli_file)
            if current != switch.state:
                messages.append(switch.set_state(current))
        return messages

    def _set_autostart(self, name: str, enabled: bool) -> None:
        cli_path = self.config.prefs_dir / f"{name}_cli.json"
        if not cli_path.exists():
            raise FileNotFoundError(f"Missing CLI config: {cli_path}")
        data = _load_json(cli_path)
        data["autostart"] = enabled
        cli_path.write_text(_dump_json(data), encoding="utf-8")
        _LOGGER.info("Updated autostart for %s to %s", name, enabled)

    def _remove_instance(self, name: str) -> None:
        _LOGGER.info("Removing VA instance: %s", name)
        try:
            subprocess.Popen(
                [str(self.config.remove_script), "--yes", "--no-stop", name]
            )
        except Exception:
            _LOGGER.exception("Failed to remove VA instance: %s", name)

    def _set_shared_mute(self, enabled: bool) -> None:
        _LOGGER.info("Setting shared mute: %s", enabled)
        try:
            self._shared_mute_path().write_text(
                "on" if enabled else "off", encoding="utf-8"
            )
        except Exception:
            _LOGGER.exception("Failed to write shared mute flag")

    def _restart_services(self) -> None:
        _LOGGER.info("Restarting VA services via %s", self.config.restart_script)
        try:
            subprocess.Popen([str(self.config.restart_script)])
        except Exception:
            _LOGGER.exception("Failed to restart VA services")

    def _deploy_new_instance(self) -> None:
        try:
            name = self._next_instance_name()
        except Exception:
            _LOGGER.exception("No available instance name for auto-deploy")
            return
        _LOGGER.info("Deploying new VA instance: %s", name)
        try:
            subprocess.Popen([str(self.config.deploy_script), name])
            asyncio.create_task(self._restart_manager_after_delay(3.0))
        except Exception:
            _LOGGER.exception("Failed to deploy VA instance: %s", name)

    def _next_instance_name(self) -> str:
        used = {path.stem.replace("_cli", "") for path in self._iter_instance_cli_files()}
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            candidate = f"{self.config.base_name}_{letter}"
            if candidate not in used:
                return candidate
        raise ValueError("No available instance name")

    def _read_shared_mute(self) -> bool:
        try:
            path = self._shared_mute_path()
            if not path.exists():
                return False
            txt = path.read_text(encoding="utf-8").strip().lower()
            return txt.startswith("on") or txt.startswith("true")
        except Exception:
            _LOGGER.debug("Failed to read shared mute flag", exc_info=True)
            return False

    def _shared_mute_path(self) -> Path:
        return Path("/dev/shm/lvas_system_mute")

    def _restart_manager(self) -> None:
        _LOGGER.info("Restarting manager service: %s", self.config.manager_service)
        try:
            subprocess.Popen(
                ["systemctl", "--user", "restart", self.config.manager_service]
            )
        except Exception:
            _LOGGER.exception("Failed to restart manager service")

    async def _ensure_bluetooth(self) -> Optional[BlueZHelper]:
        if self._bluetooth_helper is not None:
            return self._bluetooth_helper
        try:
            self._bluetooth_helper = await BlueZHelper.create()
            return self._bluetooth_helper
        except Exception:
            _LOGGER.exception("Failed to initialize BlueZ helper")
            return None

    async def _scan_and_refresh_bluetooth(self) -> None:
        helper = await self._ensure_bluetooth()
        if helper is None:
            self._bluetooth_devices_text = "unavailable"
            return
        try:
            await helper.scan(8.0)
        except Exception:
            _LOGGER.exception("Bluetooth scan failed")
        await self._update_bluetooth_devices(force=True)

    async def _pair_selected_device(self, device_path: str) -> None:
        helper = await self._ensure_bluetooth()
        if helper is None:
            self._bluetooth_devices_text = "unavailable"
            return
        try:
            await helper.pair_trust_connect(device_path)
        except Exception:
            _LOGGER.exception("Bluetooth pair/connect failed")
        await self._update_bluetooth_devices(force=True)

    async def _update_bluetooth_devices(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._bluetooth_refresh_at:
            return
        helper = await self._ensure_bluetooth()
        if helper is None:
            self._bluetooth_devices_text = "unavailable"
            return
        try:
            device_entries = await helper.list_devices_with_paths(audio_only=True)
            devices = [info for _, info in device_entries]
            self._bluetooth_devices_text = _format_bt_devices(devices)
            options: List[str] = ["none"]
            mapping: Dict[str, str] = {}
            for path, info in device_entries:
                option = f"{info.name} [{info.address}]"
                options.append(option)
                mapping[option] = path
            self._bluetooth_device_options = options
            self._bluetooth_device_map = mapping
        except Exception:
            _LOGGER.exception("Bluetooth device list failed")
            self._bluetooth_devices_text = "unavailable"
        self._bluetooth_refresh_at = now + 5.0

    async def _forget_all_devices(self) -> None:
        helper = await self._ensure_bluetooth()
        if helper is None:
            self._bluetooth_devices_text = "unavailable"
            return
        try:
            device_entries = await helper.list_devices_with_paths(audio_only=True)
            for path, info in device_entries:
                if info.paired or info.connected:
                    await helper.remove_device(path)
        except Exception:
            _LOGGER.exception("Bluetooth forget all failed")
        await self._update_bluetooth_devices(force=True)

    async def _restart_manager_after_delay(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        self._restart_manager()

    async def _autoconnect_bluetooth_audio(self) -> None:
        await asyncio.sleep(2.0)
        helper = await self._ensure_bluetooth()
        if helper is None:
            return
        try:
            device_entries = await helper.list_devices_with_paths(audio_only=True)
            for path, info in device_entries:
                if info.paired and not info.connected:
                    try:
                        await helper.connect_device(path)
                    except Exception:
                        _LOGGER.exception(
                            "Bluetooth autoconnect failed: %s", info.address
                        )
        except Exception:
            _LOGGER.exception("Bluetooth autoconnect failed")


class DeviceManagerProtocol(APIServer):
    def __init__(self, manager: DeviceManager) -> None:
        super().__init__(manager.config.name)
        self.manager = manager

    def connection_made(self, transport) -> None:
        super().connection_made(transport)
        self.manager.attach_protocol(self)

    def connection_lost(self, exc) -> None:
        super().connection_lost(exc)
        self.manager.detach_protocol(self)

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, DeviceInfoRequest):
            return [
                DeviceInfoResponse(
                    uses_password=False,
                    name=self.manager.config.name,
                    mac_address=self.manager.config.mac_address,
                    voice_assistant_feature_flags=0,
                )
            ]

        if isinstance(
            msg,
            (
                ListEntitiesRequest,
                SubscribeHomeAssistantStatesRequest,
                ButtonCommandRequest,
                SelectCommandRequest,
                SwitchCommandRequest,
            ),
        ):
            messages: List[message.Message] = []
            for entity in self.manager.entities:
                entity_messages = list(entity.handle_message(msg) or [])
                messages.extend(entity_messages)
            if isinstance(msg, ListEntitiesRequest):
                messages.append(ListEntitiesDoneResponse())
            return messages

        return []


def _load_json(path: Path) -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return _load_json_from_str(file_obj.read())
    except Exception:
        return {}


def _load_json_from_str(data: str) -> Dict:
    import json

    try:
        return json.loads(data) or {}
    except Exception:
        return {}


def _dump_json(data: Dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=4)


def _load_autostart(path: Path) -> bool:
    config = _load_json(path)
    return bool(config.get("autostart"))


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())
    return cleaned.strip("_") or "instance"


def _systemd_status(name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", f"{name}.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        status = result.stdout.strip() or result.stderr.strip()
        return status if status else "unknown"
    except Exception:
        return "unknown"


def _systemd_unit_status(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            check=False,
        )
        status = result.stdout.strip() or result.stderr.strip()
        return status if status else "unknown"
    except Exception:
        return "unknown"


def _format_bt_devices(devices: List["BluetoothDeviceInfo"]) -> str:
    if not devices:
        return "none"
    parts = []
    for device in devices:
        flags = []
        if device.connected:
            flags.append("connected")
        if device.paired:
            flags.append("paired")
        suffix = f" ({', '.join(flags)})" if flags else ""
        parts.append(f"{device.name} [{device.address}]{suffix}")
    return ", ".join(parts)
