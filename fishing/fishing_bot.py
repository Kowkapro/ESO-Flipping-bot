"""
ESO Fishing Bot
Automates fishing: cast -> detect hook -> reel -> loot -> repeat
Requires Votan's Fisherman addon (shows white hook icon on bite)

Phase 1: Single hole fishing (default)
Phase 2: Route navigation between multiple fishing holes
  Requires FishingNav Lua addon for player coordinates

Controls:
  F5  - Start/Pause bot
  F6  - Stop bot completely

Usage:
  python fishing_bot.py                         # Phase 1: single hole
  python fishing_bot.py routes/my_route.json    # Phase 2: navigate route
"""

import argparse
import time
import random
import sys
import ctypes
import threading

import os
import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

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
MAX_FAILED_CASTS = 2         # Failed casts in a row before hole is considered depleted

# ─── Telegram ───────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── State ──────────────────────────────────────────────────────────
running = False
paused = False
fish_count = 0
cast_count = 0
failed_casts = 0


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


def send_telegram(message):
    """Send a notification to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TG] No Telegram config, skipping: {message}")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
        print(f"[TG] Sent: {message}")
    except Exception as e:
        print(f"[TG] Failed to send: {e}")


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


def fish_one_hole():
    """Fish at the current hole until depleted.

    Returns True if hole was depleted (should move to next),
    False if bot was stopped/paused externally.
    """
    global fish_count, cast_count, failed_casts

    hole_fish = 0

    while running and not paused:
        # Step 1: Cast line (press E)
        cast_count += 1
        print(f"[{cast_count}] Casting...")
        press_key(CAST_KEY)
        human_delay(DELAY_AFTER_CAST)

        # Step 2: Wait for hook icon
        print(f"[{cast_count}] Waiting for bite...")
        if not wait_for_hook():
            if not running:
                return False

            failed_casts += 1
            print(f"[{cast_count}] No bite (failed: {failed_casts}/{MAX_FAILED_CASTS})")

            if failed_casts >= MAX_FAILED_CASTS:
                print(f"\n[BOT] HOLE DEPLETED! Fish from this hole: {hole_fish}")
                failed_casts = 0
                return True  # Hole depleted, move to next
            else:
                human_delay(DELAY_RECAST)
            continue

        # Reset failed cast counter on successful bite
        failed_casts = 0

        # Step 3: Reel in (press E)
        human_delay(DELAY_REEL_REACTION)
        print(f"[{cast_count}] HOOK! Reeling in...")
        press_key(CAST_KEY)

        # Step 4: Wait for loot window to appear
        print(f"[{cast_count}] Waiting for loot window...")
        human_delay(DELAY_AFTER_REEL)

        # Step 5: Loot (press R)
        fish_count += 1
        hole_fish += 1
        print(f"[{cast_count}] Fish #{fish_count}! Pressing R to loot...")
        press_key(LOOT_KEY)
        time.sleep(0.3)
        press_key(LOOT_KEY)
        human_delay(DELAY_AFTER_LOOT)

    return False


def fishing_loop():
    """Phase 1: Single hole fishing (original mode)."""
    global running, paused, fish_count, cast_count, failed_casts

    print("\n[BOT] Starting fishing loop (single hole mode)...")
    print("[BOT] Make sure you are facing a fishing hole!\n")
    send_telegram("🎣 Fishing bot started!")

    while running:
        if paused:
            time.sleep(0.5)
            continue

        depleted = fish_one_hole()

        if depleted and running:
            msg = (
                f"🔴 Лунка иссякла!\n"
                f"Поймано рыб: {fish_count}\n"
                f"Забросов: {cast_count}\n"
                f"Перемести персонажа и нажми F5"
            )
            send_telegram(msg)
            paused = True

    send_telegram(f"⏹ Bot stopped. Fish: {fish_count}, Casts: {cast_count}")
    print(f"\n[BOT] Stopped. Casts: {cast_count}, Fish caught: {fish_count}")


def fishing_route_loop(route_file):
    """Phase 2: Navigate between fishing holes using a recorded route."""
    global running, paused, fish_count, cast_count

    from navigation import (
        load_route, navigate_route, sprint_escape, read_player_position
    )

    route = load_route(route_file)
    waypoints = route["waypoints"]
    fishing_count = sum(1 for wp in waypoints if wp["type"] == "fishing")

    print(f"\n[BOT] Starting route mode: {route['zone']}")
    print(f"[BOT] Waypoints: {len(waypoints)} ({fishing_count} fishing holes)")
    send_telegram(
        f"🎣 Fishing bot started (route mode)\n"
        f"Zone: {route['zone']}\n"
        f"Fishing holes: {fishing_count}"
    )

    # Check FishingNav is working
    pos = read_player_position()
    if not pos:
        print("[ERROR] Cannot read FishingNav data! Is the addon active?")
        send_telegram("❌ FishingNav not responding!")
        return

    circuit = 0

    while running:
        if paused:
            time.sleep(0.5)
            continue

        circuit += 1
        print(f"\n[BOT] === Circuit #{circuit} ===")
        send_telegram(f"🔄 Circuit #{circuit} starting (total fish: {fish_count})")

        for i, wp in enumerate(waypoints):
            if not running or paused:
                break

            # Navigate to waypoint
            print(f"\n[NAV] → Waypoint #{i+1}/{len(waypoints)} ({wp['type']})")

            def check_running():
                return running and not paused

            def on_combat():
                print("[BOT] Combat detected! Sprinting away...")
                send_telegram("⚔️ Мобы атаковали — убегаю!")
                sprint_escape()
                return True  # Continue after sprinting

            def on_stuck():
                print("[BOT] Stuck! Pausing...")
                send_telegram(
                    f"🚧 Бот застрял!\n"
                    f"Рыб: {fish_count}, Забросов: {cast_count}\n"
                    f"Нажми F5 после ручного перемещения"
                )
                global paused
                paused = True
                return False

            from navigation import move_to_waypoint
            arrived = move_to_waypoint(
                wp["x"], wp["y"],
                check_running=check_running,
                on_combat=on_combat,
                on_stuck=on_stuck,
            )

            if not arrived:
                if not running:
                    break
                continue

            # At waypoint — fish if it's a fishing spot
            if wp["type"] == "fishing":
                print(f"[BOT] Arrived at fishing hole #{i+1}. Starting to fish...")
                human_delay((1.0, 2.0))  # Settle before fishing

                depleted = fish_one_hole()

                if depleted:
                    print(f"[BOT] Hole #{i+1} depleted. Moving to next...")
                    send_telegram(
                        f"🐟 Hole #{i+1} done (total fish: {fish_count})"
                    )
                elif not running:
                    break

        # Circuit complete
        if running and not paused:
            print(f"\n[BOT] Circuit #{circuit} complete! Total fish: {fish_count}")
            human_delay((3.0, 6.0))  # Pause between circuits

    send_telegram(
        f"⏹ Bot stopped.\n"
        f"Circuits: {circuit}, Fish: {fish_count}, Casts: {cast_count}"
    )
    print(f"\n[BOT] Stopped. Circuits: {circuit}, "
          f"Casts: {cast_count}, Fish: {fish_count}")


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

    parser = argparse.ArgumentParser(description="ESO Fishing Bot")
    parser.add_argument(
        "route", nargs="?", default=None,
        help="Path to route JSON file for Phase 2 (navigation mode)"
    )
    args = parser.parse_args()

    route_mode = args.route is not None

    print("=" * 50)
    print("  ESO Fishing Bot")
    if route_mode:
        print(f"  Mode: ROUTE NAVIGATION")
        print(f"  Route: {args.route}")
    else:
        print(f"  Mode: SINGLE HOLE")
    print("=" * 50)
    print()
    print("  F5 - Start / Pause")
    print("  F6 - Stop")
    print()
    if route_mode:
        print("  Bot will navigate between fishing holes automatically.")
    else:
        print("  Stand in front of a fishing hole and press F5")
    print("=" * 50)

    get_screen_regions()

    # Validate route file if specified
    if route_mode and not os.path.exists(args.route):
        print(f"\n[ERROR] Route file not found: {args.route}")
        sys.exit(1)

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

    # Run appropriate loop
    try:
        if route_mode:
            fishing_route_loop(args.route)
        else:
            fishing_loop()
    except KeyboardInterrupt:
        running = False
        print("\n[BOT] Interrupted by user")


if __name__ == "__main__":
    main()
