# Linux Voice Assistant - AI Agent Instructions

## Big picture
- Multi-instance voice satellite for Home Assistant using the ESPHome protocol; each instance is a networked device with a unique port and MAC address.
- Core flow: audio input -> wake word detection -> stream audio to HA -> HA STT/intent/TTS -> local TTS playback with music ducking -> LED/screen feedback.
- Single asyncio event loop per instance; shared runtime state lives in `ServerState` in `linux_voice_assistant/models.py`.
- Optional device manager for centralized control of multiple instances, Bluetooth devices, system monitoring, and mute state.

## Architecture

### Voice Satellite (Primary Mode)
- `linux_voice_assistant/satellite.py`: main voice pipeline, wake word handling, audio streaming, timers, screen DPMS control.
- `linux_voice_assistant/api_server.py`: ESPHome protocol server and message parsing; `APIServer.handle_message()` dispatches entity updates.
- `linux_voice_assistant/entity.py`: ESPHome entities (MediaPlayerEntity, TextAttributeEntity, SwitchEntity, ButtonEntity, SelectEntity) registered in `ServerState.entities`.
- `linux_voice_assistant/__main__.py`: CLI entry, preferences loading, wake word discovery, event loop setup for satellite instances.
- `linux_voice_assistant/mpv_player.py`: audio playback and automatic music ducking for announcements using mpv.
- `linux_voice_assistant/models.py`: shared data models (`ServerState`, `Preferences`, `GlobalPreferences`, `AvailableWakeWord`, `WakeWordType`).
- `linux_voice_assistant/zeroconf.py`: mDNS discovery and advertisement for Home Assistant.

### Device Manager (Optional Centralized Control)
- `linux_voice_assistant/__main_manager__.py`: manager entry point for controlling multiple satellites.
- `linux_voice_assistant/device_manager.py`: centralized instance management, system metrics (CPU/temp/memory/disk), Bluetooth device pairing/connection, system mute state, Squeezelite/LED service status.
- Deployed via `script/deploy-manager NAME` with its own port (default 6152).
- Exposes HA entities: switches to start/stop instances, buttons to restart/remove instances, sensors for system metrics, Bluetooth controls, service status.

### Additional Modules
- `bluetooth/`: async Bluetooth management via D-Bus (BlueZ); `BlueZHelper` class for scanning, pairing, connecting audio devices.
- `led/`: standalone LED feedback service that tails systemd logs and drives WS2812 LED strips via SPI; reacts to voice assistant events (listening, intent, TTS, mute).
- `lvas_startup/`: startup helpers for kiosk/auto-login environments.
- `Squeezelite/`: integration documentation for Music Assistant playback with automatic ducking.

## Developer workflows
- **Setup**: `script/setup` (creates venv and installs all dependencies).
- **Run foreground**: `script/run --name NAME [--wake-model MODEL] [--audio-input-device DEVICE]`.
- **Deploy satellite service**: `script/deploy NAME [--wake-model MODEL]` (auto-assigns port starting at 6053 and MAC).
- **Deploy manager service**: `script/deploy-manager NAME [--port PORT]` (default port 6152).
- **Manage services**: 
  - `script/status` - show all instances and service status
  - `script/restart [NAME]` - restart all or specific instance
  - `script/stop NAME` - stop specific instance
  - `script/remove NAME` - remove instance and service
  - `script/restart-manager [NAME]` - restart manager
  - `script/remove-manager [NAME]` - remove manager service
- **Audio devices**: `script/run --name Test --list-input-devices` / `--list-output-devices`.
- **Development tools**: `script/format`, `script/lint`, `script/test`.

## Configuration and data
- **Preferences** live in `preferences/user/`:
  - `NAME_cli.json` - per-instance CLI/runtime settings (port, devices, screen management, etc.)
  - `NAME.json` - per-instance wake word configuration
  - `NAME_manager.json` - manager CLI config
  - `ha_settings.json` - global HA connection (base URL, token, wake word friendly names, history entity)
- **Default templates** in `preferences/default/`:
  - `default_cli.json` - default satellite settings
  - `default_wsl_cli.json` - WSL-specific defaults
  - `default.json` - default wake word config
- **Wake words** discovered from `wakewords/` and `wakewords/openWakeWord/` using paired `*.json` + `*.tflite` models.
- **System state**: `/dev/shm/lvas_system_mute` - shared mute state file (written by satellites, read by LED service and manager).

## Conventions and gotchas
- All scripts in `script/` are Python executables (not shell scripts) and are venv-aware.
- Microphone input must support 16kHz mono audio.
- Audio backend uses `soundcard` library (PulseAudio/PipeWire compatible); device listing is the recommended way to select input/output.
- Playback uses `python-mpv` (requires system `libmpv-dev`).
- System dependencies: `portaudio19-dev`, `build-essential`, `libmpv-dev`.
- LED feedback requires `spidev` and SPI enabled on device (e.g., `/dev/spidev1.0`).
- Bluetooth requires BlueZ and D-Bus (`dbus-next` Python package).
- Screen management (`--screen-management`) uses `xset` DPMS commands on X11 displays.
- Manager assigns ports incrementally from 6053 for satellites; manager itself uses 6152 by default.
- CLI config arguments from last run are auto-loaded as defaults when re-running instances.

## Features
- **Multi-instance**: run multiple satellites on one machine with different wake words and audio devices.
- **Wake word detection**: supports microWakeWord and openWakeWord models; multiple wake words per instance.
- **Stop word**: optional "stop" wake word to cancel listening.
- **Voice pipeline**: full HA integration for STT, intent, TTS via ESPHome protocol.
- **Timers**: voice-controlled timers with callback announcements.
- **TTS ducking**: automatic music volume reduction during announcements.
- **Wake word disable during TTS**: `--disable-wakeword-during-tts` flag to reduce false triggers.
- **Screen management**: auto-sleep/wake screen on voice activity (X11 DPMS).
- **Bluetooth audio**: pair and connect Bluetooth speakers/headphones via manager or BlueZ module.
- **System monitoring**: CPU, temperature, memory, disk usage exposed as HA sensors (via manager).
- **LED feedback**: visual indicator strip for voice states (listening, processing, speaking, muted).
- **Squeezelite integration**: Music Assistant playback with ducking coordination.
- **Zeroconf/mDNS**: auto-discovery by Home Assistant.

## Integration points
- **Home Assistant**: ESPHome integration; add each satellite by IP:port (e.g., `192.168.1.100:6053`).
- **Zeroconf**: satellites and manager advertise via mDNS for HA discovery.
- **Music Assistant**: via Squeezelite user service; coordinates with TTS for ducking.
- **BlueZ/D-Bus**: async Bluetooth device management for audio devices.
- **Systemd**: user services for satellites, manager, LED feedback, and Squeezelite.
- **SPI**: LED strip control via `spidev` (for WS2812 LEDs on Raspberry Pi/Orange Pi).
- **X11 DPMS**: screen sleep/wake control via `xset`.

## Entity types
- **MediaPlayerEntity**: main TTS playback control
- **TextAttributeEntity**: active STT/TTS/assistant pipeline display
- **SwitchEntity**: mute, instance enable/disable
- **ButtonEntity**: restart/remove instances, Bluetooth scan/pair/forget
- **SelectEntity**: wake word selection, audio device selection, Bluetooth device selection
