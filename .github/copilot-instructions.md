# Linux Voice Assistant - AI Agent Instructions

## Big picture
- Voice satellite for Home Assistant using the ESPHome protocol; each instance is a networked device with a unique port and MAC.
- Core flow: audio input -> wake word -> stream audio to HA -> HA STT/intent/TTS -> local TTS playback with ducking -> LED feedback.
- Single asyncio event loop; shared runtime state lives in `ServerState` in `linux_voice_assistant/models.py`.

## Key files and responsibilities
- `linux_voice_assistant/satellite.py`: main voice pipeline, wake word handling, audio streaming, timers, LED feedback.
- `linux_voice_assistant/api_server.py`: ESPHome protocol server and message parsing; `APIServer.handle_message()` dispatches entity updates.
- `linux_voice_assistant/entity.py`: ESPHome entities (media player, text/sensor attributes) registered in `ServerState.entities`.
- `linux_voice_assistant/__main__.py`: CLI entry, preferences loading, wake word discovery, event loop setup.
- `linux_voice_assistant/mpv_player.py`: audio playback and music ducking for announcements.
- `linux_voice_assistant/zeroconf.py`: mDNS discovery for Home Assistant.

## Developer workflows
- Setup: `script/setup` (creates venv and installs deps).
- Run foreground: `script/run --name NAME`.
- Deploy systemd user service: `script/deploy NAME` (auto-assigns port starting at 6053 and MAC).
- Manage services: `script/status`, `script/restart`, `script/stop NAME`, `script/remove NAME`.
- Audio devices: `script/run --name Test --list-input-devices` / `--list-output-devices`.

## Configuration and data
- Preferences live in `preferences/user/`:
  - `NAME_cli.json` for CLI/runtime settings (port, devices, etc.).
  - `NAME.json` for wake word configuration.
  - `ha_settings.json` for HA connection.
- Wake words are discovered from `wakewords/` using paired `*.json` + `*.tflite` models.

## Conventions and gotchas
- All scripts in `script/` are Python (not shell) and are venv-aware.
- Microphone input must be 16kHz mono.
- Audio backend uses PulseAudio via `soundcard`; device listing is the supported way to select input/output.
- Pi LED feedback uses `/sys/class/leds/PWR/trigger` (see `satellite.py`).

## Integration points
- Home Assistant via ESPHome integration; instances are added by IP:port.
- Zeroconf publishes the device for HA discovery.
- `mpv` is required for playback (system dependency in README).
