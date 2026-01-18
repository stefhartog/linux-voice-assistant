import os
import glob
import socket
import subprocess
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

def follow_journals():
    service_names = get_lva_service_names()
    print("Following journals for:", service_names)
    procs = []
    for svc in service_names:
        cmd = ["journalctl", "--user", "-u", svc, "-f", "-n", "0"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append((svc, p))
    try:
        while True:
            for svc, p in procs:
                line = p.stdout.readline()
                if line:
                    l = line.lower()
                    # Filter and translate relevant events to simple commands
                    if "detected wake word" in l or "voice_assistant_stt_start" in l:
                        send_to_socket("listening")
                    elif "voice_assistant_intent_start" in l:
                        send_to_socket("processing")
                    elif "voice_assistant_tts_start" in l:
                        send_to_socket("responding")
                    elif "tts response finished" in l:
                        send_to_socket("idle")
                    elif "assistant mute changed: true" in l:
                        print("[debug] Assistant mute changed: True. Sending 'mute' to neopixel.")
                        send_to_socket("mute")
                    elif "assistant mute changed: false" in l:
                        print("[debug] Assistant mute changed: False. Sending 'idle' to neopixel.")
                        send_to_socket("idle")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping journal followers...")
        for _, p in procs:
            p.terminate()
        for _, p in procs:
            p.wait()
        print("All journal followers stopped.")

def main():
    print("LVA monitor started. Ctrl+C to exit.")
    follow_journals()

if __name__ == "__main__":
    main()
