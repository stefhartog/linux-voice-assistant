# Linux Voice Assistant - AI Agent Instructions

## Big Picture

**Linux Voice Assistant (LVAS)** is a multi-instance voice satellite platform for Home Assistant using the ESPHome protocol. Each instance runs as an independent asyncio service with its own wake word detection, audio processing, and network identity (unique port, MAC address). The architecture supports:

- **Independent Voice Satellites**: Multiple instances on one machine, each with unique audio devices and wake words; discovered by HA via mDNS/Zeroconf
- **Unified Event Loop**: Single asyncio event loop per satellite; all I/O (network, audio, subprocess) is async-first
- **Shared Runtime State**: `ServerState` (models.py) holds persistent config, audio queues, entity references, player instances
- **Optional Device Manager**: Centralized control and monitoring of multiple satellites with system metrics, Bluetooth, service status
- **Voice Pipeline**: audio input → (local) wake word detection → stream audio to HA → HA STT/intent/TTS → local TTS playback (with music ducking) → LED/screen feedback

## Architecture

### Voice Satellite (Primary Mode)

**Core Components:**
- `linux_voice_assistant/__main__.py`: CLI entry point; loads preferences, discovers wake words, creates ServerState, spins up asyncio event loop and APIServer
- `linux_voice_assistant/satellite.py` (`VoiceSatelliteProtocol` class): extends APIServer; main voice pipeline logic including wake word handling, audio streaming to HA, timer management, screen DPMS control
- `linux_voice_assistant/api_server.py` (`APIServer` base class): ESPHome protocol server (asyncio.Protocol); handles low-level message parsing/serialization; abstract `handle_message()` dispatch
- `linux_voice_assistant/entity.py`: ESPHome entity classes registered in ServerState (MediaPlayerEntity, TextAttributeEntity, SwitchEntity, ButtonEntity, SelectEntity); each has `handle_message()` to respond to HA commands
- `linux_voice_assistant/mpv_player.py` (`MpvMediaPlayer` class): plays audio via python-mpv subprocess; tracks playback state; supports automatic music ducking (volume reduction during announcements)
- `linux_voice_assistant/models.py`: shared dataclasses (`ServerState`, `Preferences`, `GlobalPreferences`, `AvailableWakeWord`, `WakeWordType`); ServerState is the central mutable state holder
- `linux_voice_assistant/zeroconf.py` (`HomeAssistantZeroconf`): mDNS discovery/advertisement for HA; announces satellite at IP:port with friendly name and MAC address
- `linux_voice_assistant/util.py`: helper functions (`get_mac()`, `call_all()`)

**Data Flow (Voice Input):**
1. Audio input thread reads 16kHz mono PCM from soundcard → `ServerState.audio_queue` (thread-safe Queue)
2. asyncio task (`_audio_detection_loop()` in satellite.py) dequeues audio and feeds to wake word model (MicroWakeWord or OpenWakeWord)
3. Wake word triggered → stream audio to HA via VoiceAssistantAudio message (binary protobuf)
4. HA performs STT/intent/TTS → sends VoiceAssistantRequest back with TTS audio URL
5. VoiceSatelliteProtocol receives TTS request → MediaPlayerEntity.play() → MpvMediaPlayer plays audio with ducking
6. Done → send VoiceAssistantAnnounceFinished to HA

### Device Manager (Optional Centralized Control)

**Components:**
- `linux_voice_assistant/__main_manager__.py`: entry point; CLI argument parsing; starts DeviceManager and DeviceManagerProtocol
- `linux_voice_assistant/device_manager.py` (`DeviceManager`, `DeviceManagerProtocol` classes): 
  - Exposes HA entities (text sensors for CPU/temp/memory/disk/Squeezelite/LED status; switches to enable/disable instances; buttons to restart/remove instances; Bluetooth pairing controls)
  - Periodically monitors system metrics and instance service status
  - Spawns/kills satellite instances via script/deploy and script/remove
  - Reads/writes shared mute state from `/dev/shm/lvas_system_mute`

### Additional Modules

