# Linux Voice Assistant - AI Agent Instructions

## Project Overview
A multi-instance Linux voice satellite for Home Assistant using the ESPHome protocol. Supports wake words, announcements, timers, and conversations through Home Assistant's voice pipeline. Designed to run as systemd services on servers and Raspberry Pi devices.

**Key repo**: github.com/OHF-Voice/linux-voice-assistant | **Status**: Alpha (v1.0.0)

## Architecture

### Core Components
- **`satellite.py`** (~680 lines): Main `VoiceSatelliteProtocol` class inheriting `APIServer`. Implements ESPHome server protocol: handles voice events/audio streaming/TTS playback/wake word management/timer events.
- **`api_server.py`** (~180 lines): Base `APIServer(asyncio.Protocol)` implementing ESPHome network protocol. Handles packet parsing, protobuf serialization, HelloRequest/Authentication/PingRequest. Provides abstract `handle_message()` for subclasses. Core packet loop in `data_received()`.
- **`__main__.py`** (~580 lines): Entry point with CLI parsing (argparse), wake word filesystem discovery, preferences loading/migration, audio device enumeration (soundcard), and asyncio event loop setup. Runs audio capture in background thread. Runnable as `python -m linux_voice_assistant --name Test`.
- **`mpv_player.py`**: `MpvMediaPlayer` wrapper around python-mpv. Handles audio playback, music ducking (pauses music during announcements), playlist management, and done callbacks.
- **`entity.py`** (~230 lines): ESPHome entities exposed to HA: `MediaPlayerEntity` (audio control + ducking logic), `TextAttributeEntity` (displays active STT/TTS/assistant text), `SwitchEntity` (toggles—e.g., software mute). Base `ESPHomeEntity` class with abstract `handle_message()` method.
- **`models.py`**: Dataclasses: `Preferences` (per-instance, minimal—just active wake word list), `GlobalPreferences` (shared HA settings), `ServerState` (central mutable container passed through entire app), `AvailableWakeWord` (wake word metadata + dynamic loader), `WakeWordType` enum (micro/openWakeWord).
- **`zeroconf.py`**: Zeroconf/mDNS service discovery for automatic Home Assistant detection.
- **`util.py`**: Helper utilities (e.g., `call_all()` for chaining callbacks).
- **`script/*`**: Zero-dependency Python executables (not shell) for deployment/management/development. All use `#!/usr/bin/env python3`. Key scripts: `run` (dev foreground), `deploy` (systemd installation), `setup` (venv + deps), `status`/`stop`/`restart`/`remove` (instance management), `test`/`lint`/`format` (dev tools).

### Data Flow
1. **Audio input**: Captured from microphone (16kHz mono) in background thread → pushed to `ServerState.audio_queue`
2. **Wake word detection**: Async task monitors queue, runs loaded `MicroWakeWord`/`OpenWakeWord` detectors, triggers voice event on match
3. **Audio streaming**: On wake, `VoiceAssistantAudio` protobuf messages stream audio chunks to Home Assistant via ESPHome protocol
4. **HA processing**: Home Assistant's voice pipeline processes audio (STT→intent→TTS), returns `VoiceAssistantEventResponse` messages + TTS audio URL
5. **Playback & Ducking**: TTS audio downloaded via `urllib`, played via mpv's `announce_player`. If `music_player` is active, it's paused during announcement, resumed on completion
6. **Visual feedback**: Can be provided via neopixel LED ring (optional supplementary service)

### Script System Architecture
All scripts in `script/` are **Python executables** (not shell scripts) with zero external dependencies beyond stdlib (except `distro` which is optional). Key design principles:

