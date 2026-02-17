"""BlueZ D-Bus helper for Bluetooth device discovery and listing."""

import asyncio
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType


@dataclass
class BluetoothDeviceInfo:
    address: str
    name: str
    paired: bool
    connected: bool


class BlueZHelper:
    def __init__(self, bus, object_manager, adapter_iface, adapter_path: str) -> None:
        self._bus = bus
        self._object_manager = object_manager
        self._adapter_iface = adapter_iface
        self._adapter_path = adapter_path

    @classmethod
    async def create(cls, adapter_path: str = "/org/bluez/hci0") -> "BlueZHelper":
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        root = await bus.introspect("org.bluez", "/")
        root_obj = bus.get_proxy_object("org.bluez", "/", root)
        object_manager = root_obj.get_interface("org.freedesktop.DBus.ObjectManager")

        adapter_introspect = await bus.introspect("org.bluez", adapter_path)
        adapter_obj = bus.get_proxy_object(
            "org.bluez", adapter_path, adapter_introspect
        )
        adapter_iface = adapter_obj.get_interface("org.bluez.Adapter1")

        return cls(bus, object_manager, adapter_iface, adapter_path)

    async def scan(self, duration_seconds: float = 8.0) -> None:
        try:
            await self._adapter_iface.call_start_discovery()
            await asyncio.sleep(duration_seconds)
        finally:
            try:
                await self._adapter_iface.call_stop_discovery()
            except Exception:
                pass

    async def list_devices(self, audio_only: bool = False) -> List[BluetoothDeviceInfo]:
        entries = await self.list_devices_with_paths(audio_only=audio_only)
        return [info for _, info in entries]

    async def list_devices_with_paths(
        self, audio_only: bool = False
    ) -> List[Tuple[str, BluetoothDeviceInfo]]:
        devices: List[Tuple[str, BluetoothDeviceInfo]] = []
        objects = await self._object_manager.call_get_managed_objects()
        for path, interfaces in objects.items():
            device = interfaces.get("org.bluez.Device1")
            if not device:
                continue
            if audio_only and not _has_audio_uuid(device):
                continue
            address = _variant_value(device.get("Address"))
            name = _variant_value(device.get("Alias")) or _variant_value(device.get("Name"))
            paired = bool(_variant_value(device.get("Paired")))
            connected = bool(_variant_value(device.get("Connected")))
            if not address:
                continue
            devices.append(
                (
                    path,
                    BluetoothDeviceInfo(
                        address=address,
                        name=name or address,
                        paired=paired,
                        connected=connected,
                    ),
                )
            )
        return devices

    async def get_connected_device(
        self, audio_only: bool = True
    ) -> Optional[Tuple[str, BluetoothDeviceInfo]]:
        objects = await self._object_manager.call_get_managed_objects()
        for path, interfaces in objects.items():
            device = interfaces.get("org.bluez.Device1")
            if not device:
                continue
            if audio_only and not _has_audio_uuid(device):
                continue
            connected = bool(_variant_value(device.get("Connected")))
            if not connected:
                continue
            address = _variant_value(device.get("Address"))
            name = _variant_value(device.get("Alias")) or _variant_value(device.get("Name"))
            paired = bool(_variant_value(device.get("Paired")))
            if not address:
                continue
            info = BluetoothDeviceInfo(
                address=address,
                name=name or address,
                paired=paired,
                connected=True,
            )
            return path, info
        return None

    async def pair_trust_connect(self, device_path: str) -> None:
        device_obj = await self._get_device_proxy(device_path)
        device_iface = device_obj.get_interface("org.bluez.Device1")
        props = device_obj.get_interface("org.freedesktop.DBus.Properties")
        try:
            await device_iface.call_pair()
        except Exception:
            # Pair may already be done; continue
            pass
        try:
            await props.call_set(
                "org.bluez.Device1", "Trusted", _variant(True)
            )
        except Exception:
            pass
        try:
            await device_iface.call_connect()
        except Exception:
            pass

    async def connect_device(self, device_path: str) -> None:
        device_obj = await self._get_device_proxy(device_path)
        device_iface = device_obj.get_interface("org.bluez.Device1")
        await device_iface.call_connect()

    async def remove_device(self, device_path: str) -> None:
        await self._adapter_iface.call_remove_device(device_path)

    async def _get_device_proxy(self, device_path: str):
        introspect = await self._bus.introspect("org.bluez", device_path)
        return self._bus.get_proxy_object("org.bluez", device_path, introspect)


def _variant_value(value):
    try:
        return value.value
    except Exception:
        return value


def _variant(value):
    try:
        from dbus_next import Variant

        if isinstance(value, bool):
            return Variant("b", value)
        if isinstance(value, int):
            return Variant("i", value)
        if isinstance(value, list):
            return Variant("as", value)
        return Variant("s", str(value))
    except Exception:
        return value


def _has_audio_uuid(device_props: dict) -> bool:
    uuids = _variant_value(device_props.get("UUIDs")) or []
    audio_uuids = {
        "0000110b-0000-1000-8000-00805f9b34fb",  # Audio Sink
        "0000110a-0000-1000-8000-00805f9b34fb",  # Audio Source
        "0000110e-0000-1000-8000-00805f9b34fb",  # A/V Remote Control
        "0000110c-0000-1000-8000-00805f9b34fb",  # A/V Remote Control Target
        "0000111e-0000-1000-8000-00805f9b34fb",  # Handsfree
        "0000111f-0000-1000-8000-00805f9b34fb",  # Handsfree Audio Gateway
        "00001108-0000-1000-8000-00805f9b34fb",  # Headset
        "00001112-0000-1000-8000-00805f9b34fb",  # Headset Audio Gateway
    }
    return any(str(uuid).lower() in audio_uuids for uuid in uuids)