- `bluetooth/bluez_helper.py` (`BlueZHelper` class): async wrapper around BlueZ D-Bus service (dbus-next); scan for Bluetooth devices, initiate pairing, connect audio devices, manage connection state
- `led/led_feedback.py`: standalone service that tails systemd journal, parses LVAS log messages, drives WS2812 LED strip via SPI (`/dev/spidev1.0` or configurable); reacts to voice events (listening→pulsing green, TTS→cyan, detected intent→blue, muted→red)
- `led/state_patterns.py`: LED color/animation primitives
- `lvas_startup/`: desktop environment helpers for kiosk/auto-login scenarios (systemd services, .desktop files, shell scripts)
- `Squeezelite/setup_squeezelite.sh`: integration guide for Music Assistant playback (runs Squeezelite on same machine, auto-pauses during TTS announcements)

## Developer Workflows

### Setup

```bash
script/setup
```
Creates Python 3.9+ venv in `.venv/` and installs all dependencies (see pyproject.toml).

### Running Instances

**Development/Foreground:**
```bash
script/run --name MyVA
```
Starts instance in foreground with auto-generated preferences. Options:
- `--wake-model MODEL` - active wake word model ID (default: okay_nabu)
- `--stop-model MODEL` - stop/cancel model (default: stop)
- `--audio-input-device DEVICE` - soundcard name (see `--list-input-devices`)
- `--audio-output-device DEVICE` - mpv output device (see `--list-output-devices`)
- `--port PORT` - ESPHome server port (default: 6052)
- `--mac MAC_ADDR` - spoof MAC address (format: aa:bb:cc:dd:ee:ff or aabbccddeeff)
- `--host HOST` - bind address (default: 0.0.0.0)
- `--refractory-seconds SECS` - cooldown between wake word triggers (default: 2.0)
- `--wakeup-sound PATH` - audio file played when wake word detected
- `--timer-finished-sound PATH` - audio file for timer callbacks
- `--screen-management SECONDS` - X11 screen sleep timeout (0=off, >0=seconds before sleep)
- `--disable-wakeword-during-tts` - suppress wake word detection while TTS is playing (reduces false triggers)
- `--debug` - verbose logging to console
- `--list-input-devices` / `--list-output-devices` - enumerate audio devices and exit
- `--preferences-file PATH` - root preferences JSON (normally auto-located)
- `--download-dir PATH` - directory for downloaded wake word models

CLI arguments from last run are auto-loaded as defaults (persisted in `preferences/user/NAME_cli.json`).

**Production/Background Service:**
```bash
script/deploy MyVA [--wake-model Model] [additional args]
```
Creates preference files, installs systemd user service (in `~/.config/systemd/user/`), enables persistent sessions (loginctl user-runtime-dir), and starts service immediately. Auto-assigns port starting from 6053, unique MAC. Survive reboot and SSH logout.

**Multiple Instances:**
```bash
script/deploy VA1 --wake-model alexa
script/deploy VA2 --wake-model hey_jarvis
script/deploy VA3
```
Each instance has independent preferences (`VA1.json`, `VA1_cli.json`, etc.) and systmed service.

### Service Management

```bash
script/status                   # Show all instances and their service status
script/restart [NAME]          # Restart all instances (or specific NAME)
script/stop NAME               # Stop specific instance
script/remove NAME             # Remove instance config and service
script/restart-manager [NAME]  # Restart device manager service
script/remove-manager [NAME]   # Remove device manager service
```

### Device Manager

```bash
script/deploy-manager MyManager [--port 6152]
```
Deployes centralized manager service on specified port (default 6152). Use `script/status` to see manager systemd status.

### Audio Devices

```bash
script/run --name Test --list-input-devices
script/run --name Test --list-output-devices
```

### Development Tools

```bash
script/format             # Black + isort formatting
script/lint              # Pylint + flake8 + mypy + isort --check
script/test              # Pytest on tests/
```

## Configuration and Data

### Preferences (JSON Files)

Live in `preferences/user/` (created on first run):

- **`NAME_cli.json`** - Per-instance runtime CLI settings: port, audio devices, screen timeout, etc. Sourced as argparse defaults on next run.
- **`NAME.json`** - Per-instance wake word configuration: `active_wake_words` list.
- **`NAME.service`** - Systemd user service file (auto-generated by script/deploy).
- **`NAME_manager.json`** - Device manager CLI config (port, refresh interval, debug flag).
- **`ha_settings.json`** - Global HA connection: `ha_base_url`, `ha_token`, `ha_history_entity`, `wake_word_friendly_names` (dict of model ID → friendly name).

### Default Preference Templates

In `preferences/default/`:

