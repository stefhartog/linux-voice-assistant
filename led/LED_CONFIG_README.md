# LED Configuration and Pattern System

This LED system is driven by a JSON configuration file (`led_config.json`) that defines all colors, animations, brightness levels, and state-to-animation mappings. This makes the system highly configurable without needing to modify Python code.

## Files

- **`led_config.json`** - Central configuration file defining all LED states, patterns, colors, and events
- **`state_patterns.py`** - Animation functions and utilities; loads config and provides reusable animation interface
- **`led_feedback.py`** - Systemd journal listener that watches LVA events and triggers LED animations
- **`led_reset.py`** - Utility to turn all LEDs off

## Configuration Structure

### Hardware Settings
```json
"hardware": {
  "num_leds": 8,
  "spi_bus": 1,
  "spi_device": 0,
  "spi_speed_hz": 4000000
}
```

### Global Brightness
```json
"brightness": {
  "global": 0.2,           // Overall multiplier (0.0-1.0)
  "indicator_led": 0.15    // First LED indicator brightness
}
```

### Color Palette
Define named colors once, reuse everywhere:
```json
"colors": {
  "blue": [0, 0, 50],
  "green": [0, 50, 0],
  "red": [50, 0, 0],
  "purple": [40, 0, 40],
  ...
}
```

### States (Animation Definitions)
Each state defines an animation, color, and parameters:
```json
"states": {
  "listening": {
    "animation": "listening_inward",
    "color": "blue",
    "brightness_multiplier": 1.0,
    "animation_params": {
      "step_delay": 0.12,
      "hold_delay": 0.1
    }
  },
  ...
}
```

Available animations:
- **`listening_inward`** - Sweep from edges to center
- **`cylon_bounce`** - Moving light bounces back and forth
- **`pulse_wave`** - Sinusoidal wave across LEDs
- **`color_cycle_breathing`** - Breathing in/out animation
- **`solid_color`** - Solid color display
- **`all_off`** - Turn all LEDs off

### Event Mapping
Maps journal events to LED states:
```json
"events": {
  "VOICE_ASSISTANT_RUN_START": "voice_stream",
  "VOICE_ASSISTANT_INTENT_START": "processing",
  "VOICE_ASSISTANT_TTS_START": "tts_active",
  "TTS_RESPONSE_FINISHED": "listening",
  ...
}
```

## Usage

### From Python Code

**Play animation for a state:**
```python
from led.state_patterns import play_state_animation
import threading

stop_event = threading.Event()
play_state_animation("listening", stop_event=stop_event)
```

**Get configuration for a state:**
```python
from led.state_patterns import get_state_config, resolve_color

config = get_state_config("listening")
color = resolve_color(config["color"])
params = config["animation_params"]
```

**Resolve color names to RGB:**
```python
from led.state_patterns import resolve_color

rgb = resolve_color("blue")  # Returns (0, 0, 50)
```

### From Command Line

Test animations interactively:
```bash
python led/state_patterns.py
```

This lists all available states and lets you test them by name.

## Customization

### Change Colors
Edit `led_config.json` color definitions:
```json
"colors": {
  "blue": [0, 0, 80],  // Brighter blue
  "custom_Purple": [50, 0, 50]
}
```

### Adjust Animation Timing
Edit animation parameters in state definitions:
```json
"listening": {
  "animation_params": {
    "step_delay": 0.2,    // Slower animation
    "hold_delay": 0.15
  }
}
```

### Change Overall Brightness
Edit global brightness multiplier:
```json
"brightness": {
  "global": 0.3   // 30% brightness instead of 20%
}
```

### Add New States
1. Add color names if needed to `colors`
2. Add state definition to `states`
3. Map events to it in `events` if desired

Example—add a "custom_alert" state:
```json
"states": {
  "custom_alert": {
    "animation": "pulse_wave",
    "color": "red",
    "brightness_multiplier": 1.0,
    "animation_params": {
      "min_brightness": 10,
      "step_delay": 0.06
    }
  }
},
"events": {
  "CUSTOM_ALERT_EVENT": "custom_alert"
}
```

Then in code:
```python
play_state_animation("custom_alert")
```

## LED Layout

- **LED 0** - Indicator (very dim, always on)
- **LEDs 1-7** - Main animation area

The `listening_inward` animation uses:
- Outer LEDs (0-6 → 7), bouncing inward
- Center position (3-4) for sustained state

## Integration with LVA

The `led_feedback.py` service watches LVA systemd journal logs and automatically triggers LED animations based on voice events:

```
LVA event detected → Check events map → Get state name → Play animation
```

Current event mappings in config:
- `VOICE_ASSISTANT_RUN_START` → `voice_stream` (yellow breathing)
- `VOICE_ASSISTANT_INTENT_START` → `processing` (purple cylon)
- `VOICE_ASSISTANT_TTS_START` → `tts_active` (green breathing)
- `TTS_RESPONSE_FINISHED` → `listening` (idle blue sweep)

## Technical Notes

### Config Loading
Config is loaded once at module import and cached. To reload after config changes:
```python
import importlib
import led.state_patterns
importlib.reload(led.state_patterns)
```

### Color Order
Hardware uses GRB order (Green, Red, Blue) internally for WS2812 compatibility. Config values are RGB (Red, Green, Blue); conversion happens automatically.

### Stop Events
All animations accept a `threading.Event` for graceful shutdown:
```python
stop_event = threading.Event()
play_state_animation("listening", stop_event=stop_event)
# ... later
stop_event.set()  # Animation stops cleanly
```

## Troubleshooting

**LEDs not responding:**
- Check SPI is enabled: `ls /dev/spidev*`
- Verify config `spi_bus` and `spi_device` match your hardware
- Check brightness values are not 0

**Wrong colors:**
- Verify color names match config palette
- Check RGB values (0-255 range)
- Adjust global brightness if colors are too dim

**Animation timing issues:**
- Increase `step_delay` in animation_params for slower animations
- Decrease for faster animations (0.01 min recommended)

**Config not loading:**
- Check JSON syntax: `python -m json.tool led_config.json`
- Verify file path is correct
- Check file permissions: `chmod 644 led_config.json`
