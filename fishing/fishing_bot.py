"""
ESO Fishing Bot
Automates fishing: cast -> detect hook -> reel -> loot -> repeat
Requires Votan's Fisherman addon (shows white hook icon on bite)

Controls:
  F5  - Start/Pause bot
  F6  - Stop bot completely
"""

import time
import random
import sys
import ctypes
import threading

import cv2
import numpy as np
import pyautogui
import pydirectinput
from PIL import ImageGrab

# ─── Settings ───────────────────────────────────────────────────────
SCAN_REGION_HOOK = None       # Will be set on first run (center of screen)
SCAN_REGION_LOOT = None       # Will be set on first run (bottom-right)

HOOK_WHITE_THRESHOLD = 220    # Pixel brightness to count as "white" (hook icon)
HOOK_WHITE_RATIO = 0.08       # Min ratio of white pixels in center to detect hook
LOOT_DARK_THRESHOLD = 40      # Pixel brightness to count as "dark" (loot panel)
LOOT_DARK_RATIO = 0.50        # Min ratio of dark pixels in bottom-right for loot

CAST_KEY = 'e'
LOOT_KEY = 'r'

SCAN_INTERVAL = 0.05          # 50ms between screen checks (fast enough for 0.5s hook)

# Human-like delays (random range in seconds)
DELAY_AFTER_CAST = (1.0, 2.0)       # Wait after casting before scanning
DELAY_REEL_REACTION = (0.05, 0.2)   # Reaction time to press E on hook
DELAY_AFTER_REEL = (1.5, 3.0)       # Wait for loot window to appear
DELAY_AFTER_LOOT = (0.5, 1.5)       # Wait after looting before next cast
DELAY_RECAST = (0.3, 0.8)           # Delay before re-casting

MAX_WAIT_FOR_HOOK = 45.0     # Max seconds to wait for hook (bite timeout)
MAX_WAIT_FOR_LOOT = 10.0     # Max seconds to wait for loot window

# ─── State ──────────────────────────────────────────────────────────
running = False
paused = False
fish_count = 0
cast_count = 0


def get_screen_regions():
    """Calculate scan regions based on screen resolution."""
    global SCAN_REGION_HOOK, SCAN_REGION_LOOT

    screen_w, screen_h = pyautogui.size()

    # Hook icon appears in center of screen
    center_x, center_y = screen_w // 2, screen_h // 2
    hook_size = min(screen_w, screen_h) // 4
    SCAN_REGION_HOOK = (
        center_x - hook_size // 2,
        center_y - hook_size // 2,
        hook_size,
        hook_size
    )

    # Loot window appears in right-center area of screen
    loot_x = int(screen_w * 0.55)
    loot_y = int(screen_h * 0.30)
    loot_w = int(screen_w * 0.30)
    loot_h = int(screen_h * 0.40)
    SCAN_REGION_LOOT = (
        loot_x,
        loot_y,
        loot_w,
        loot_h
    )

    print(f"[INFO] Screen: {screen_w}x{screen_h}")
    print(f"[INFO] Hook scan region: {SCAN_REGION_HOOK}")
    print(f"[INFO] Loot scan region: {SCAN_REGION_LOOT}")


def capture_region(region):
    """Capture a screen region and return as numpy array."""
    x, y, w, h = region
    bbox = (x, y, x + w, y + h)
    img = ImageGrab.grab(bbox)
    return np.array(img)


def detect_hook():
    """Detect white hook icon in center of screen."""
    frame = capture_region(SCAN_REGION_HOOK)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    white_pixels = np.sum(gray > HOOK_WHITE_THRESHOLD)
    total_pixels = gray.size
    ratio = white_pixels / total_pixels

    return ratio > HOOK_WHITE_RATIO


def detect_loot_window():
    """Detect dark loot panel in bottom-right of screen."""
    frame = capture_region(SCAN_REGION_LOOT)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    dark_pixels = np.sum(gray < LOOT_DARK_THRESHOLD)
    total_pixels = gray.size
    ratio = dark_pixels / total_pixels

    return ratio > LOOT_DARK_RATIO