- **`default_cli.json`** - Fallback CLI settings if instance has no config
- **`default_wsl_cli.json`** - WSL-specific defaults (different audio backend, paths)
- **`default.json`** - Default wake word config template

### Wake Words

**Directory Structure:**
- `wakewords/` - microWakeWord models (each model is a paired `*.json` config + `*.tflite` binary)
- `wakewords/openWakeWord/` - openWakeWord models (same structure)

**Discovery:** __main__.py scans both directories, matches JSON+tflite pairs, builds `available_wake_words` dict keyed by model ID.

**Factory-Installed Models:**
- `alexa`, `choo_choo_homie`, `hey_home_assistant`, `hey_jarvis`, `hey_luna`, `hey_mycroft`, `okay_computer`, `okay_nabu`, `stop`
- openWakeWord variants: `alexa_v0.1`, `hey_jarvis_v0.1`, `hey_mycroft_v0.1`, `hey_rhasspy_v0.1`, `ok_nabu_v0.1`

**Adding Custom Wake Words:** Download `.tflite` + `.json` pair to `wakewords/` or `local/`, reference by ID in `NAME.json` or `--wake-model` argument.

### Shared System State

- **`/dev/shm/lvas_system_mute`** - Text file containing "true"/"false" shared mute state (written by satellites, read by LED service and manager to suppress wake word/feedback)

### Preferences Format Details

**`ha_settings.json`:**
```json
{
  "ha_base_url": "http://192.168.1.100:8123",
  "ha_token": "<long-lived-HA-token>",
  "ha_history_entity": "input_boolean.voice_assistant_history",
  "wake_word_friendly_names": {
    "hey_jarvis": "Jarvis",
    "okay_nabu": "Nabu"
  }
}
```

**`NAME_cli.json`:**
```json
{
  "port": 6053,
  "mac": "aabbccddeeff1234",
  "wake_model": "okay_nabu",
  "audio_input_device": "Mic",
  "audio_output_device": "Speaker",
  "screen_management": 300,
  "__system_info__": { "os": "Linux", "machine": "aarch64" }
}
```

**`NAME.json`:**
```json
{
  "active_wake_words": ["okay_nabu", "stop"]
}
```

## ESPHome Protocol & Entities

### Protocol Overview

- Based on `aioesphomeapi` (protobuf-over-TCP, plaintext framing variant)
- `APIServer` base class handles low-level protocol (HelloResponse, AuthenticationResponse, lifecycle)
- `VoiceSatelliteProtocol` extends APIServer for voice-specific messages (VoiceAssistantAudio, VoiceAssistantRequest, VoiceAssistantConfigurationResponse, VoiceAssistantWakeWord)
- `DeviceManagerProtocol` extends APIServer for non-voice manager entities
- Message dispatch: incoming protobuf → `handle_message()` → entity handler → response protobuf

### Entity Types

Each entity has a unique `key` (int) and registers itself with `ListEntities*Response` messages:

- **`MediaPlayerEntity`** - Controls TTS/music playback via mpv. Supports play (with URL or immediate command), pause, resume, volume. Implements music ducking for announcements (pauses music, plays announcement, resumes music).
  - Constructor: `MediaPlayerEntity(server, key, name, object_id, music_player, announce_player)`
  - `play(url, announcement=False, done_callback=None)` - Play audio URL or list of URLs; sets is_playing flag and yields MediaPlayerStateResponse
  - Handles `MediaPlayerCommandRequest` from HA

- **`TextAttributeEntity`** - Read-only text sensor for displaying dynamic status (active STT/TTS/intent pipeline).
  - Constructor: `TextAttributeEntity(server, key, name, object_id, icon=None)`
  - `set_state(state: str)` - Update value and send TextSensorStateResponse to HA
  - Typically used for: active_stt_entity, active_tts_entity, active_assistant_entity in satellite

- **`SwitchEntity`** - Toggle switch for mute, enable/disable, etc.
  - Supports on_turn_on / on_turn_off callbacks
  - Handles `SwitchCommandRequest` from HA

- **`ButtonEntity`** - Momentary press button for actions (restart, remove, scan Bluetooth)
  - Constructor: `ButtonEntity(server, key, name, object_id, on_press=None, icon=None)`
  - `on_press` callback fired when HA sends command
  - Handles `ButtonCommandRequest` from HA

- **`SelectEntity`** - Dropdown selector for wake word model, audio device, Bluetooth device
  - Constructor: `SelectEntity(server, key, name, object_id, options=[], on_select=None, icon=None)`
  - Handles `SelectCommandRequest` from HA with index

