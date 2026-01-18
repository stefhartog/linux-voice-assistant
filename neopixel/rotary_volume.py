#!/usr/bin/env python3
"""Rotary encoder volume control for default PulseAudio sink."""

import subprocess
import threading
import time
import sys
import logging
import os
from pathlib import Path
from queue import Queue

# Setup logging
log_file = Path("/tmp/rotary_volume.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Get the user's PulseAudio socket - default to stef's UID 1000
# This is needed when running as root via sudo
PULSE_SOCKET = os.environ.get("PULSE_SERVER", "unix:/run/user/1000/pulse/native")
if "unix:" in PULSE_SOCKET:
    PULSE_SOCKET = PULSE_SOCKET.replace("unix:", "")

# Set environment for pactl subprocess calls
PACTL_ENV = os.environ.copy()
PACTL_ENV["PULSE_SERVER"] = PULSE_SOCKET

try:
    import RPi.GPIO as GPIO
except ImportError:
    logger.error("RPi.GPIO not installed. Install with: sudo apt install python3-rpi.gpio")
    sys.exit(1)

# Rotary encoder GPIO pins
CLK = 24  # Rotary encoder pin A (CLK)
DT = 25   # Rotary encoder pin B (DT)
SW = 27   # Switch/button for mute

VOLUME_STEP = 2  # Percentage per rotation step
DEBOUNCE_TIME = 0.2  # Seconds
NEOPIXEL_SOCKET = "/tmp/neopixel.sock"

# Simple step-based control (no LED quantization here)

clk_last_state = None
rotary_lock = threading.Lock()
running = True
volume_queue = Queue()  # Queue for volume changes
software_mute = False  # Track mute state (like the main satellite script does)


def send_neopixel_command(cmd: str) -> None:
    """Send command to neopixel socket."""
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(NEOPIXEL_SOCKET)
        sock.sendall(cmd.encode("utf-8"))
        sock.close()
    except Exception as e:
        # Silently fail - neopixel service might not be running
        pass




def toggle_mute() -> None:
    """Toggle software mute state and write to shared mute file."""
    global software_mute
    software_mute = not software_mute
    
    # Write to the shared mute file so the main satellite script respects it
    shared_mute_path = "/dev/shm/lvas_system_mute"
    mute_content = "on" if software_mute else "off"
    
    try:
        # Use tee to write as the file's owner (stef) to avoid permission issues
        subprocess.run(
            ["sudo", "-u", "stef", "tee", shared_mute_path],
            input=mute_content,
            text=True,
            capture_output=True,
            check=True,
        )
        
        # Read back from file to verify what was actually written
        file_state = subprocess.run(
            ["cat", shared_mute_path],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        
        logger.info(f"Wrote mute state to {shared_mute_path}: {mute_content} (file now reads: {file_state})")
    except Exception as e:
        logger.error(f"Failed to write mute state: {e}")
    
    # Let neopixel_lva_monitor script handle LED feedback (via satellite log messages)
    # This avoids command conflicts




def get_volume() -> int:
    """Get current volume of default sink (0-100)."""
    try:
        result = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True,
            text=True,
            check=True,
            env=PACTL_ENV,
        )
        # Output like: "Volume: front-left: 49043 /  75% / -7.55 dB,   front-right: 49043 /  75% / -7.55 dB"
        # Look for pattern like "/ 75% /"
        import re
        match = re.search(r'/\s+(\d+)%', result.stdout)
        if match:
            vol = int(match.group(1))
            return vol
        logger.warning(f"Could not parse volume from pactl output: {result.stdout}")
        return 0
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting volume (exit {e.returncode}): stdout={e.stdout} stderr={e.stderr}")
        return 0
    except Exception as e:
        logger.error(f"Error getting volume: {e}")
        return 0


def set_volume(volume: int) -> None:
    """Set volume of default sink (0-100)."""
    volume = max(0, min(100, volume))  # Clamp to 0-100
    try:
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"],
            capture_output=True,
            text=True,
            check=True,
            env=PACTL_ENV,
        )
        # Verify it was set
        verify = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True,
            text=True,
            env=PACTL_ENV,
        )
        logger.info(f"Volume set to: {volume}% - Verify: {verify.stdout.strip()[:80]}")

        # Also adjust active stream volumes on the default sink for audible change
        try:
            def_sink_name = subprocess.run(
                ["pactl", "get-default-sink"], capture_output=True, text=True, env=PACTL_ENV
            ).stdout.strip()
            sinks_short = subprocess.run(
                ["pactl", "list", "sinks", "short"], capture_output=True, text=True, env=PACTL_ENV
            ).stdout.strip().splitlines()
            def_sink_index = None
            for line in sinks_short:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == def_sink_name:
                    def_sink_index = parts[0]
                    break
            if def_sink_index is not None:
                inputs_short = subprocess.run(
                    ["pactl", "list", "sink-inputs", "short"], capture_output=True, text=True, env=PACTL_ENV
                ).stdout.strip().splitlines()
                for line in inputs_short:
                    parts = line.split()
                    if len(parts) >= 2:
                        input_id, sink_id = parts[0], parts[1]
                        if sink_id == def_sink_index:
                            subprocess.run(
                                ["pactl", "set-sink-input-volume", input_id, f"{volume}%"],
                                capture_output=True,
                                text=True,
                                env=PACTL_ENV,
                                check=False,
                            )
        except Exception as e:
            pass
        # Update neopixel visualization
        send_neopixel_command(f"volume {volume}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error setting volume (exit {e.returncode}): stdout={e.stdout} stderr={e.stderr}")
    except Exception as e:
        logger.error(f"Error setting volume: {e}")


