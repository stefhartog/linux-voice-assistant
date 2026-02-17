# Bluetooth Module

This module provides async Bluetooth device management for the Linux Voice Assistant using the BlueZ D-Bus interface.

## Files

### `__init__.py`
Exports the public API of the bluetooth module:
- `BluetoothDeviceInfo` - Data class for Bluetooth device information
- `BlueZHelper` - Main helper class for Bluetooth operations

### `bluez_helper.py`
Contains the core Bluetooth functionality:

**BluetoothDeviceInfo** (dataclass)
- `address`: MAC address of the Bluetooth device
- `name`: Human-readable device name
- `paired`: Whether the device is paired
- `connected`: Whether the device is currently connected

**BlueZHelper** (async class for Bluetooth device management)
- `scan(duration_seconds)`: Start and stop Bluetooth discovery for a specified duration
- `list_devices(audio_only)`: Retrieve all discovered Bluetooth devices, optionally filtering for audio-only devices
- `list_devices_with_paths(audio_only)`: Retrieve devices along with their D-Bus object paths
- `get_connected_device(audio_only)`: Get the currently connected audio device
- `pair_trust_connect(device_path)`: Pair, trust, and connect to a device in one operation
- `connect_device(device_path)`: Connect to an already-paired device
- `remove_device(device_path)`: Remove a device from the pairing list

## Dependencies

### System Packages
- **BlueZ** - Linux Bluetooth stack (typically pre-installed on most distributions)
  ```bash
  # Ubuntu/Debian
  sudo apt-get install bluez bluez-tools

  # Fedora/RHEL
  sudo dnf install bluez

  # Arch
  sudo pacman -S bluez
  ```

### Python Packages
- **dbus-next** - D-Bus bindings for Python (async support)
  - Installed automatically as part of the project dependencies in `pyproject.toml`

## Usage

The module requires an active D-Bus session to communicate with BlueZ. It uses async/await for non-blocking operations.

### Basic Example
```python
from linux_voice_assistant.bluetooth import BlueZHelper

# Create a helper instance
helper = await BlueZHelper.create()

# List all discovered audio devices
devices = await helper.list_devices(audio_only=True)
for device in devices:
    print(f"{device.name} ({device.address}) - Connected: {device.connected}")

# Scan for new devices
await helper.scan(duration_seconds=10)

# Connect to a device
devices_with_paths = await helper.list_devices_with_paths()
if devices_with_paths:
    path, device_info = devices_with_paths[0]
    await helper.pair_trust_connect(path)
```

## Notes

- All BlueZHelper methods are **async** and must be called with `await` within an asyncio event loop
- Audio device filtering uses standard Bluetooth audio UUIDs (A2DP, HFP, HSP, etc.)
- The default adapter path is `/org/bluez/hci0` (first Bluetooth adapter); can be overridden in the `create()` method
- D-Bus system bus access is required; typically available to the user running the service
- D-Bus variant handling is abstracted in helper functions (`_variant_value`, `_variant`, `_has_audio_uuid`)