### Voice Assistant Messages (Satellite-Specific)

**Sent by Satellite to HA:**
- `VoiceAssistantAudio` - streaming audio (16kHz mono PCM) after wake word detected
- `VoiceAssistantAnnounceRequest` / `VoiceAssistantAnnounceFinished` - TTS announcement lifecycle
- `VoiceAssistantWakeWord` - Signal which wake word was detected (for HA logging)

**Received from HA:**
- `VoiceAssistantRequest` - Contains TTS audio URL (media_url) and config (use_announce)
- `VoiceAssistantConfigurationRequest` - Query satellite capabilities (wake word types, assistant pipeline version)

## Conventions and Gotchas

### Critical Assumptions

- **16kHz Mono Audio:** Wake word models and audio streaming assume exactly 16kHz mono PCM. Soundcard input MUST be configured to support this sample rate.
- **Single Event Loop:** All async code runs in one `asyncio.get_running_loop()` per instance. Audio reading runs on a separate thread with thread-safe Queue; wake word detection, network I/O, and callbacks all in asyncio context.
- **Shared ServerState:** All entities, callbacks, and background tasks reference same `ServerState` object passed from __main__.py.

### Script/Deployment

- All scripts in `script/` are **Python executables** (not shell scripts), venv-aware, and idempotent.
- `script/setup` auto-detects WSL and sets appropriate defaults.
- `script/deploy` auto-assigns port (6053, 6054, etc.) and MAC from UUID (deterministic per machine).
- Systemd services live in `~/.config/systemd/user/` (enable persistent sessions with `loginctl enable-linger $USER`).

### Audio & Devices

- **Input:** Soundcard library scans PulseAudio/PipeWire (on Linux). Device names are case-sensitive and must exactly match soundcard output.
- **Output:** mpv naming depends on backend (PulseAudio sink names, PipeWire node names). Use `--list-output-devices` to discover.
- **Echo Cancellation:** PulseAudio/PipeWire module loopback can provide echo cancellation; configure via `pactl` / `wpctl`.
- **Audio Format:** Input is 16kHz mono 16-bit signed PCM; output depends on mpv/hardware codec support.

### Dependencies & System Packages

- **@Required:**
  - `libportaudio2` or `portaudio19-dev` - soundcard input (C library)
  - `build-essential` - pymicro-wakeword compilation
  - `libmpv-dev` - python-mpv bindings
  - Python 3.9+ with pip, venv

- **Optional (for advanced features):**
  - `bluez bluez-tools` - BlueZ daemon and CLI tools for Bluetooth (if using BT audio)
  - `spidev` Python package - LED strip SPI control (WS2812 on Raspberry Pi)
  - `x11-xserver-utils` - xset command for screen DPMS (if using --screen-management)

### Port Assignment & MAC Spoofing

- **Ports:** script/deploy auto-assigns starting from 6053. Manually set with `--port PORT`.
- **MAC:** UUID-based and deterministic per machine. Override with `--mac aa:bb:cc:dd:ee:ff`. HA discovery uses MAC to uniquely key satellites.
- **Manager Port:** Default 6152; configure with `--port`.

### Preferences Auto-Load

- On subsequent runs, `script/run --name NAME` loads previous CLI args from `preferences/user/NAME_cli.json` as argparse defaults.
- Useful for avoiding re-typing device names, port, etc.
- Defaults can be overridden on command line.

### Mute State

- `/dev/shm/lvas_system_mute` is a shared tmpfs file (survives process restarts but not reboot unless used via systemd).
- Written by satellites when mute switch toggled.
- Read by LED service and satellites to suppress wake word / feedback.

### Screen Management (X11)

- `--screen-management SECONDS` uses `xset dpms` to sleep/wake display on voice activity.
- Requires X11 (not Wayland); `DISPLAY=:0` is default but can be overridden in code.
- Typical value: 300 seconds (5 minutes before sleep).

### Refractory Period

- `--refractory-seconds` (default 2.0) is cooldown after wake word trigger before next detection.
- Prevents false re-triggers from tail-end audio or echos.

### Wake Word Models

- microWakeWord (format: `micro`) - lightweight, English-only, on-device; lower latency
- openWakeWord (format: `openWakeWord`) - more robust, multilingual; requires more CPU
- Each model's ID is its JSON filename (without extension); same model can appear in microWakeWord or openWakeWord directories (not both simultaneously).