def human_delay(delay_range):
    """Sleep for a random duration within range (human-like)."""
    delay = random.uniform(*delay_range)
    time.sleep(delay)


def press_key(key):
    """Press a key via DirectInput (games ignore regular virtual keys)."""
    hold_time = random.uniform(0.04, 0.12)
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


def wait_for_hook():
    """Wait for white hook icon to appear. Returns True if detected."""
    start = time.time()
    while running and not paused:
        if time.time() - start > MAX_WAIT_FOR_HOOK:
            print("[WARN] Hook timeout - hole might be empty")
            return False

        if detect_hook():
            return True

        time.sleep(SCAN_INTERVAL)

    return False


def wait_for_loot():
    """Wait for loot window to appear. Returns True if detected."""
    start = time.time()
    while running and not paused:
        if time.time() - start > MAX_WAIT_FOR_LOOT:
            print("[WARN] Loot window timeout")
            return False

        if detect_loot_window():
            return True

        time.sleep(SCAN_INTERVAL)

    return False


def fishing_loop():
    """Main fishing cycle."""
    global running, fish_count, cast_count

    print("\n[BOT] Starting fishing loop...")
    print("[BOT] Make sure you are facing a fishing hole!\n")

    while running:
        if paused:
            time.sleep(0.5)
            continue

        # Step 1: Cast line (press E)
        cast_count += 1
        print(f"[{cast_count}] Casting...")
        press_key(CAST_KEY)
        human_delay(DELAY_AFTER_CAST)

        # Step 2: Wait for hook icon
        print(f"[{cast_count}] Waiting for bite...")
        if not wait_for_hook():
            if not running:
                break
            print(f"[{cast_count}] No bite, retrying...")
            human_delay(DELAY_RECAST)
            continue

        # Step 3: Reel in (press E)
        human_delay(DELAY_REEL_REACTION)
        print(f"[{cast_count}] HOOK! Reeling in...")
        press_key(CAST_KEY)

        # Step 4: Wait for loot window to appear
        print(f"[{cast_count}] Waiting for loot window...")
        human_delay(DELAY_AFTER_REEL)

        # Step 5: Loot (press R)
        fish_count += 1
        print(f"[{cast_count}] Fish #{fish_count}! Pressing R to loot...")
        press_key(LOOT_KEY)
        time.sleep(0.3)
        # Press R again in case first one didn't register
        press_key(LOOT_KEY)
        human_delay(DELAY_AFTER_LOOT)

    print(f"\n[BOT] Stopped. Casts: {cast_count}, Fish caught: {fish_count}")


def hotkey_listener():
    """Listen for F5 (toggle pause) and F6 (stop) hotkeys."""
    global running, paused

    # Use Windows API for global hotkeys
    VK_F5 = 0x74
    VK_F6 = 0x75

    while running:
        if ctypes.windll.user32.GetAsyncKeyState(VK_F5) & 0x8000:
            paused = not paused
            state = "PAUSED" if paused else "RUNNING"
            print(f"\n[BOT] {state}")
            time.sleep(0.3)  # debounce

        if ctypes.windll.user32.GetAsyncKeyState(VK_F6) & 0x8000:
            running = False
            print("\n[BOT] Stopping...")
            break

        time.sleep(0.05)


def main():
    global running

    print("=" * 50)
    print("  ESO Fishing Bot")
    print("=" * 50)
    print()
    print("  F5 - Start / Pause")
    print("  F6 - Stop")
    print()
    print("  Stand in front of a fishing hole and press F5")
    print("=" * 50)

    get_screen_regions()

    # Wait for F5 to start
    VK_F5 = 0x74
    print("\n[BOT] Waiting for F5 to start...")
    while True:
        if ctypes.windll.user32.GetAsyncKeyState(VK_F5) & 0x8000:
            break
        time.sleep(0.05)

    running = True
    time.sleep(0.3)  # debounce

    # Start hotkey listener in background
    hotkey_thread = threading.Thread(target=hotkey_listener, daemon=True)
    hotkey_thread.start()

    # Run fishing loop
    try:
        fishing_loop()
    except KeyboardInterrupt:
        running = False
        print("\n[BOT] Interrupted by user")


if __name__ == "__main__":
    main()
