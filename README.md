# Linux Voice Assistant

An alpha Linux multi-instance voice satellite for [Home Assistant][homeassistant] using the [ESPHome][esphome] protocol. Turn any Linux device into a voice-controlled assistant with wake word detection, voice conversations, announcements, LED feedback, Bluetooth audio, and centralized device management.

**Created by:** [Michael Hansen](https://github.com/synesthesiam) and [The Home Assistant Authors](https://github.com/OHF-Voice)

## Features

### Voice Satellite Core
- 🎙️ **Local Wake Word Detection** - Multiple wake words (Alexa, Hey Jarvis, Okay Nabu, and more) using microWakeWord and openWakeWord
- 💬 **Full Voice Pipeline** - Speech-to-text, intent processing, and text-to-speech through Home Assistant
- 📢 **Announcements** - Play TTS announcements with automatic music ducking
- ⏲️ **Timer Support** - Voice-controlled timers with callbacks
- 🔄 **Multi-Instance** - Run multiple voice satellites on the same machine with unique wake words and audio devices
- 🚀 **Production Ready** - Systemd service integration with automatic restarts and persistent sessions
- 🎛️ **Audio Flexibility** - Supports PulseAudio/PipeWire with echo cancellation and custom audio devices

### Advanced Features
- 🔵 **Bluetooth Audio** - Pair and connect Bluetooth speakers/headphones with auto-reconnect support
- 💡 **LED Feedback** - Visual feedback via WS2812 LED strips (listening, processing, speaking, muted states)
- 📊 **Device Manager** - Centralized control panel for multiple instances with system monitoring (CPU, temperature, memory, disk)
- 🎵 **Music Assistant Integration** - Squeezelite support with automatic music ducking during voice interactions
- 🖥️ **Screen Management** - Auto-wake/sleep displays during voice activity (X11 DPMS support)
- 🔇 **Smart Mute** - System-wide mute state with LED indicators and wake word suppression during TTS

Runs on Linux `aarch64` and `x86_64` platforms. Tested with Python 3.13, 3.12, and 3.11.

## Installation

### System Requirements

Install required system dependencies:

```sh
sudo apt-get update && sudo apt-get install -y portaudio19-dev build-essential libmpv-dev
```

**Core packages** (required for all installations):
* `libportaudio2` or `portaudio19-dev` - Audio input support (soundcard library)
* `build-essential` - Compilation tools for pymicro-features
* `libmpv-dev` - Audio output and media playback

**Optional packages** (for advanced features):
- **BlueZ** - Bluetooth audio device management
  ```sh
  sudo apt-get install bluez bluez-tools
  ```
- **spidev** - LED strip feedback (WS2812)
  ```sh
  .venv/bin/pip install spidev
  ```
- **xset** - Screen management (usually pre-installed on X11 systems)
  ```sh
  sudo apt-get install x11-xserver-utils
  ```

### Quick Start

Clone the repository and run setup:

```sh
git clone https://github.com/OHF-Voice/linux-voice-assistant.git
cd linux-voice-assistant
script/setup
```

This creates a Python virtual environment and installs all dependencies.

## Usage

### Development Mode (Foreground)

For testing and development, run an instance in the foreground:

```sh
script/run --name "MyVoiceAssistant"
```

This auto-creates preference files in `preferences/user/` and assigns a unique port and MAC address.

### Production Deployment (Background Service)

For production use on servers or Raspberry Pi, deploy as a systemd service:

```sh
script/deploy MyVoiceAssistant
```

This will:
- Create all necessary preference files
- Auto-assign a unique port (starting from 6053) and MAC address
- Install a systemd user service
- Enable persistent user sessions (survives reboots and SSH disconnects)
- Start the service immediately

#### Deploy Multiple Instances

You can run multiple voice satellites on the same machine with different wake words and audio devices:

```sh
script/deploy Kitchen LivingRoom Bedroom --wake-model hey_jarvis
```

Each instance gets its own port, MAC address, and configuration.

### Device Manager (Optional)

Deploy a centralized device manager to control all instances, manage Bluetooth devices, and monitor system health:

```sh
script/deploy-manager MyDeviceManager
```

The device manager provides:
- **Instance Control** - Start/stop/restart/remove instances from Home Assistant
- **System Monitoring** - CPU usage, temperature, memory, disk space sensors
- **Bluetooth Management** - Scan, pair, connect, and forget Bluetooth audio devices
- **Service Status** - Monitor Squeezelite and LED feedback service states
- **System Mute** - Toggle microphone mute state across all instances

Add the manager to Home Assistant using port 6152 (default) or your custom port.

### Managing Instances

```sh
script/status                  # Show all instances and service status
script/restart                 # Restart all running instances
script/restart MyVoice         # Restart specific instance
script/stop MyVoiceAssistant   # Stop a specific instance
script/remove Kitchen          # Remove instance and service

# Manager-specific commands
script/restart-manager         # Restart manager
script/remove-manager          # Remove manager service
```

### Audio Device Configuration

List available devices:

```sh
script/run --name Test --list-input-devices   # List microphones
script/run --name Test --list-output-devices  # List speakers
```

Configure devices during deployment:

```sh
script/deploy MyVA --audio-input-device 1 --audio-output-device "hdmi"
```

**Important:** Microphone must support 16kHz mono audio.

## Wake Word Configuration

### Default Wake Words

The following wake words are included:
- `okay_nabu` (default)
- `alexa`
- `hey_jarvis`
- `hey_mycroft`
- `hey_luna`
- `okay_computer`

Change the wake word:

```sh
script/deploy MyVA --wake-model hey_jarvis
```

### Custom Wake Words

Add custom wake words from the [Home Assistant Wake Words Collection][wakewords-collection]:

1. Download a `.tflite` model (e.g., `glados.tflite`)
2. Create a config file `glados.json`:

```json
{
  "type": "openWakeWord",
  "wake_word": "GLaDOS",
  "model": "glados.tflite"
}
```

3. Place both files in a directory and add it:

```sh
script/run --name MyVA --wake-word-dir /path/to/custom/wakewords
```

The system supports both [microWakeWord][microWakeWord] and [openWakeWord][openWakeWord] models.

## Architecture Overview

The Linux Voice Assistant consists of several components that work together:

### Core Components

- **Voice Satellite** - Main voice assistant instance that handles wake word detection, audio streaming, and TTS playback
- **API Server** - ESPHome protocol implementation for Home Assistant integration
- **Media Player** - mpv-based audio playback with automatic music ducking
- **Entity System** - ESPHome entities (switches, buttons, selectors, sensors) exposed to Home Assistant

### Optional Components

- **Device Manager** - Centralized control panel for managing multiple satellites, monitoring system resources, and controlling Bluetooth devices
- **LED Feedback Service** - Standalone service for visual feedback via WS2812 LED strips
- **Bluetooth Module** - Async Bluetooth device management via BlueZ/D-Bus
- **Squeezelite Integration** - Music Assistant playback coordination

### Data Flow

1. **Wake Word** → Microphone captures audio → Wake word model detects trigger
2. **Voice Streaming** → Audio stream sent to Home Assistant via ESPHome protocol
3. **Processing** → HA performs STT → Intent recognition → TTS generation
4. **Response** → TTS audio returned and played locally with music ducking
5. **Feedback** → LED strips show state, screen wakes/sleeps based on activity

Each voice satellite runs as an independent systemd user service with its own port, MAC address, and configuration files.

## Connecting to Home Assistant

### Voice Satellite Instances

1. In Home Assistant, go to **Settings → Devices & services**
2. Click **Add Integration**
3. Search for and select **ESPHome**
4. Choose **Set up another instance of ESPHome**
5. Enter your Linux device's IP address with port (default: `6053`)
   - Example: `192.168.1.100:6053`
6. Click **Submit**

Your voice satellite will appear as a new device with media player and sensor entities.

### Device Manager (Optional)

Add the device manager using port 6152 (or your custom port):

1. Follow the same ESPHome integration steps above
2. Enter your device's IP with port `6152`
   - Example: `192.168.1.100:6152`
3. Click **Submit**

The device manager device will appear with:
- **Switches** - Enable/disable individual instances
- **Buttons** - Restart/remove instances, Bluetooth controls
- **Selectors** - Wake word selection, audio device selection, Bluetooth device selection
- **Sensors** - CPU usage, temperature, memory, disk space, service status

### Multi-Instance Setup

Each instance uses a unique port. Find assigned ports:

```sh
cat preferences/user/*_cli.json | grep port
```

Add each instance separately in Home Assistant using its unique port.

## Advanced Configuration

### Bluetooth Audio

The device manager includes built-in Bluetooth device management via Home Assistant entities:

1. Deploy the device manager: `script/deploy-manager MyManager`
2. In Home Assistant, use the Bluetooth controls:
   - **Bluetooth Scan** button - Discover nearby devices
   - **Bluetooth Device** selector - Choose device to connect
   - **Bluetooth Refresh** button - Update connection status
   - **Bluetooth Forget All** button - Remove all paired devices

Bluetooth audio devices will auto-reconnect on system startup when the device manager is running.

**Manual Bluetooth Setup** (without manager):

```python
from bluetooth import BlueZHelper
import asyncio

async def pair_speaker():
    helper = BlueZHelper()
    # Scan for 10 seconds
    await helper.scan(duration_seconds=10)
    # List audio devices
    devices = await helper.list_devices(audio_only=True)
    for device in devices:
        print(f"{device.name} - {device.address}")
    # Pair and connect (get device_path from list_devices_with_paths)
    # await helper.pair_trust_connect(device_path)

asyncio.run(pair_speaker())
```

### LED Feedback

Visual feedback via WS2812 LED strips for voice assistant states:

**Requirements:**
- SPI-enabled device (Raspberry Pi, Orange Pi, etc.)
- WS2812 LED strip connected to SPI pins
- Python `spidev` package

**Installation:**

```sh
# Enable SPI on your device (Raspberry Pi example)
sudo raspi-config  # Interface Options → SPI → Enable

# Install spidev in the project venv
.venv/bin/pip install spidev

# Install and start the LED service
systemctl --user enable /home/$USER/linux-voice-assistant/led/led_feedback.service
systemctl --user start led_feedback.service
```

**LED States:**
- **Dim white** - Idle, waiting for wake word
- **Bright blue** - Listening for command
- **Purple pulse** - Processing intent
- **Green pulse** - Speaking TTS response
- **Red solid** - Muted

The LED service automatically discovers all voice assistant instances and monitors their logs in real-time.

### Squeezelite / Music Assistant Integration

Integrate with [Music Assistant][music-assistant] for seamless music playback with automatic ducking during voice interactions:

1. Follow the setup guide in `Squeezelite/Setup Manual`
2. Deploy Squeezelite as a user service targeting your Home Assistant IP
3. Configure a unique device name per machine
4. Use PipeWire for audio output (`-o pipewire`)
5. Deploy device manager to monitor Squeezelite service status

The voice assistant will automatically duck (lower volume) music during wake word detection and TTS playback, then restore volume when finished.

### Screen Management

Automatically wake/sleep displays during voice interactions using X11 DPMS:

```sh
script/deploy MyVoice --screen-management 30
```

- Screen wakes on wake word detection
- Screen sleeps after 30 seconds of inactivity
- Requires X11 display and `xset` command

### Wake Word Disable During TTS

Prevent false wake word triggers during TTS playback:

```sh
script/deploy MyVoice --disable-wakeword-during-tts
```

This temporarily disables wake word detection while the assistant is speaking, reducing accidental activations from the speaker output.

### Acoustic Echo Cancellation

Enable PulseAudio echo cancellation for better wake word detection:

```sh
pactl load-module module-echo-cancel \
  aec_method=webrtc \
  aec_args="analog_gain_control=0 digital_gain_control=1 noise_suppression=1"
```

Verify the devices are available:

```sh
pactl list short sources
pactl list short sinks
```

Use the echo-cancelled devices:

```sh
script/deploy MyVA \
  --audio-input-device 'Echo-Cancel Source' \
  --audio-output-device 'pipewire/echo-cancel-sink'
```

### Configuration Files

The system uses a multi-tier preferences structure stored in `preferences/user/`:

**Per-Instance Configuration:**
- `{NAME}_cli.json` - CLI arguments, port, MAC address, audio devices, screen management settings
- `{NAME}.json` - Active wake words list for the instance

**Device Manager Configuration:**
- `{NAME}_manager.json` - Manager CLI settings and port configuration

**Global Settings:**
- `ha_settings.json` - Shared across all instances
  ```json
  {
    "ha_base_url": "http://homeassistant.local:8123",
    "ha_token": "your_long_lived_access_token",
    "wake_word_friendly_names": {
      "okay_nabu": "Okay Nabu",
      "hey_jarvis": "Hey Jarvis"
    },
    "ha_history_entity": "sensor.voice_history"
  }
  ```

**System State:**
- `/dev/shm/lvas_system_mute` - Shared memory file for system-wide mute state (written by satellites, read by LED service and manager)

Edit these files to customize behavior without changing command-line arguments. Changes are automatically reloaded on service restart.

### Template Defaults

Create custom defaults for new instances in `preferences/default/default_user_cli.json`:

```json
{
  "wake_model": "hey_jarvis",
  "audio_input_device": "1",
  "refractory_seconds": 3.0
}
```

New instances will inherit these settings unless overridden.

## Troubleshooting

### Port Already in Use

Each instance needs a unique port. The system auto-assigns ports starting from 6053. Set a custom port:

```sh
script/deploy MyVA --port 6055
```

Or change the base port for all instances:

```sh
export LVAS_BASE_PORT=7000
script/deploy MyVA
```

### Service Management

Check service logs:

```sh
journalctl --user -u MyVoiceAssistant.service -f
```

Restart a misbehaving instance:

```sh
systemctl --user restart MyVoiceAssistant.service
# Or use the helper script
script/restart MyVoiceAssistant
```

### Audio Issues

Verify your microphone supports 16kHz mono:

```sh
script/run --name Test --list-input-devices
```

Test audio capture in development mode to see real-time detection.

For echo cancellation issues, verify the echo-cancel devices exist:

```sh
pactl list short sources | grep echo
pactl list short sinks | grep echo
```

### Bluetooth Connection Issues

If Bluetooth devices won't pair or connect:

1. Ensure BlueZ is running: `systemctl status bluetooth`
2. Verify device is in pairing mode
3. Check device manager logs: `journalctl --user -u *_manager.service -f`
4. Try manual pairing first with `bluetoothctl` to verify device works
5. Use "Bluetooth Forget All" and re-pair from scratch

### LED Feedback Not Working

Common LED issues:

1. **SPI not enabled**: Enable SPI in your system configuration
   ```sh
   # Raspberry Pi
   sudo raspi-config  # Interface Options → SPI
   ```
2. **Wrong SPI device**: Check available devices
   ```sh
   ls -l /dev/spidev*
   ```
3. **Permissions**: Ensure user is in `spi` or `gpio` group
   ```sh
   sudo usermod -a -G spi,gpio $USER
   # Log out and back in
   ```
4. **Service not running**: Check LED service status
   ```sh
   systemctl --user status led_feedback.service
   ```

### Screen Management Not Working

Ensure you're running on an X11 display (not Wayland) and `xset` is installed:

```sh
echo $DISPLAY  # Should show :0 or similar
xset q         # Should show DPMS settings
```

For headless/SSH sessions, set the DISPLAY variable:

```sh
export DISPLAY=:0
script/deploy MyVA --screen-management 30
```

## Contributing

Contributions are welcome! This project uses:
- **black** + **isort** for code formatting
- **flake8**, **pylint**, **mypy** for linting
- **pytest** for testing

Development workflow:

```sh
script/setup --dev          # Install dev dependencies
script/format               # Format code
script/lint                 # Check code quality
script/test                 # Run tests
```

## License

Apache License 2.0 - See [LICENSE.md](LICENSE.md) for details.

## Credits

**Original Creator:** [Michael Hansen](https://github.com/synesthesiam) (synesthesiam)  
**Contributors:** [The Home Assistant Authors](https://github.com/OHF-Voice) and [community contributors](https://github.com/OHF-Voice/linux-voice-assistant/graphs/contributors)

Built with:
- [Home Assistant](https://www.home-assistant.io/) - Open source home automation
- [ESPHome](https://esphome.io/) - Device communication protocol
- [microWakeWord](https://github.com/kahrendt/microWakeWord) - Efficient wake word detection
- [openWakeWord](https://github.com/dscripka/openWakeWord) - Open source wake word models
- [Music Assistant](https://music-assistant.io/) - Multi-room audio platform (via Squeezelite)
- [BlueZ](http://www.bluez.org/) - Official Linux Bluetooth stack
- [python-mpv](https://github.com/jaseg/python-mpv) - Audio playback with ducking support

<!-- Links -->
[homeassistant]: https://www.home-assistant.io/
[esphome]: https://esphome.io/
[microWakeWord]: https://github.com/kahrendt/microWakeWord
[openWakeWord]: https://github.com/dscripka/openWakeWord
[wakewords-collection]: https://github.com/fwartner/home-assistant-wakewords-collection
[glados]: https://github.com/fwartner/home-assistant-wakewords-collection/blob/main/en/glados/glados.tflite
[music-assistant]: https://music-assistant.io/
