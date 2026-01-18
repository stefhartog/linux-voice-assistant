import socket
import select
import os
SOCKET_PATH = "/tmp/neopixel.sock"
import board
import neopixel
import time
import threading

NUM_PIXELS = 8
PIXEL_PIN = board.D18
BRIGHTNESS = 0.1

COLOR_PRESETS = [
    (255, 0, 0),    # Red
    (0, 255, 0),    # Green
    (0, 0, 255),    # Blue
    (255, 255, 0),  # Yellow
    (255, 0, 255),  # Magenta
]

pixels = neopixel.NeoPixel(PIXEL_PIN, NUM_PIXELS, brightness=BRIGHTNESS, auto_write=True)

pattern_index = 0
color_index = 0
brightness = BRIGHTNESS
running = True

def breathing(color):
    print(f"[debug] Entered breathing with color={color}")
    for b in list(range(0, 256, 4)) + list(range(255, -1, -4)):
        if pattern_index != 0 or not running or color != COLOR_PRESETS[color_index]:
            return
        factor = b / 255.0
        c = tuple(int(x * factor) for x in color)
        pixels.brightness = brightness
        pixels.fill(c)
        time.sleep(0.01)

def pulsing(color):
    print(f"[debug] Entered pulsing with color={color}")
    for _ in range(3):
        if pattern_index != 1 or not running or color != COLOR_PRESETS[color_index]:
            return
        for b in range(0, 256, 8):
            if pattern_index != 1 or not running or color != COLOR_PRESETS[color_index]:
                return
            c = tuple(int(x * (b / 255.0)) for x in color)
            pixels.brightness = brightness
            pixels.fill(c)
            time.sleep(0.005)
        for b in range(255, -1, -8):
            if pattern_index != 1 or not running or color != COLOR_PRESETS[color_index]:
                return
            c = tuple(int(x * (b / 255.0)) for x in color)
            pixels.brightness = brightness
            pixels.fill(c)
            time.sleep(0.005)

