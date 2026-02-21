#!/usr/bin/env python3
"""
Dual-mode LED feedback service: MQTT-first with journalctl fallback.

If MQTT is configured in led_config.json, subscribes to HA MQTT topics for actual state.
Fallback to journalctl if MQTT is unavailable or unconfigured.

In MQTT mode, also monitors journalctl for special events like "wakeword triggered while muted".
"""
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from state_patterns import (
    play_state_animation,
    all_off,
    CONFIG,
)

logging.basicConfig(level=logging.INFO, format='[LED] %(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)

# Extract MQTT config
MQTT_CONFIG = CONFIG.get("mqtt", {})
MQTT_ENABLED = MQTT_CONFIG.get("enabled", False)
MQTT_BROKER = MQTT_CONFIG.get("broker")
MQTT_PORT = MQTT_CONFIG.get("port", 1883)
MQTT_USERNAME = MQTT_CONFIG.get("username")
MQTT_PASSWORD = MQTT_CONFIG.get("password")
TOPIC_PREFIX = MQTT_CONFIG.get("topic_prefix", "nodes")
STATE_TOPIC_SUFFIX = MQTT_CONFIG.get("state_topic_suffix", "va/state")
MUTE_TOPIC_SUFFIX = MQTT_CONFIG.get("mute_topic_suffix", "va/manager_mute")

# Map HA satellite states to LED animation states
HA_STATE_TO_LED = {
    "idle": "idle",
    "listening": "listening",
    "processing": "processing",
    "responding": "responding",
    "error": "error",
    "unavailable": "error",
}

# Track active animations per area
current_animations = {}  # area -> thread
current_stop_events = {}  # area -> threading.Event
animation_locks = {}
area_mute_state = {}  # area -> bool (True if muted)


def _discover_lva_services():
    """Discover LVA services from preferences/user/ directory."""
    import glob
    pref_user_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preferences", "user")
    services = [
        os.path.basename(f).replace(".service", "") 
        for f in glob.glob(os.path.join(pref_user_dir, "*.service"))
        if not f.endswith("_manager.service")  # Exclude manager service
    ]
    return services


def _monitor_wakeword_events(stop_event: threading.Event):
    """Monitor journalctl for 'wakeword triggered while muted' events.
    
    Runs in a background thread alongside MQTT mode.
    """
    try:
        import glob
        
        pref_user_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preferences", "user")
        lva_services = [
            os.path.basename(f) 
            for f in glob.glob(os.path.join(pref_user_dir, "*.service"))
            if not f.endswith("_manager.service")
        ]
        
        if not lva_services:
            _LOGGER.info("[WakeWord Monitor] No LVA services found")
            return
        
        _LOGGER.info(f"[WakeWord Monitor] Monitoring services: {', '.join(lva_services)}")
        
        # Build journalctl command to monitor all VA services
        journalctl_cmd = ["journalctl"]
        for svc in lva_services:
            journalctl_cmd += ["--user-unit", svc]
        journalctl_cmd += ["-f", "-n", "0", "-o", "cat"]
        
        wakeword_muted_pattern = re.compile(r"Wakeword triggered while muted\.")
        
        try:
            proc = subprocess.Popen(
                journalctl_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        except Exception as e:
            _LOGGER.error(f"[WakeWord Monitor] Failed to start journalctl: {e}")
            return
        
        try:
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                
                if wakeword_muted_pattern.search(line):
                    _LOGGER.info("[WakeWord Monitor] Detected: wakeword triggered while muted")
                    
                    # Try to find which area triggered this by checking all active areas
                    # Use the first known muted area, or just trigger all known areas
                    for area in list(area_mute_state.keys()):
                        if area_mute_state.get(area, False):
                            _LOGGER.info(f"[{area}] Wakeword while muted → triggering muted animation")
                            _start_animation(area, "muted")
                            break
        except KeyboardInterrupt:
            pass
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass
    
    except Exception as e:
        _LOGGER.error(f"[WakeWord Monitor] Unexpected error: {e}")


def _get_or_create_lock(area: str) -> threading.RLock:
    """Get or create a reentrant lock for an area."""
    if area not in animation_locks:
        animation_locks[area] = threading.RLock()
    return animation_locks[area]


def _stop_animation_unlocked(area: str) -> None:
    """Stop the current animation for an area (caller must hold lock)."""
    if area in current_stop_events:
        current_stop_events[area].set()
    if area in current_animations:
        thread = current_animations[area]
        if thread and thread.is_alive():
            thread.join(timeout=0.5)
        current_animations[area] = None
    if area in current_stop_events:
        del current_stop_events[area]


def _start_animation(area: str, state: str) -> None:
    """Start an animation for a given area and state."""
    lock = _get_or_create_lock(area)
    with lock:
        # Stop any running animation first
        _stop_animation_unlocked(area)
        
        try:
            _LOGGER.info(f"[{area}] Starting animation for state: {state}")
            stop_event = threading.Event()
            current_stop_events[area] = stop_event
            thread = threading.Thread(
                target=play_state_animation,
                args=(state,),
                kwargs={"stop_event": stop_event},
                daemon=True,
                name=f"led-{area}"
            )
            thread.start()
            current_animations[area] = thread
        except Exception as e:
            _LOGGER.error(f"[{area}] Failed to start animation: {e}")


def mqtt_mode():
    """Run LED service in MQTT mode, subscribing to HA topics."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        _LOGGER.error("paho-mqtt not installed. Install with: pip install paho-mqtt")
        _LOGGER.info("Falling back to journalctl mode...")
        return journalctl_mode()
    
    # Parse broker address
    if not MQTT_BROKER:
        _LOGGER.error("MQTT broker not configured. Falling back to journalctl...")
        return journalctl_mode()
    
    _LOGGER.info(f"Starting in MQTT mode (broker: {MQTT_BROKER}:{MQTT_PORT})")
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    
    def on_connect(client, userdata, connect_flags, reason_code, properties):
        if reason_code == 0:
            _LOGGER.info(f"Connected to MQTT broker {MQTT_BROKER}")
            # Subscribe to all VA state topics
            state_topic = f"{TOPIC_PREFIX}/+/{STATE_TOPIC_SUFFIX}"
            mute_topic = f"{TOPIC_PREFIX}/+/{MUTE_TOPIC_SUFFIX}"
            client.subscribe(state_topic)
            client.subscribe(mute_topic)
            _LOGGER.info(f"Subscribed to: {state_topic}")
            _LOGGER.info(f"Subscribed to: {mute_topic}")
        else:
            _LOGGER.error(f"MQTT connection failed with code {reason_code}")
    
    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        _LOGGER.warning(f"Disconnected from MQTT (code {reason_code}). Attempting reconnect...")
    
    def on_message(client, userdata, msg):
        """Handle MQTT messages."""
        topic = msg.topic
        payload = msg.payload.decode('utf-8', errors='ignore').strip().lower()
        
        # Extract area from topic: nodes/{area}/va/state
        parts = topic.split('/')
        if len(parts) < 2:
            return
        
        area = parts[1]
        
        # Handle state topic
        if topic.endswith(f"/{STATE_TOPIC_SUFFIX}"):
            ha_state = payload
            led_state = HA_STATE_TO_LED.get(ha_state, "off")
            
            # If idle state received and area is muted, use muted animation instead
            if led_state == "idle" and area_mute_state.get(area, False):
                led_state = "muted"
            
            _LOGGER.info(f"[{area}] State changed: {ha_state} → {led_state}")
            _start_animation(area, led_state)
        
        # Handle mute topic
        elif topic.endswith(f"/{MUTE_TOPIC_SUFFIX}"):
            is_muted = payload in ("on", "true", "1")
            area_mute_state[area] = is_muted
            _LOGGER.info(f"[{area}] Manager mute: {is_muted}")
            
            # Re-apply animation based on mute state
            # If muted, show muted animation; if not, show idle
            animation_state = "muted" if is_muted else "idle"
            _start_animation(area, animation_state)
    
    # Set credentials if provided
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    
    # Start wakeword event monitor in background
    monitor_stop_event = threading.Event()
    monitor_thread = threading.Thread(
        target=_monitor_wakeword_events,
        args=(monitor_stop_event,),
        daemon=True,
        name="led-wakeword-monitor"
    )
    monitor_thread.start()
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except Exception as e:
        _LOGGER.error(f"MQTT connection failed: {e}")
        monitor_stop_event.set()
        _LOGGER.info("Falling back to journalctl mode...")
        return journalctl_mode()
    finally:
        monitor_stop_event.set()


def journalctl_mode():
    """Fall back to journalctl mode (original implementation)."""
    _LOGGER.info("Starting in journalctl mode (fallback)")
    
    import glob
    import re
    
    PREF_USER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preferences", "user")
    LVA_SERVICES = [
        os.path.basename(f) for f in glob.glob(os.path.join(PREF_USER_DIR, "*.service"))
    ]
    
    if not LVA_SERVICES:
        _LOGGER.error("No LVA instance services found. Exiting.")
        return
    
    _LOGGER.info(f"Monitoring services: {', '.join(LVA_SERVICES)}")
    
    # Load event-to-state mapping from config
    EVENTS_MAP = CONFIG.get("events", {})
    
    LVA_EVENT_RE = re.compile(r"LVA_EVENT: (\w+)")
    MUTE_RE = re.compile(r"Assistant mute changed: (True|False)")
    WAKEWORD_MUTED_RE = re.compile(r"Wakeword triggered while muted\.")
    
    # Track current animation thread
    current_thread = None
    stop_event = None
    
    def _stop_current_animation():
        """Stop the currently running animation."""
        nonlocal current_thread, stop_event
        if stop_event:
            stop_event.set()
        if current_thread and current_thread.is_alive():
            current_thread.join(timeout=1.0)
        current_thread = None
        stop_event = None
    
    def _start_animation_thread(state: str):
        """Start an animation in a background thread."""
        nonlocal current_thread, stop_event
        _stop_current_animation()
        try:
            stop_event = threading.Event()
            current_thread = threading.Thread(
                target=play_state_animation,
                args=(state,),
                kwargs={"stop_event": stop_event},
                daemon=True
            )
            current_thread.start()
        except Exception as e:
            _LOGGER.error(f"Failed to start animation thread: {e}")
    
    # Startup animation
    try:
        all_off()
    except Exception as e:
        _LOGGER.warning(f"Startup animation failed: {e}")
    
    # Build journalctl command with multiple --user-unit args
    journalctl_cmd = ["journalctl"]
    for svc in LVA_SERVICES:
        journalctl_cmd += ["--user-unit", svc]
    journalctl_cmd += ["-f", "-n", "0", "-o", "cat"]
    
    try:
        proc = subprocess.Popen(
            journalctl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    except Exception as e:
        _LOGGER.error(f"Failed to start journalctl: {e}")
        return
    
    try:
        for line in proc.stdout:
            # Handle mute state changes
            mute_match = MUTE_RE.search(line)
            if mute_match:
                is_muted = mute_match.group(1) == "True"
                state = "muted" if is_muted else "idle"
                _LOGGER.info(f"Mute state changed: {state}")
                _start_animation_thread(state)
                continue
            
            # Handle wakeword triggered while muted
            if WAKEWORD_MUTED_RE.search(line):
                _LOGGER.info("Wakeword triggered while muted")
                _start_animation_thread("muted")
                continue
            
            # Handle LVA_EVENT
            match = LVA_EVENT_RE.search(line)
            if match:
                event = match.group(1)
                if event in EVENTS_MAP:
                    state = EVENTS_MAP[event]
                    _LOGGER.info(f"Event: {event} → {state}")
                    _start_animation_thread(state)
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
        _stop_current_animation()
        all_off()
    finally:
        _stop_current_animation()
        proc.terminate()


def main():
    """Main entry point: detect mode and run."""
    _LOGGER.info("=" * 50)
    _LOGGER.info("LED Feedback Service (Dual-Mode)")
    _LOGGER.info("=" * 50)
    
    # Check if MQTT should be used
    if MQTT_ENABLED and MQTT_BROKER:
        _LOGGER.info("MQTT configuration detected, attempting MQTT mode...")
        mqtt_mode()
    else:
        _LOGGER.info("MQTT not configured, using journalctl fallback...")
        journalctl_mode()


if __name__ == "__main__":
    main()
