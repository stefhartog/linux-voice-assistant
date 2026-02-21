"""LED pattern animations and control.

Loads configuration from led_config.json for colors, brightness, and animation parameters.
"""
import spidev
import time
import math
import json
import os
from pathlib import Path

# Load configuration
CONFIG_PATH = Path(__file__).parent / "led_config.json"
CONFIG_EXAMPLE_PATH = Path(__file__).parent / "led_config.json.example"

CONFIG = None
# Try personal config first, then fall back to example
for config_file in [CONFIG_PATH, CONFIG_EXAMPLE_PATH]:
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
        if config_file == CONFIG_EXAMPLE_PATH:
            print(f"[LED] Using example config from {CONFIG_EXAMPLE_PATH}")
            print(f"[LED] To customize: cp {CONFIG_EXAMPLE_PATH} {CONFIG_PATH} and edit")
        break
    except Exception as e:
        if config_file == CONFIG_EXAMPLE_PATH:
            raise RuntimeError(f"Failed to load LED config from {CONFIG_PATH} or {CONFIG_EXAMPLE_PATH}: {e}")

# Extract hardware and brightness settings
HARDWARE = CONFIG.get("hardware", {})
BRIGHTNESS_CONFIG = CONFIG.get("brightness", {})
COLORS_MAP = CONFIG.get("colors", {})
STATES_MAP = CONFIG.get("states", {})

BRIGHTNESS = BRIGHTNESS_CONFIG.get("global", 0.2)
NUM_LEDS = HARDWARE.get("num_leds", 8)
ACTIVE_LEDS = NUM_LEDS - 1  # LED 0 is taped off, use LEDs 1-7 for animations
SPI_BUS = HARDWARE.get("spi_bus", 1)
SPI_DEVICE = HARDWARE.get("spi_device", 0)
SPI_SPEED = HARDWARE.get("spi_speed_hz", 4000000)

spi = spidev.SpiDev()
spi.open(SPI_BUS, SPI_DEVICE)
spi.max_speed_hz = SPI_SPEED


def resolve_color(color_spec):
    """Resolve a color name or RGB tuple to RGB values.
    
    Args:
        color_spec: Either a color name string or [r, g, b] list
    
    Returns:
        tuple: (r, g, b) values
    """
    if isinstance(color_spec, str):
        if color_spec not in COLORS_MAP:
            raise ValueError(f"Unknown color: {color_spec}. Available: {list(COLORS_MAP.keys())}")
        return tuple(COLORS_MAP[color_spec])
    elif isinstance(color_spec, (list, tuple)) and len(color_spec) == 3:
        return tuple(color_spec)
    else:
        raise ValueError(f"Invalid color spec: {color_spec}")


def get_state_config(state_name):
    """Get animation config for a named state.
    
    Args:
        state_name: State name from config (e.g., "listening", "processing")
    
    Returns:
        dict: State configuration with animation, color, params
    """
    if state_name not in STATES_MAP:
        raise ValueError(f"Unknown state: {state_name}. Available: {list(STATES_MAP.keys())}")
    return STATES_MAP[state_name]

def send_colors(colors):
    """Send RGB colors to WS2812 LEDs via SPI.
    
    Args:
        colors: List of (r, g, b) tuples for LEDs 1-7 (LED 0 is taped off)
    """
    tx_data = []
    # Keep LED 0 off (taped off), prepend black to keep animations centered on LEDs 1-7
    out_colors = [(0, 0, 0)] + list(colors)
    for idx, (r, g, b) in enumerate(out_colors):
        r = int(r * BRIGHTNESS)
        g = int(g * BRIGHTNESS)
        b = int(b * BRIGHTNESS)
        for val in [g, r, b]:  # GRB order
            for i in range(8):
                tx_data.append(0xE0 if (val << i) & 0x80 else 0x80)
    spi.xfer2(tx_data)

def all_off():
    send_colors([(0, 0, 0)] * NUM_LEDS)

def all_off_stoppable(stop_event=None):
    all_off()
    # Wait until stop_event is set, so thread can be joined cleanly
    while not (stop_event and stop_event.is_set()):
        time.sleep(0.05)

