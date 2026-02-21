# LED Feedback Service

This folder contains the LED feedback service used to drive a WS2812-style LED strip via SPI and react to voice assistant events from Home Assistant via MQTT or LVA log events via journalctl.

## What it does
- Runs a standalone service that monitors voice assistant state changes and switches LED patterns based on events.
- **Primary mode (MQTT)**: Subscribes to Home Assistant MQTT topics for real-time satellite state updates (listening, processing, responding, error)
- **Fallback mode (journalctl)**: Tails LVA systemd user logs if MQTT is unavailable
- Uses SPI (spidev) to drive an 8 LED strip (LED 0 taped off, LEDs 1-7 active for animations)
- Maps voice assistant states to animations (listening, intent, TTS, idle, mute, error)

## Files
- led_feedback.py: Main log follower, event parser, and pattern switcher.
- state_patterns.py: SPI init and LED animation functions.
- led_feedback.service: systemd user unit to run led_feedback.py.
- led_reset.py: one-shot helper to turn LEDs off and close SPI.

## Dependencies
- Python packages: spidev, paho-mqtt
- SPI enabled on the device (e.g., /dev/spidev1.0)
- Systemd user services (for journalctl and the service unit)
- Home Assistant with MQTT integration (for primary MQTT mode)

## Operating Modes

### Primary Mode: MQTT (Recommended)
- Service subscribes to Home Assistant MQTT broker for satellite state changes
- Requires MQTT configuration in `led_config.json` (broker address, credentials)
- Real-time feedback from HA's actual state (not dependent on local logs)
- Requires HA automation to publish satellite states to MQTT topics
- Falls back to journalctl automatically if MQTT connection fails

Configuration in `led_config.json`:
```json
"mqtt": {
  "enabled": true,
  "broker": "192.168.1.101",
  "port": 1883,
  "username": "mqtt",
  "password": "your_password",
  "topic_prefix": "nodes",
  "state_topic_suffix": "va/state",
  "mute_topic_suffix": "va/manager_mute"
}
```

### Fallback Mode: Journalctl
- If MQTT is disabled or connection fails, service falls back to tailing LVA logs
- Reacts to LVA_EVENT messages and system mute state from `/dev/shm/lvas_system_mute`
- Works independently without external MQTT broker
- Less immediate (log-based) but reliable fallback

## Event Sources

### MQTT Mode (Primary)
- Topics: `nodes/{area}/va/state` - Satellite state (idle, listening, processing, responding, error)
- Topics: `nodes/{area}/va/manager_mute` - System mute state (on/off)
- Requires Home Assistant automation to publish satellite state changes to these topics

### Journalctl Mode (Fallback)
- LVA_EVENT lines (listening, intent, TTS events)
- "Connected to Home Assistant"
- "Assistant mute changed: True/False"
- "Wakeword triggered while muted."
- `/dev/shm/lvas_system_mute` - System mute state file

## Home Assistant Integration (MQTT Mode)

### 1. Configure MQTT Credentials
Add Home Assistant MQTT credentials to `led_config.json`:
```json
"mqtt": {
  "enabled": true,
  "broker": "YOUR_HA_IP",
  "port": 1883,
  "username": "mqtt_username",
  "password": "mqtt_password"
}
```

### 2. Create HA Automation (YAML)
Add this automation to Home Assistant to publish satellite state changes to MQTT:
```yaml
aliases: VA State to MQTT
description: Publish voice assistant satellite states to MQTT for LED feedback
triggers:
  - trigger: state
    entity_id:
      - assist_satellite.living_room
      - assist_satellite.bedroom
    # Add more satellite entities as needed
actions:
  - if:
      - condition: template
        value_template: "{{ trigger.entity_id.split('.')[1] | default('unknown') }}"
    then:
      - action: mqtt.publish
        data:
          topic: "nodes/{{ trigger.entity_id.split('.')[1] }}/va/state"
          payload: "{{ trigger.to_state.state }}"
mode: parallel
```

Also publish manager mute state if using device manager:
```yaml
# Add trigger for manager mute switches
  - trigger: state
    entity_id:
      - switch.manager_mute_living_room
      - switch.manager_mute_bedroom
actions:
  - action: mqtt.publish
    data:
      topic: "nodes/{{ device_attr(trigger.entity_id, 'name').split()[2].lower() }}/va/manager_mute"
      payload: "{{ 'on' if trigger.to_state.state == 'on' else 'off' }}"
```

## Quick Installation

Run the automated install script:
```bash
led/install
```

This will:
- Check for SPI device availability
- Install Python packages: spidev, paho-mqtt
- Create and enable the systemd user service
- Set up SPI device permissions
- Start the LED feedback service

## Manual setup
1) Enable SPI on your device (Raspberry Pi/Orange Pi tooling or config).
2) Install spidev in the LVA venv:
   - .venv/bin/pip install spidev
3) Create and install the systemd user service:
   - led/install (recommended) or manually copy service file
4) Start the service:
   - systemctl --user start led_feedback.service

## Service management
- Status:  systemctl --user status led_feedback.service
- Restart: systemctl --user restart led_feedback.service
- Stop:    systemctl --user stop led_feedback.service
- Disable: systemctl --user disable led_feedback.service
- Logs:    journalctl --user -u led_feedback.service -f

## Useful commands
- **Test LED patterns interactively**:
  ```bash
  .venv/bin/python3 led/state_patterns.py
  ```

- **Reset LEDs (turn all off)**:
  ```bash
  .venv/bin/python3 led/led_reset.py
  ```

- **View live log stream** (what the LED service sees):
  ```bash
  journalctl --user -u led_feedback.service -f
  ```

- **Monitor voice assistant events**:
  ```bash
  journalctl --user-unit bedroom_va_A.service -f -n 0 -o cat | grep LVA_EVENT
  ```

## Configuration

All LED behavior (colors, animations, timing, MQTT settings) is configured in `led_config.json`:
- **hardware**: SPI device path, number of LEDs, SPI speed
- **brightness**: Global brightness multiplier and per-state overrides
- **colors**: Named RGB color definitions
- **states**: Animation type, color, and timing for each state (idle, listening, processing, responding, error, etc.)
- **events**: Maps LVA_EVENT names to state animations (fallback mode only)
- **mqtt**: MQTT broker configuration and topic settings

## Notes
- LED brightness is controlled by the `brightness` section in `led_config.json`
- LED 0 is taped off (black prepended so LEDs 1-7 are active/centered)
- State mapping: HA states (idle, listening, processing, responding) → LED states with animations
- When switching states, previous animation is properly stopped before starting the new one
- MQTT mode auto-falls back to journalctl if MQTT is disabled or connection fails
