#!/usr/bin/env python3
"""
Single-service LED pattern switcher that listens to LVA journal events and switches patterns directly.

Loads all patterns and event mappings from led_config.json via state_patterns.
"""
import subprocess
import threading
import re
import time
import json
import glob
import os
from pathlib import Path

from state_patterns import (
    all_off_stoppable,
    all_off,
    play_state_animation,
    get_state_config,
    CONFIG
)

# List of systemd user unit names to monitor
PREF_USER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preferences", "user")
MUTE_STATE_PATH = "/dev/shm/lvas_system_mute"
LVA_SERVICES = [
    os.path.basename(f) for f in glob.glob(os.path.join(PREF_USER_DIR, "*.service"))
]

# Load event-to-state mapping from config
EVENTS_MAP = CONFIG.get("events", {})

LVA_EVENT_RE = re.compile(r"LVA_EVENT: (\w+)")
MUTE_RE = re.compile(r"Assistant mute changed: (True|False)")
WAKEWORD_MUTED_RE = re.compile(r"Wakeword triggered while muted\.")
HA_CONNECTED_RE = re.compile(r"Connected to Home Assistant")


def _is_muted() -> bool:
    """Check if system is muted via shared mute state file."""
    try:
        with open(MUTE_STATE_PATH, "r", encoding="utf-8") as state_file:
            return state_file.read().strip().lower().startswith("on")
    except Exception:
        return False


def _start_idle_pattern(current_thread: "PatternThread") -> "PatternThread":
    """Start idle pattern (listening_inward)."""
    if current_thread and current_thread.is_alive():
        current_thread.stop()
        current_thread.join()
    
    # Use muted state or listening state based on mute status
    state_name = "muted" if _is_muted() else "idle"
    current_thread = PatternThread(play_state_animation, state_name)
    current_thread.start()
    return current_thread


class PatternThread(threading.Thread):
    """Thread wrapper for running LED pattern animations."""
    
    def __init__(self, pattern_func, *args, **kwargs):
        super().__init__()
        self.pattern_func = pattern_func
        self.args = args
        self.kwargs = kwargs
        self._stop_event = threading.Event()
        self.daemon = True

    def run(self):
        self.pattern_func(*self.args, stop_event=self._stop_event, **self.kwargs)

    def stop(self):
        self._stop_event.set()


def short_breath(state_name="startup", duration=2.0):
    """Play a timed animation from config state."""
    stop_event = threading.Event()
    t = threading.Thread(
        target=play_state_animation,
        args=(state_name,),
        kwargs={"stop_event": stop_event}
    )
    t.start()
    time.sleep(duration)
    stop_event.set()
    t.join()


def main():
    if not LVA_SERVICES:
        print("No LVA instance services found in preferences/user. Exiting.")
        return
    
    print(f"Listening for LVA events from {', '.join(LVA_SERVICES)} and switching LED patterns...")
    print(f"Loaded {len(EVENTS_MAP)} event mappings from config")
    
    current_thread = None
    
    # Startup: announce readiness with startup animation
    try:
        short_breath("startup", duration=2.0)
    except Exception as e:
        print(f"[LED] Warning: Startup animation failed: {e}")
    
    all_off()

    # Build journalctl command with multiple --user-unit args
    journalctl_cmd = ["journalctl"]
    for svc in LVA_SERVICES:
        journalctl_cmd += ["--user-unit", svc]
    journalctl_cmd += ["-f", "-n", "0", "-o", "cat"]
    
    proc = subprocess.Popen(
        journalctl_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Track which services have been seen
    seen_services = set()
    
    try:
        for line in proc.stdout:
            # Try to extract the service name from the journal line
            svc_name = None
            for svc in LVA_SERVICES:
                if svc in line:
                    svc_name = svc
                    break
            
            # Handle mute state changes
            mute_match = MUTE_RE.search(line)
            if mute_match:
                current_thread = _start_idle_pattern(current_thread)
                print(f"[LED] Mute state changed to: {mute_match.group(1)}")
                continue

            # Handle wakeword triggered while muted
            if WAKEWORD_MUTED_RE.search(line):
                current_thread = _start_idle_pattern(current_thread)
                print("[LED] Wakeword triggered while muted")
                continue

            # Handle HA connection
            if HA_CONNECTED_RE.search(line):
                current_thread = _start_idle_pattern(current_thread)
                print("[LED] Connected to Home Assistant")
                continue

            # Track service startup
            if svc_name and svc_name not in seen_services:
                print(f"[LED] LVA service ready: {svc_name}")
                seen_services.add(svc_name)
            
            # Handle LVA_EVENT
            match = LVA_EVENT_RE.search(line)
            if match:
                event = match.group(1)
                print(f"[LED] Detected event: {event}")
                
                if event not in EVENTS_MAP:
                    print(f"[LED] Warning: No mapping for event {event}")
                    continue
                
                state_name = EVENTS_MAP[event]
                print(f"[LED] Starting animation for state: {state_name}")
                
                try:
                    if current_thread and current_thread.is_alive():
                        current_thread.stop()
                        current_thread.join()
                    
                    # Special handling for completion events
                    if event == "TTS_RESPONSE_FINISHED":
                        current_thread = _start_idle_pattern(current_thread)
                    else:
                        current_thread = PatternThread(play_state_animation, state_name)
                        current_thread.start()
                except Exception as e:
                    print(f"[LED] Error starting animation: {e}")
                    
    except KeyboardInterrupt:
        print("\n[LED] Exiting LED journal pattern service.")
    finally:
        if current_thread and current_thread.is_alive():
            current_thread.stop()
            current_thread.join()
        all_off()
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()