# --- Pattern Functions (continuous, blocking) ---
def cylon_bounce(stop_event=None, color=None, **kwargs):
    """Cylon bounce animation.
    
    Args:
        stop_event: threading.Event to signal stop
        color: Color name (string) or RGB tuple (0-255)
        **kwargs: Accept additional parameters from config
    """
    if color is None:
        config = get_state_config("processing")
        color = resolve_color(config["color"])
    else:
        color = resolve_color(color)
    
    tail = [24, 8, 2]
    try:
        while not (stop_event and stop_event.is_set()):
            for i in range(ACTIVE_LEDS * 2 - 2):
                if stop_event and stop_event.is_set():
                    return
                leds = [(0, 0, 0)] * ACTIVE_LEDS
                pos = i if i < ACTIVE_LEDS else (ACTIVE_LEDS * 2 - 2 - i)
                leds[pos] = color
                for t, b in enumerate(tail, 1):
                    if pos - t >= 0:
                        leds[pos - t] = (int(color[0]*b/40), 0, int(color[2]*b/40))
                    if pos + t < ACTIVE_LEDS:
                        leds[pos + t] = (int(color[0]*b/40), 0, int(color[2]*b/40))
                send_colors(leds)
                time.sleep(0.07)
    except KeyboardInterrupt:
        all_off()

def pulse_wave(stop_event=None, color=None, **kwargs):
    """Pulsing wave animation.
    
    Args:
        stop_event: threading.Event to signal stop
        color: Color name (string) or RGB tuple (0-255)
        **kwargs: Accept additional parameters from config
    """
    if color is None:
        config = get_state_config("responding")
        color = resolve_color(config["color"])
    else:
        color = resolve_color(color)
    
    min_brightness = 8
    try:
        phase = 0
        while not (stop_event and stop_event.is_set()):
            leds = []
            for i in range(ACTIVE_LEDS):
                b = int(21 * math.sin((i + phase) * 2 * math.pi / ACTIVE_LEDS) + 29)
                r = int(color[0] * b / 50)
                g = int(color[1] * b / 50)
                b_ = int(color[2] * b / 50)
                leds.append((max(r, min_brightness), max(g, min_brightness), max(b_, min_brightness)))
            send_colors(leds)
            phase = (phase + 1) % ACTIVE_LEDS
            time.sleep(0.09)
    except KeyboardInterrupt:
        all_off()


def solid_color(stop_event=None, color=None, **kwargs):
    """Solid color display.
    
    Args:
        stop_event: threading.Event to signal stop
        color: Color name (string) or RGB tuple (0-255)
        **kwargs: Accept additional parameters from config
    """
    if color is None:
        config = get_state_config("error")
        color = resolve_color(config["color"])
    else:
        color = resolve_color(color)
    
    try:
        while not (stop_event and stop_event.is_set()):
            send_colors([color] * ACTIVE_LEDS)
            time.sleep(0.2)
    except KeyboardInterrupt:
        all_off()

def color_cycle_breathing(stop_event=None, color=None, min_brightness=8, step_delay=0.02, **kwargs):
    """Color breathing animation.
    
    Args:
        stop_event: threading.Event to signal stop
        color: Color name (string) or RGB tuple (0-255)
        min_brightness: Minimum brightness level (0-255 scale)
        step_delay: Delay between animation steps in seconds
        **kwargs: Accept additional parameters from config
    """
    if color is None:
        config = get_state_config("voice_stream")
        color = resolve_color(config["color"])
    else:
        color = resolve_color(color)
    try:
        while not (stop_event and stop_event.is_set()):
            # Breathe in
            for i in range(min_brightness, 51, 2):
                if stop_event and stop_event.is_set():
                    return
                send_colors([(int(color[0]*i/50), int(color[1]*i/50), int(color[2]*i/50))] * ACTIVE_LEDS)
                time.sleep(step_delay)
            # Breathe out
            for i in range(50, min_brightness-1, -2):
                if stop_event and stop_event.is_set():
                    return
                send_colors([(int(color[0]*i/50), int(color[1]*i/50), int(color[2]*i/50))] * ACTIVE_LEDS)
                time.sleep(step_delay)
    except KeyboardInterrupt:
        all_off()