def volume_worker() -> None:
    """Worker thread to process volume deltas queued by rotary edges."""
    global running
    current_volume = get_volume()
    pending_delta = 0

    while running:
        try:
            # Collect deltas quickly to batch rapid rotations
            delta = volume_queue.get(timeout=0.01)
            if delta is None:
                break
            pending_delta += delta
            while not volume_queue.empty():
                d = volume_queue.get_nowait()
                if d is not None:
                    pending_delta += d

            # Apply accumulated delta to current volume
            if pending_delta != 0:
                current_volume = max(0, min(100, current_volume + pending_delta))
                set_volume(current_volume)
                pending_delta = 0
        except Exception:
            continue


def rotary_listener() -> None:
    """Listen to rotary encoder and adjust volume."""
    global clk_last_state, running

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    clk_last_state = GPIO.input(CLK)
    sw_last_state = GPIO.input(SW)
    last_sw_press_time = 0
    logger.info("Rotary encoder volume control active. Rotate to adjust volume, press button to toggle mute.")

    try:
        while running:
            clk_state = GPIO.input(CLK)
            dt_state = GPIO.input(DT)
            sw_state = GPIO.input(SW)

            # Detect rotation on falling edge of CLK
            if clk_last_state == 1 and clk_state == 0:
                # Determine direction based on DT state
                if dt_state != clk_state:
                    # Clockwise - increase volume by step
                    volume_queue.put(VOLUME_STEP)
                else:
                    # Counter-clockwise - decrease volume by step
                    volume_queue.put(-VOLUME_STEP)

            # Detect button press (falling edge, 200ms debounce)
            current_time = time.time()
            if sw_last_state == 1 and sw_state == 0:
                logger.info(f"DEBUG: Button press detected! sw_last_state={sw_last_state} sw_state={sw_state}")
                if (current_time - last_sw_press_time) > DEBOUNCE_TIME:
                    logger.info(f"DEBUG: Button press passed debounce check, calling toggle_mute()")
                    toggle_mute()
                    last_sw_press_time = current_time
                else:
                    logger.info(f"DEBUG: Button press rejected by debounce (time diff={current_time - last_sw_press_time})")

            clk_last_state = clk_state
            sw_last_state = sw_state

            time.sleep(0.001)  # 1ms polling for faster edge detection

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        GPIO.cleanup()
        running = False


def main() -> None:
    """Main entry point."""
    global running
    
    # Start volume worker thread
    worker_thread = threading.Thread(target=volume_worker, daemon=True)
    worker_thread.start()
    logger.info("Volume worker thread started")
    
    try:
        rotary_listener()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        running = False
        volume_queue.put(None)  # Signal worker to stop
        worker_thread.join(timeout=1)


if __name__ == "__main__":
    main()
