"""BlueZ D-Bus helper for Bluetooth device discovery and listing."""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next.service import ServiceInterface, method

_LOGGER = logging.getLogger(__name__)


@dataclass
class BluetoothDeviceInfo:
    address: str
    name: str
    paired: bool
    connected: bool


class BlueZAgent(ServiceInterface):
    """Simple BlueZ agent that auto-accepts pairing requests."""
    
    def __init__(self):
        super().__init__("org.bluez.Agent1")
        self._registered = False
    
    @method(name='Release')
    def release(self):  # noqa: N802
        """Called when the agent is unregistered."""
        self._registered = False
    
    @method(name='RequestPinCode')
    def request_pin_code(self, device: 'o') -> 's':  # noqa: N802
        """Return a PIN for pairing (use 0000 as default)."""
        _LOGGER.info(f"RequestPinCode for {device}")
        return "0000"
    
    @method(name='RequestPasskey')
    def request_passkey(self, device: 'o') -> 'u':  # noqa: N802
        """Return a passkey for pairing (use 0 as default)."""
        _LOGGER.info(f"RequestPasskey for {device}")
        return 0
    
    @method(name='DisplayPinCode')
    def display_pin_code(self, device: 'o', pincode: 's'):  # noqa: N802
        """Display PIN code for pairing."""
        _LOGGER.info(f"DisplayPinCode for {device}: {pincode}")
    
    @method(name='DisplayPasskey')
    def display_passkey(self, device: 'o', passkey: 'u', entered: 'u'):  # noqa: N802
        """Display passkey for pairing."""
        _LOGGER.info(f"DisplayPasskey for {device}: {passkey} (entered: {entered})")
    
    @method(name='RequestConfirmation')
    def request_confirmation(self, device: 'o', passkey: 'u'):  # noqa: N802
        """Auto-confirm pairing."""
        _LOGGER.info(f"RequestConfirmation for {device}: {passkey}")
        # Return nothing to confirm
    
    @method(name='RequestAuthorization')
    def request_authorization(self, device: 'o'):  # noqa: N802
        """Auto-authorize pairing."""
        _LOGGER.info(f"RequestAuthorization for {device}")
        # Return nothing to authorize
    
    @method(name='AuthorizeService')
    def authorize_service(self, device: 'o', uuid: 's'):  # noqa: N802
        """Auto-authorize service."""
        _LOGGER.info(f"AuthorizeService for {device}: {uuid}")
        # Return nothing to authorize
    
    @method(name='Cancel')
    def cancel(self):  # noqa: N802
        """Called when pairing is cancelled."""
        _LOGGER.info("Pairing cancelled")


class BlueZHelper:
    def __init__(self, bus, object_manager, adapter_iface, adapter_path: str, agent: Optional[BlueZAgent] = None) -> None:
        self._bus = bus
        self._object_manager = object_manager
        self._adapter_iface = adapter_iface
        self._adapter_path = adapter_path
        self._agent = agent

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

        # Create and register agent
        agent = BlueZAgent()
        try:
            await bus.request_name("org.bluez.agent.LVA")
            bus.export("/org/bluez/agent/lva", agent)
            agent_manager_obj = bus.get_proxy_object("org.bluez", "/org/bluez", root)
            agent_manager_iface = agent_manager_obj.get_interface("org.bluez.AgentManager1")
            await agent_manager_iface.call_register_agent("/org/bluez/agent/lva", "DisplayYesNo")
            _LOGGER.info("BlueZ agent registered successfully")
            agent._registered = True
        except Exception as e:
            _LOGGER.warning(f"Failed to register BlueZ agent: {e}")
            agent = None

        return cls(bus, object_manager, adapter_iface, adapter_path, agent)

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
        """Pair, trust, and connect to a Bluetooth device.
        
        This method requires the BlueZ agent to be properly registered.
        Make sure the device is in pairing mode before calling this.
        """
        device_obj = await self._get_device_proxy(device_path)
        device_iface = device_obj.get_interface("org.bluez.Device1")
        props = device_obj.get_interface("org.freedesktop.DBus.Properties")
        
        # Check if agent is registered
        if not self._agent or not self._agent._registered:
            _LOGGER.warning("BlueZ agent not registered - pairing may fail without confirmation")
        
        # Step 1: Pair the device
        _LOGGER.info(f"Pairing with device {device_path}...")
        try:
            # Set pairing timeout
            pair_task = device_iface.call_pair()
            await asyncio.wait_for(pair_task, timeout=30.0)
            _LOGGER.info("Device paired successfully")
            await asyncio.sleep(0.5)  # Brief pause before next step
        except asyncio.TimeoutError:
            _LOGGER.error("Pairing timed out")
            raise Exception("Pairing timed out - ensure device is in pairing mode")
        except Exception as e:
            # Check if device is already paired
            current_props = await self._object_manager.call_get_managed_objects()
            if device_path in current_props:
                device_info = current_props[device_path].get("org.bluez.Device1", {})
                if _variant_value(device_info.get("Paired")):
                    _LOGGER.info("Device already paired, continuing...")
                else:
                    _LOGGER.error(f"Pairing failed: {e}")
                    raise
            else:
                _LOGGER.error(f"Pairing failed: {e}")
                raise
        
        # Step 2: Set device as trusted
        _LOGGER.info("Setting device as trusted...")
        try:
            await props.call_set("org.bluez.Device1", "Trusted", _variant(True))
            _LOGGER.info("Device marked as trusted")
        except Exception as e:
            _LOGGER.warning(f"Failed to set trusted: {e}")
        
        await asyncio.sleep(0.5)  # Brief pause before connection
        
        # Step 3: Connect to the device
        _LOGGER.info("Connecting to device...")
        try:
            connect_task = device_iface.call_connect()
            await asyncio.wait_for(connect_task, timeout=15.0)
            _LOGGER.info("Device connected successfully")
        except asyncio.TimeoutError:
            _LOGGER.warning("Connection timed out - device may connect in background")
        except Exception as e:
            # Connection might fail if not an audio device, but that's ok
            _LOGGER.warning(f"Connection failed (may not be audio device): {e}")

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
