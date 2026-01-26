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
BRIGHTNESS = 0.05
MIN_BREATHE_FACTOR = 0.1  # Minimum brightness factor during breathing to avoid fully off

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

# Volume bar state
volume_display_active = False
volume_display_end_time = 0
last_volume = 0
saved_pattern_index = 0
saved_color_index = 0
volume_bar_drawn = False

def breathing(color):
    print(f"[debug] Entered breathing with color={color}")
    for b in list(range(0, 256, 4)) + list(range(255, -1, -4)):
        if pattern_index != 0 or not running or color != COLOR_PRESETS[color_index]:
            return
        factor = b / 255.0
        if factor < MIN_BREATHE_FACTOR:
            factor = MIN_BREATHE_FACTOR
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

def volume_bar(volume_percent):
    """Display volume as a bar (filled LEDs from 0-100%).
    
    Args:
        volume_percent: Volume level 0-100
    """
    vol = max(0, min(100, volume_percent))
    num_lit = int((vol / 100.0) * NUM_PIXELS)
    
    # Solid cyan color
    color = (0, 255, 255)
    
    # Fill LEDs from left to right based on volume, respecting global brightness
    global brightness
    pixels.brightness = brightness
    pixels.fill((0, 0, 0))  # Clear first
    for i in range(num_lit):
        pixels[i] = color
    pixels.show()

def mute_collapse():
    """Outer pixels travel inward and dim, ending with just center two LEDs dimly lit."""
    print(f"[debug] Entered mute_collapse")
    color = (255, 0, 0)  # Red
    very_dim_factor = 0.1
    
    # Animation: pairs travel inward and dim
    # Pairs: (0,7), (1,6), (2,5) -> finally just (3,4)
    pairs = [(0, 7), (1, 6), (2, 5)]
    
    for pair_idx, (left, right) in enumerate(pairs):
        if pattern_index != 5 or not running:
            return
        
        # All pixels very dim
        very_dim_color = tuple(int(x * very_dim_factor) for x in color)
        
        pixels.brightness = brightness
        pixels[left] = very_dim_color
        pixels[right] = very_dim_color
        pixels.show()
        time.sleep(0.15)
    
    # Final state: just center two pixels very dim
    very_dim_color = tuple(int(x * very_dim_factor) for x in color)
    pixels.fill((0, 0, 0))
    pixels.brightness = brightness
    pixels[3] = very_dim_color
    pixels[4] = very_dim_color
    pixels.show()

def mute_idle():
    """Hold the mute state with just center two pixels dimly lit."""
    print(f"[debug] Entered mute_idle")
    color = (255, 0, 0)  # Red
    very_dim_factor = 0.1
    very_dim_color = tuple(int(x * very_dim_factor) for x in color)
    
    while running and pattern_index == 6:
        pixels.brightness = brightness
        pixels.fill((0, 0, 0))
        pixels[3] = very_dim_color
        pixels[4] = very_dim_color
        pixels.show()
        time.sleep(0.05)


def pattern_runner():
    global pattern_index, color_index, running
    global brightness
    global volume_display_active, volume_display_end_time, last_volume
    global saved_pattern_index, saved_color_index, volume_bar_drawn
    last_pat = last_col = None
    while running:
        # Check if volume display timer expired
        if volume_display_active and time.time() >= volume_display_end_time:
            volume_display_active = False
            volume_bar_drawn = False
            pattern_index = saved_pattern_index
            color_index = saved_color_index
            print(f"[debug] Volume display timeout - returning to pattern {pattern_index}")
        
        # If volume display is active, show it once then just wait
        if volume_display_active:
            if not volume_bar_drawn:
                volume_bar(last_volume)
                volume_bar_drawn = True
            time.sleep(0.05)
            continue
        
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
        elif pat_idx == 5:
            print("[debug] Calling mute_collapse")
            mute_collapse()
            # After animation, switch to idle state
            pattern_index = 6
        elif pat_idx == 6:
            print("[debug] Calling mute_idle")
            mute_idle()
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
        global volume_display_active, volume_display_end_time, last_volume
        global saved_pattern_index, saved_color_index, volume_bar_drawn
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
                            pattern_index = 5  # mute_collapse animation
                            print(f"[debug] socket_listener set pattern_index=5 (mute collapse)")
                        elif cmd == "muted_wakeword":
                            # Replay the collapse animation
                            pattern_index = 5  # mute_collapse animation
                            print(f"[debug] socket_listener set pattern_index=5 (muted wakeword detected)")
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
                        elif cmd.startswith("volume"):
                            # Format: "volume 50" for 50%
                            try:
                                vol = int(cmd.split()[1])
                                # Save current pattern if not already in volume display mode
                                if not volume_display_active:
                                    saved_pattern_index = pattern_index
                                    saved_color_index = color_index
                                last_volume = vol
                                volume_display_active = True
                                volume_bar_drawn = False  # Force redraw
                                volume_display_end_time = time.time() + 1.0  # Show for 1 second
                                print(f"[debug] socket_listener set volume bar to {vol}% (will timeout at {volume_display_end_time})")
                            except Exception as e:
                                print(f"[debug] Error parsing volume command: {e}")
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