### Disable Wake Word During TTS

- `--disable-wakeword-during-tts` suppresses wake word detection while TTS is playing.
- Useful to reduce false triggers from announcements or speech-like sounds.
- Detection resumes after TTS ends.

### File Paths

- Preferences: `_REPO_DIR / "preferences"` (inferred from __main__.py location)
- Sounds (wakeup, timer finished): `_REPO_DIR / "sounds"`
- Wake words: `_REPO_DIR / "wakewords"` (can be extended with `--wake-word-dir`)
- Downloads: `_REPO_DIR / "local"` (default, can override with `--download-dir`)

## Features

### Voice Satellite

- ✅ **Multi-Instance** - Run multiple satellites on one machine with different wake words/devices; auto-assigned ports and MACs; independent systemd services.
- ✅ **Wake Word Detection** - Local, on-device; supports microWakeWord and openWakeWord models; multiple active wake words per instance.
- ✅ **Stop Word** - Optional "stop" wake word to cancel listening before TTS is requested (e.g., to save bandwidth or prevent accidental stream).
- ✅ **Full Voice Pipeline** - Audio → HA (via ESPHome) → STT → intent → TTS → local playback.
- ✅ **Timers** - Voice-controlled with duration/label; HA integration; local callback announcements.
- ✅ **Music Ducking** - Automatic volume reduction (duck to ~50%) during TTS; resume full volume after.
- ✅ **Wake Word Disable During TTS** - Suppress detection while playing TTS to reduce false triggers.
- ✅ **Screen Management** - Auto-sleep/wake X11 displays on voice activity (DPMS).
- ✅ **Asyncio-First** - All I/O (network, subprocess) is async; audio thread is separate but thread-safe.

### Advanced (Optional)

- ✅ **Bluetooth Audio** - Pair/connect BT speakers/headphones via `bluetooth/bluez_helper.py` (D-Bus/BlueZ integration).
- ✅ **LED Feedback** - Visual state indicators via WS2812 LEDs on SPI; colors for listening/intent/TTS/mute.
- ✅ **Device Manager** - Centralized dashboard for multi-instance control (start/stop/restart), system metrics (CPU/temp/memory/disk), Bluetooth pairing, mute state, service status.
- ✅ **System Monitoring** - Manager exposes CPU/temp/memory/disk as HA text sensors; supports /sys/class/thermal/ and /proc/stat parsing.
- ✅ **Music Assistant Integration** - Squeezelite auto-pauses during TTS; HA automation can control music service.
- ✅ **Multiuser Systemd** - Services survive reboot and SSH logout (requires `loginctl enable-linger`).

## Integration Points

- **Home Assistant (ESPHome Integration)**
  - Add each satellite by IP:port in HA ESPHome integration (e.g., 192.168.1.100:6053)
  - Each satellite shows as an ESPHome device with media player, mute switch, text sensors
  - Manager shows as separate ESPHome device with control switches and status sensors
  - Full voice pipeline coordination via ESPHome API

- **Zeroconf/mDNS**
  - Each satellite advertises via `_hap._tcp` SRV record with friendly name, IP, port, MAC
  - HA can auto-discover satellites if on same network
  - Manager also advertises (port 6152 by default)

- **Bluetooth (BlueZ/D-Bus)**
  - Via `bluetooth/bluez_helper.py` and manager Bluetooth entities
  - Async scanning, pairing, connection management
  - Requires BlueZ daemon and D-Bus on Linux

- **Systemd (User Services)**
  - Each deployed instance is a systemd user service in `~/.config/systemd/user/`
  - Services auto-restart on failure (Restart=always)
  - Persistent sessions: `loginctl enable-linger $USER`
  - Manager can spawn/kill instances via script/deploy and script/remove

- **Audio (PulseAudio/PipeWire)**
  - Input via soundcard library (queries PulseAudio/PipeWire) at 16kHz mono
  - Output via mpv (auto-selects default sink or explicit device via --audio-output-device)

- **SPI (LED Feedback)**
  - `/dev/spidev1.0` or configurable via led/led_feedback.py
  - WS2812 RGB LED strips (NeoPixel-compatible)
  - Requires SPI enabled on device (Raspberry Pi, Orange Pi, etc.)

- **X11 DPMS (Screen Management)**
  - `xset dpms` commands for screen sleep/wake
  - Requires X11 (not Wayland); DISPLAY environment variable