def cylon(color):
    print(f"[debug] Entered cylon with color={color}")
    fade_template = [0.2, 0.5, 1.0, 1.0, 0.5, 0.2]
    fade_len = len(fade_template)
    center_range = range(2, NUM_PIXELS-2+1)
    for _ in range(3):
        if pattern_index != 2 or not running or color != COLOR_PRESETS[color_index]:
            return
        for center in center_range[:-1]:
            if pattern_index != 2 or not running or color != COLOR_PRESETS[color_index]:
                return
            pixels.brightness = brightness
            for i in range(NUM_PIXELS):
                fade_idx = i - center + (fade_len // 2)
                if 0 <= fade_idx < fade_len:
                    fade = fade_template[fade_idx]
                else:
                    fade = fade_template[0]
                c = tuple(int(x * fade) for x in color)
                pixels[i] = c
            time.sleep(0.105)
        for center in reversed(center_range[1:]):
            if pattern_index != 2 or not running or color != COLOR_PRESETS[color_index]:
                return
            pixels.brightness = brightness
            for i in range(NUM_PIXELS):
                fade_idx = i - center + (fade_len // 2)
                if 0 <= fade_idx < fade_len:
                    fade = fade_template[fade_idx]
                else:
                    fade = fade_template[0]
                c = tuple(int(x * fade) for x in color)
                pixels[i] = c
            time.sleep(0.105)

def static(color):
    print(f"[debug] Entered static with color={color}")
    while running:
        if pattern_index != 3 or not running or color != COLOR_PRESETS[color_index]:
            return
        pixels.brightness = brightness
        pixels.fill(color)
        time.sleep(0.05)

def ripple(color):
    print(f"[debug] Entered ripple with color={color}")
    for _ in range(3):
        if pattern_index != 4 or not running or color != COLOR_PRESETS[color_index]:
            return
        for i in range(NUM_PIXELS):
            if pattern_index != 4 or not running or color != COLOR_PRESETS[color_index]:
                return
            pixels.brightness = brightness
            pixels.fill((0, 0, 0))
            for j in range(i + 1):
                fade = 1 - (j / NUM_PIXELS)
                c = tuple(int(x * fade) for x in color)
                pixels[i - j] = c
            time.sleep(0.07)

def pattern_runner():
    global pattern_index, color_index, running
    global brightness
    last_pat = last_col = None
    while running:
        color = COLOR_PRESETS[color_index]
        pixels.brightness = brightness
        pat_idx = pattern_index
        if pat_idx != last_pat or color_index != last_col:
            print(f"[debug] pattern_runner: pattern_index={pat_idx}, color_index={color_index}, color={color}")
            last_pat, last_col = pat_idx, color_index
        if pat_idx == 0:
            print("[debug] Calling breathing")
            breathing(color)
        elif pat_idx == 1:
            print("[debug] Calling pulsing")
            pulsing(color)
        elif pat_idx == 2:
            print("[debug] Calling cylon")
            cylon(color)
        elif pat_idx == 3:
            print("[debug] Calling static")
            static(color)
        elif pat_idx == 4:
            print("[debug] Calling ripple")
            ripple(color)
        else:
            print("[debug] pattern_index is off/unknown, turning off LEDs")
            pixels.fill((0, 0, 0))
            time.sleep(0.1)

def main():
    # Set default to 'on' preset: blue breathing
    global pattern_index, color_index, running
    pattern_index = 0  # breathing
    color_index = 2    # blue

    def socket_listener():
        global pattern_index, color_index
        import traceback
        try:
            if os.path.exists(SOCKET_PATH):
                os.remove(SOCKET_PATH)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(SOCKET_PATH)
            os.chmod(SOCKET_PATH, 0o666)
            server.listen(1)
            print(f"[patterns] Listening on {SOCKET_PATH}")
            while running:
                rlist, _, _ = select.select([server], [], [], 0.5)
                if server in rlist:
                    conn, _ = server.accept()
                    with conn:
                        data = conn.recv(1024)
                        if not data:
                            continue
                        cmd = data.decode("utf-8").strip().lower()
                        print(f"[patterns] Received command: {cmd}")
                        # Handle commands
                        if cmd == "on":
                            pattern_index = 0  # breathing
                            color_index = 2    # blue (COLOR_PRESETS[2])
                            print(f"[debug] socket_listener set pattern_index=0 (on), color_index=2 (blue)")
                        elif cmd == "mute":
                            pattern_index = 3  # static
                            color_index = 0    # red (COLOR_PRESETS[0])
                            print(f"[debug] socket_listener set pattern_index=3 (mute), color_index=0 (red)")
                        elif cmd == "error":
                            pattern_index = 1  # pulsing
                            color_index = 0    # red (COLOR_PRESETS[0])
                            print(f"[debug] socket_listener set pattern_index=1 (error), color_index=0 (red)")
                        elif cmd == "off":
                            pattern_index = -1
                            pixels.fill((0,0,0))
                            pixels.show()
                            print(f"[debug] socket_listener set pattern_index=-1 (off)")
                        elif cmd == "listening":
                            pattern_index = 0  # breathing
                            color_index = 3    # yellow (COLOR_PRESETS[3])
                            print(f"[debug] socket_listener set pattern_index=0 (listening), color_index=3 (yellow)")
                        elif cmd == "processing":
                            pattern_index = 2  # cylon
                            color_index = 4    # magenta (purple, COLOR_PRESETS[4])
                            print(f"[debug] socket_listener set pattern_index=2 (processing), color_index=4 (magenta)")
                        elif cmd == "responding":
                            pattern_index = 0  # breathing
                            color_index = 1    # green (COLOR_PRESETS[1])
                            print(f"[debug] socket_listener set pattern_index=0 (responding), color_index=1 (green)")
                        elif cmd == "idle":
                            pattern_index = -1
                            pixels.fill((0,0,0))
                            pixels.show()
                            print(f"[debug] socket_listener set pattern_index=-1 (idle)")
                        elif cmd.startswith("preset"):
                            try:
                                idx = int(cmd.split()[1])
                                color_index = idx
                            except Exception:
                                pass
            server.close()
            if os.path.exists(SOCKET_PATH):
                os.remove(SOCKET_PATH)
        except Exception as e:
            print(f"[patterns] Exception in socket_listener: {e}")
            traceback.print_exc()

    t_sock = threading.Thread(target=socket_listener, daemon=True)
    t_sock.start()
    print("NeoPixel pattern service started. Ctrl+C to exit.")
    t_pattern = threading.Thread(target=pattern_runner)
    t_pattern.start()
    t_pattern.join()
    running = False
    pixels.fill((0, 0, 0))
    print("All LEDs off.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        running = False
        try:
            pixels.fill((0, 0, 0))
            pixels.show()
        except Exception:
            pass
        print("All LEDs off.")