- **Self-contained**: Parse CLI args, read/write JSON configs, manage systemd services entirely within script—no imports from main package
- **Venv-aware**: Auto-detect `.venv/` and use appropriate Python interpreter (see [script/run#L51-L53](script/run#L51-L53))
- **Template cascade**: `script/run` and `script/deploy` use intelligent template defaults via `_choose_template()` function:
  1. User custom default (`default_user_cli.json` - allows overriding project defaults)
  2. OS-specific default (`default_wsl_cli.json` for WSL, etc.)
  3. Main fallback (`default_cli.json`)
- **Auto-assignment**: Ports (starting from 6053, or `LVAS_BASE_PORT` env var) and MAC addresses (via `uuid.getnode()`) auto-generated if not specified
- **Preference migration**: Legacy single-file preferences automatically split into per-instance + global on first run (see [__main__.py#L280-L320](__main__.py#L280-L320))
- **Systemd integration**: `script/deploy` enables user linger (via `loginctl enable-linger`) so services persist across logouts/reboots, installs units in `~/.config/systemd/user/`
- **Venv activation**: Scripts auto-activate `.venv/` if present, fall back to system Python with warnings

## Multi-Instance Configuration

### Preferences System (Two-Tier)
The `preferences/user/` directory is created on first run. Each instance has two config files:
- **Per-instance CLI config** (`preferences/user/{NAME}_cli.json`): CLI args, port, MAC address, system info, autostart flag
- **Per-instance preferences** (`preferences/user/{NAME}.json`): Active wake words list only (minimal by design - see `Preferences` dataclass in [models.py](linux_voice_assistant/models.py#L52-L56))
- **Shared/global** (`preferences/user/ha_settings.json`): HA base URL, token, friendly names, history entity (see `GlobalPreferences` in [models.py](linux_voice_assistant/models.py#L59-L66))

### Template Cascade
`script/run` loads defaults with priority:
1. `preferences/default/default_user_cli.json` (user custom defaults)
2. `preferences/default/default_wsl_cli.json` (OS-specific, e.g., WSL)
3. `preferences/default/default_cli.json` (main fallback)

When creating a new instance, `script/run` auto-generates a unique MAC address and port (starting from 6053, incrementing for each instance).

## Developer Workflows

### Setup & Run
```bash
script/setup              # Create venv, install dependencies
script/run --name "MyVA"  # Auto-creates preferences/user/{NAME}_cli.json and {NAME}.json
```

For direct module execution (after venv setup):
```bash
source .venv/bin/activate  # Or let scripts auto-detect venv
python -m linux_voice_assistant --name "Test" --list-input-devices
```

**Note**: `script/setup` can optionally install dev dependencies with `--dev` flag for linting/testing tools.

### Deployment (Production)
```bash
# Deploy and auto-start one or more instances as systemd user services
script/deploy MyVA1 MyVA2 --audio-input-device 0  # Deploy multiple with shared overrides
script/deploy --name MyVA --port 6055             # Deploy single with custom port
```
**Important**: `script/deploy` is the primary deployment tool. It:
- Creates preference files (like `script/run`)
- Enables systemd user linger (persistent user sessions across reboots)
- Installs systemd user service for each instance (`~/.config/systemd/user/{NAME}.service`)
- Starts services immediately
- Sets `autostart: true` by default in CLI config
- Creates convenience symlinks in `preferences/user/` pointing to systemd unit files

**Note**: Older deployments may use manual wrapper scripts (like `lvas_01_wrapper.py`). These are superseded by `script/deploy` but may exist in legacy setups.

### Instance Management
```bash
script/status             # Show all instances and their service status
script/restart            # Restart running instance(s)
script/stop <NAME>        # Stop instance(s)
script/remove <NAME>      # Remove instance config and service
```

### Testing & Linting
```bash
script/test               # Run pytest in tests/
script/format             # black + isort formatting
script/lint               # black --check, isort --check, flake8, pylint, mypy
```

## Key Patterns

### Async/Event-Driven Architecture
The entire app runs on a single asyncio event loop initialized in [__main__.py](linux_voice_assistant/__main__.py#L350). The event loop manages:
- **Audio capture**: Runs in separate thread pushing audio chunks to `ServerState.audio_queue`
- **Wake word detection**: Async task monitors queue, triggers voice events when wake word detected
- **ESPHome server**: `APIServer` (asyncio.Protocol) receives/sends protobuf messages over TCP (port configured per instance)
- **TTS/Announcements**: Non-blocking playback with callbacks via mpv

The event loop is accessible via `asyncio.get_running_loop()` and stored in `VoiceSatelliteProtocol._loop` for scheduling coroutines from synchronous `handle_message()` methods (see Music Ducking pattern below for example).

### State Management (ServerState)
`ServerState` (in [models.py](linux_voice_assistant/models.py#L70-L99)) is the central mutable state container passed through the entire app. Contains:
- **Config**: name, MAC, port (from CLI args and preferences)
- **Audio**: `audio_queue` (Queue[bytes]), wakeup/timer sounds
- **Wake words**: `available_wake_words` (dict by ID), loaded instances in `wake_words` (dict by ID)
- **Players**: `music_player`, `tts_player` (MpvMediaPlayer instances)
- **Entities**: `media_player_entity`, `active_stt_entity`, `active_tts_entity`, `active_assistant_entity`
- **Preferences**: Per-instance config path, per-instance `Preferences`, shared `GlobalPreferences`

Initialize ServerState in [__main__.py](linux_voice_assistant/__main__.py#L180-L250) after loading preferences and discovering wake words.

### Message Handling Pattern
ESPHome protocol messages flow through a three-stage pipeline:
1. **Receive**: `APIServer.data_received()` → `process_packet()` (packet parsing)
2. **Dispatch**: `process_packet()` → `handle_message()` (abstract method in APIServer, implemented in VoiceSatelliteProtocol)
3. **Entity handlers**: `VoiceSatelliteProtocol.handle_message()` dispatches to registered `ESPHomeEntity` subclasses (see [satellite.py](linux_voice_assistant/satellite.py#L307-L365))

Each entity's `handle_message()` returns an iterable of protobuf messages to send back. Common dispatch pattern (see [satellite.py](linux_voice_assistant/satellite.py#L360)):
```python
if isinstance(msg, VoiceAssistantConfigurationRequest):
    yield from self._handle_voice_config(msg)
elif isinstance(msg, VoiceAssistantRequest):
    # Process voice event
```

### Entity Pattern
Entities inherit from `ESPHomeEntity` and are registered in `ServerState.entities`. Key subclasses:
- **MediaPlayerEntity**: Exposes music/TTS playback control, handles ducking for announcements
- **TextAttributeEntity**: Displays active STT/TTS/assistant text in HA UI (read-only in HA)
- **SwitchEntity**: Handles toggle switches (e.g., for software mute)

Each entity registers in `ListEntitiesResponse` with unique `key` and `object_id`. Entities implement `handle_message()` that returns iterable of protobuf response messages. See [entity.py](linux_voice_assistant/entity.py#L25-L232) for implementation patterns.

### Wake Word Loading
Wake words discovered from `wakewords/` subdirectories by scanning `*.json` config files. Two types:
- **microWakeWord**: Config file itself is the model (`.json` contains model data)
- **openWakeWord**: Config references separate `.tflite` model file

Example config (`wakewords/okay_nabu.json`):
```json
{
  "type": "micro",
  "wake_word": "Okay Nabu",
  "trained_languages": ["en"]
}
```

Loaded via `AvailableWakeWord.load()` in [models.py](linux_voice_assistant/models.py#L31-L49), which dynamically imports and instantiates the correct wake word detector class. The `stop.json`/`stop.tflite` model is special-cased and not shown as selectable in HA UI.

### Audio Device Selection
Use `--list-input-devices` / `--list-output-devices` to discover devices. Microphone must support 16kHz mono. Audio input runs in background thread in [__main__.py](linux_voice_assistant/__main__.py#L330-L345), pushing frames to `ServerState.audio_queue`.

### ESPHome Protocol
Communication uses protobuf messages from `aioesphomeapi.api_pb2`. Key messages:
- `VoiceAssistantEventResponse`: Voice pipeline events (STT start/end, TTS start/end, intent results)
- `VoiceAssistantAudio`: Audio chunks sent to HA during conversation
- `VoiceAssistantTimerEventResponse`: Timer events (started, updated, finished)
- `VoiceAssistantConfigurationRequest`: Wake word configuration exchange

Message handling flow: [api_server.py](linux_voice_assistant/api_server.py#L47-L78) `process_packet()` → `handle_message()` (implemented in [satellite.py](linux_voice_assistant/satellite.py)) → `send_messages()`.

### Raspberry Pi Integration
Visual feedback for Raspberry Pi systems is provided via the optional Neopixel LED Ring supplementary service (see **Supplementary Services** section below). This monitors systemd journals for LVA events and drives animations on the LED ring via socket commands.

### Music Ducking (Auto-Volume Control)
When announcements play, music volume is automatically lowered. Implementation in [entity.py](linux_voice_assistant/entity.py#L60-L75): checks `music_player.is_playing`, pauses it, plays announcement via `announce_player`, resumes music on done callback. Separate players allow concurrent state tracking.

### Common Modification Points
- **Adding new wake word types**: Extend `WakeWordType` enum in [models.py](linux_voice_assistant/models.py#L22-L25) and implement `AvailableWakeWord.load()` branch
- **Adding new ESPHome entities**: Subclass `ESPHomeEntity` in [entity.py](linux_voice_assistant/entity.py#L25-L30), register in `ServerState.entities`, handle messages in `VoiceSatelliteProtocol.handle_message()`
- **Adding voice events**: Implement in [satellite.py](linux_voice_assistant/satellite.py#L307-L365) `handle_message()` dispatcher, yield `VoiceAssistantEventResponse` messages
- **Modifying preferences**: Update dataclasses in [models.py](linux_voice_assistant/models.py#L52-L66), migration handled in [__main__.py](linux_voice_assistant/__main__.py#L280-L320)

### Logging & History
- Conversation history logged to `lvas_log` (symlinked to `/dev/shm/lvas_log` for RAM-based logging to reduce disk wear)
- History synced to HA via REST API if `ha_token` and `ha_history_entity` configured in `ha_settings.json`
- Log entries formatted as "User: {stt_text}" and "{assistant_name}: {tts_text}"

### Supplementary Services (Optional)
**Neopixel LED Ring** (`neopixel/` directory) - Visual feedback system separate from main satellite:
- **`neopixel_patterns.py`**: Neopixel ring controller with breathing/pulsing effects, socket-based command interface (`/tmp/neopixel.sock`)
- **`neopixel_lva_monitor.py`**: Monitors systemd journals for LVA events (wake word, STT, intent, TTS, mute changes) and sends commands to neopixel ring via socket
- **Systemd services**: `neopixel_patterns.service` (ring controller) and `neopixel_lva_monitor.service` (event monitor)
- **Event mapping**: Journal log patterns → neopixel commands (`listening`, `processing`, `responding`, `idle`, `mute`)

**Startup Helper** (`lvas_startup/` directory) - Kiosk/desktop integration:
- **`lvas_kiosk.desktop`**: Desktop entry for automatic startup on login
- **`lvas_launch.sh`**: Wrapper script to start satellite with systemd integration
- **`lvas-startup-helper.service`**: Systemd service for auto-launching satellites on multiuser systems

**Squeezelite Integration** (`Squeezelite/` directory) - Music streaming compatibility:
- Setup scripts for Squeezelite (lightweight LMS player) integration with audio ducking

## Dependencies
- **aioesphomeapi**: ESPHome API protocol implementation
- **soundcard**: Audio input (requires `portaudio19-dev`)
- **pymicro-wakeword** / **pyopen-wakeword**: Wake word detection
- **python-mpv**: Audio output (requires `libmpv-dev`)

## Testing Notes
- Minimal test coverage currently (`tests/test_placeholder.py`)
- When adding tests, use `script/test` which activates venv automatically
- Integration tests require Home Assistant instance running

## Common Gotchas
- **Port conflicts**: Each instance needs unique port. Scripts auto-assign starting from 6053 (override with `LVAS_BASE_PORT` env var).
- **MAC spoofing**: Each instance needs unique MAC. Auto-generated if not specified in CLI config.
- **Preferences migration**: Legacy single-file preferences automatically split into per-instance + global files on first run. Old format had all settings in one JSON; new format separates CLI args (`{NAME}_cli.json`), active wake words (`{NAME}.json`), and shared HA settings (`ha_settings.json`).
- **Wake word stop model**: `stop.tflite` is special—not shown as selectable wake word in HA, used internally for ending conversations.
- **Systemd linger**: `script/deploy` enables user linger via `loginctl enable-linger` so services persist across SSH disconnects and reboots.
- **Development vs Production**: Use `script/run` for development (runs in foreground with live logs). Use `script/deploy` for production (installs as systemd service with autostart). Direct module execution (`python -m linux_voice_assistant`) requires manual venv activation and explicit args.
- **Legacy wrapper scripts**: Old deployments used manual `{NAME}_wrapper.py` scripts with hardcoded paths and MAC spoofing. Modern approach uses `script/deploy` which generates systemd units directly without wrapper intermediaries.
- **Preferences load order**: CLI args override defaults in this order: hardcoded defaults → template defaults (default_user_cli.json → default_wsl_cli.json → default_cli.json) → per-instance CLI config → command-line args. See [script/run](script/run#L150-L200) for implementation.
- **Async in message handlers**: `handle_message()` is synchronous (not async) but can access `asyncio.get_running_loop()` to schedule coroutines. Done callbacks in [entity.py](linux_voice_assistant/entity.py#L70-L75) use this pattern.
- **Audio thread safety**: Audio input runs in background thread; always use `ServerState.audio_queue.put()` for thread-safe communication with main event loop.