## Common Patterns & Tips

### Adding a New Wake Word

1. Obtain `.tflite` model and `.json` config from microWakeWord or openWakeWord
2. Copy both files to `wakewords/` or `wakewords/openWakeWord/` (or `local/` for custom models)
3. Name must match: `my_model.tflite` + `my_model.json`
4. Reference by ID: `script/run --name MyVA --wake-model my_model`
5. Persist in `preferences/user/MyVA.json` → `active_wake_words: ["my_model", "stop"]` to enable by default

### Debugging Audio Issues

- List input/output devices: `script/run --name Test --list-input-devices` / `--list-output-devices`
- Check PulseAudio/PipeWire status: `pactl list sources` or `wpctl status`
- Enable debug logging: `script/run --name MyVA --debug` (look for audio thread startup messages)
- Verify 16kHz mono: `ffprobe -i audio_file.wav` or equivalent

### Customizing LED Colors

Edit `led/state_patterns.py` to adjust RGB values for listening, processing, TTS, muted states.

### Integrating with Music Service

See `Squeezelite/Setup Manual` for Music Assistant (Squeezelite) auto-ducking setup; requires coordinator systemd service and HA automation rules.

### Testing Changes

- Run in foreground: `script/run --name TestVA --debug`
- Watch logs: `journalctl -u TestVA.service -f` (for systemd service)
- Validate config: no error output from script/run during startup means preferences loaded correctly
- HA logs: Home Assistant ESPHome integration logs connection/disconnection events

## Code Style & Standards

- **Python Version:** 3.9+ (tested on 3.11, 3.12, 3.13)
- **Formatting:** Black (100-char line width inferred from pyproject.toml)
- **Import Order:** isort with Black-compatible profile
- **Type Hints:** mypy strict mode (see mypy.ini)
- **Linting:** pylint + flake8
- **Testing:** pytest on tests/ (currently minimal; placeholder test in test_placeholder.py)
- **Naming Conventions:**
  - Classes: CamelCase (e.g., `VoiceSatelliteProtocol`, `MpvMediaPlayer`)
  - Functions/Methods: snake_case (e.g., `_audio_detection_loop`, `handle_message`)
  - Constants: UPPER_SNAKE_CASE (e.g., `_WAKEWORDS_DIR`, `_REPO_DIR`)
  - Private: leading underscore (e.g., `_buffer`, `_on_end_file`)

## Troubleshooting

### Instance Won't Start

- Check preferences: `cat preferences/user/NAME_cli.json`
- Verify port not in use: `lsof -i :PORT` or `ss -tulpn | grep PORT`
- Check device names: `script/run --name Test --list-input-devices`
- Enable debug: `script/run --name NAME --debug` and look for initialization errors

### HA Can't Find Satellite

- Verify Zeroconf is advertised: `avahi-browse -a -r | grep MyVA` (if avahi installed)
- Check firewall: satellite listens on `0.0.0.0:PORT` (all interfaces)
- Restart HA ESPHome integration after deploying satellite
- Manual add: Settings → Devices & Services → ESPHome → "Create Manual Entry"

### No Audio Detected / Wake Word Not Triggering

- Check input device: `script/run --name Test --list-input-devices`
- Verify microphone is unmuted and recording: `arecord -d 3 /tmp/test.wav && aplay /tmp/test.wav`
- Adjust refractory: `--refractory-seconds 0.5` (faster re-trigger)
- Check wake word model exists: `ls wakewords/your_model.*`
- Enable debug logging: look for "Audio input thread" and "wake word" messages

### False Triggers / Echo Feedback

- Increase refractory: `--refractory-seconds 3.0`
- Enable `--disable-wakeword-during-tts`
- Reduce microphone gain if input level is too high
- Consider echo cancellation via PulseAudio/PipeWire module-echo-cancel

### Systemd Service Stuck/Not Starting

- Check service: `systemctl --user status NAME.service`
- View logs: `journalctl --user -u NAME.service -n 50`
- Restart manually: `systemctl --user restart NAME.service`
- Enable linger (so services survive logout): `loginctl enable-linger`

### Manager Can't Control Instances

- Verify scripts exist: `ls -la script/{deploy,remove,restart,status}`
- Check manager service: `systemctl --user status NAME_manager.service`
- Verify instance services are managed by manager (check ManagerConfig in device_manager.py)