def listening_inward(stop_event=None, color=None, step_delay=None, hold_delay=None, **kwargs):
    """Inward sweep to center animation.
    
    Args:
        stop_event: threading.Event to signal stop
        color: Color name (string) or RGB tuple (0-255)
        step_delay: Delay between steps (overrides config)
        hold_delay: Delay while holding center (overrides config)
        **kwargs: Accept additional parameters from config
    """
    if color is None:
        config = get_state_config("listening")
        color = resolve_color(config["color"])
        params = config.get("animation_params", {})
        step_delay = step_delay or params.get("step_delay", 0.12)
        hold_delay = hold_delay or params.get("hold_delay", 0.1)
    else:
        color = resolve_color(color)
        step_delay = step_delay or 0.12
        hold_delay = hold_delay or 0.1
    
    try:
        steps = [(0, 6), (1, 5), (2, 4)]
        for left, right in steps:
            if stop_event and stop_event.is_set():
                return
            leds = [(0, 0, 0)] * ACTIVE_LEDS
            leds[left] = color
            leds[right] = color
            send_colors(leds)
            time.sleep(step_delay)

        leds = [(0, 0, 0)] * ACTIVE_LEDS
        leds[3] = color
        send_colors(leds)
        while not (stop_event and stop_event.is_set()):
            time.sleep(hold_delay)
    except KeyboardInterrupt:
        all_off()

def play_state_animation(state_name, stop_event=None):
    """Play animation for a named state (e.g., "listening", "processing").
    
    Useful for other scripts to trigger LED patterns by state name.
    
    Args:
        state_name: Name of state from config (e.g., "listening", "processing")
        stop_event: threading.Event to signal stop
    
    Returns:
        function: Animation function that can be used with threading
    """
    config = get_state_config(state_name)
    animation_name = config.get("animation")
    params = config.get("animation_params", {})
    
    # Only resolve color if it's not None and the animation needs it
    color = None
    if config.get("color") is not None and animation_name != "all_off":
        color = resolve_color(config["color"])
    
    # Map animation names to functions
    animation_map = {
        "listening_inward": listening_inward,
        "cylon_bounce": cylon_bounce,
        "pulse_wave": pulse_wave,
        "color_cycle_breathing": color_cycle_breathing,
        "solid_color": solid_color,
        "all_off": all_off_stoppable,
    }
    
    if animation_name not in animation_map:
        raise ValueError(f"Unknown animation: {animation_name}")
    
    anim_func = animation_map[animation_name]
    
    # Call animation with color and params
    if animation_name == "all_off":
        anim_func(stop_event=stop_event)
    else:
        anim_func(stop_event=stop_event, color=color, **params)


def get_event_animation(event_name, stop_event=None):
    """Get animation function for a journal event.
    
    Args:
        event_name: Event name (e.g., "VOICE_ASSISTANT_RUN_START")
        stop_event: threading.Event to signal stop
    
    Returns:
        function: Animation function
    """
    events_map = CONFIG.get("events", {})
    if event_name not in events_map:
        raise ValueError(f"Unknown event: {event_name}")
    
    state_name = events_map[event_name]
    return play_state_animation(state_name, stop_event=stop_event)


if __name__ == "__main__":
    try:
        print("Available states:")
        for state, cfg in STATES_MAP.items():
            anim = cfg.get("animation")
            print(f"  {state}: {anim}")
        print("\nEnter state name to test, or 'q' to quit:")
        while True:
            choice = input("State: ").strip()
            if choice.lower() == "q":
                all_off()
                break
            if choice in STATES_MAP:
                print(f"Playing {choice}... (Ctrl+C to stop)")
                try:
                    play_state_animation(choice)
                except KeyboardInterrupt:
                    all_off()
            else:
                print(f"Unknown state: {choice}")
    except KeyboardInterrupt:
        all_off()
    finally:
        spi.close()

