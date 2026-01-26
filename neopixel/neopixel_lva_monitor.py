#!/usr/bin/env python3
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

def get_lva_service_names():
    user_dir = Path(__file__).parent.parent / "preferences" / "user"
    service_names = []
    for f in user_dir.glob("*_cli.json"):
        if f.stem.endswith("_cli"):
            name = f.stem[:-4]
        else:
            name = f.stem
        service_file = user_dir / f"{name}.service"
        if service_file.exists():
            service_names.append(f"{name}.service")
    return service_names

# Track mute state per service
mute_states = {}

def send_to_socket(cmd):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect("/tmp/neopixel.sock")
        sock.sendall(cmd.encode("utf-8"))
        resp = sock.recv(1024)
        sock.close()
        print(f"[socket] {resp.decode('utf-8')}")
    except Exception as e:
        print(f"[socket] Error: {e}")

def follow_single_journal(svc):
    """Follow a single journal in its own thread."""
    cmd = ["journalctl", "--user", "-u", svc, "-f", "-n", "0"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Initialize mute state for this service
    mute_states[svc] = False
    
    try:
        while True:
            line = p.stdout.readline()
            if not line:
                break
            
            l = line.lower()
            # Filter and translate relevant events to simple commands
            if "wake word detected while muted" in l:
                send_to_socket("muted_wakeword")
            elif "detected wake word" in l or "voice_assistant_stt_start" in l:
                send_to_socket("listening")
            elif "voice_assistant_stt_end" in l:
                send_to_socket("processing")
            elif "playing http" in l:
                send_to_socket("responding")
            elif "tts response finished" in l:
                # Return to mute if still muted, otherwise idle
                if mute_states.get(svc, False):
                    send_to_socket("mute")
                else:
                    send_to_socket("idle")
            elif "assistant mute changed: true" in l:
                print(f"[debug] {svc}: Assistant mute changed: True. Sending 'mute' to neopixel.")
                mute_states[svc] = True
                send_to_socket("mute")
            elif "assistant mute changed: false" in l:
                print(f"[debug] {svc}: Assistant mute changed: False. Sending 'idle' to neopixel.")
                mute_states[svc] = False
                send_to_socket("idle")
    except Exception as e:
        print(f"[error] Thread for {svc} failed: {e}")
    finally:
        p.terminate()
        p.wait()

def follow_journals():
    service_names = get_lva_service_names()
    print("Following journals for:", service_names)
    
    threads = []
    for svc in service_names:
        t = threading.Thread(target=follow_single_journal, args=(svc,), daemon=True)
        t.start()
        threads.append(t)
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping journal followers...")

def main():
    print("LVA monitor started. Ctrl+C to exit.")
    follow_journals()

if __name__ == "__main__":
    main()

def main():
    print("LVA monitor started. Ctrl+C to exit.")
    follow_journals()

if __name__ == "__main__":
    main()
