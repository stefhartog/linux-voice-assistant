# LED Feedback Service

This folder contains the LED feedback service used to drive a WS2812-style LED strip via SPI and react to Linux Voice Assistant (LVA) log events.

## What it does
- Runs a standalone service that tails LVA systemd user logs and switches LED patterns based on events.
- Uses SPI (spidev) to drive an 8 LED strip, with a dim indicator LED always on.
- Maps voice assistant events to animations (listening, intent, TTS, idle, mute).

## Files
- led_feedback.py: Main log follower, event parser, and pattern switcher.
- state_patterns.py: SPI init and LED animation functions.
- led_feedback.service: systemd user unit to run led_feedback.py.
- led_reset.py: one-shot helper to turn LEDs off and close SPI.

## Dependencies
- Python package: spidev
- SPI enabled on the device (e.g., /dev/spidev1.0)
- Systemd user services (for journalctl and the service unit)

## Event sources
led_feedback.py follows logs for all LVA instances found in preferences/user/*.service and reacts to:
- LVA_EVENT lines (listening, intent, TTS events)
- "Connected to Home Assistant"
- "Assistant mute changed: True/False"
- "Wakeword triggered while muted."

Mute state is also read from:
- /dev/shm/lvas_system_mute (written by the voice assistant)

## Setup and run
1) Enable SPI on your device (Raspberry Pi/Orange Pi tooling or config).
2) Install spidev in the LVA venv:
   - .venv/bin/pip install spidev
3) Install the systemd user service:
   - systemctl --user enable /home/stef/linux-voice-assistant/led/led_feedback.service
   - systemctl --user start led_feedback.service

To stop or restart:
- systemctl --user restart led_feedback.service
- systemctl --user stop led_feedback.service

## Useful commands
- Live log stream (what the LED service sees):
  journalctl --user-unit orangepi_1.service --user-unit orangepi_2.service -f -n 0 -o cat

- Reset LEDs (all off):
  python3 /home/stef/linux-voice-assistant/led/led_reset.py

## Notes
- LED brightness is controlled by BRIGHTNESS in state_patterns.py.
- The first LED is reserved as a dim indicator and is always set.
- The idle animation color is chosen based on mute state (muted uses dim red, unmuted uses dim blue).
