"""Isolated test for disconnect recovery.

Usage:
  1. Get ESO to the disconnect error screen (or login screen)
  2. Run this script
  3. Press F5 to start the reconnect sequence
  4. Watch each step execute

Steps can be tested individually with command-line args:
  python test_reconnect.py          # full sequence (error popup → login → play → bridge)
  python test_reconnect.py --step 1 # only: close error popup (Alt)
  python test_reconnect.py --step 2 # only: click ВОЙТИ
  python test_reconnect.py --step 3 # only: click ИГРАТЬ
  python test_reconnect.py --step 4 # only: wait for pixel bridge
  python test_reconnect.py --detect # detect current screen state (no actions)
  python test_reconnect.py --screenshot # just take a screenshot and save it
"""

import argparse
import math
import os
import random
import sys
import time

import keyboard
import mss
import pyautogui
from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(__file__))
from pixel_bridge import read_player_state
from main_v5 import detect_screen_state, mouse_click_win32, BTN_VOITI, BTN_IGRAT


def take_screenshot(label="screenshot"):
    """Save a screenshot for debugging."""
    img = ImageGrab.grab()
    path = os.path.join(os.path.dirname(__file__), f"debug_{label}.png")
    img.save(path)
    print(f"[SCREENSHOT] Saved: {path}")
    return path


def press_key(key, hold=0.05):
    import pydirectinput
    pydirectinput.keyDown(key)
    time.sleep(hold)
    pydirectinput.keyUp(key)


def detect_and_print():
    """Detect and print current screen state with pixel details."""
    img = ImageGrab.grab()

    # Sample all detection points
    from main_v5 import _DETECT_POINTS

    points = dict(_DETECT_POINTS)
    points['top_menu'] = (85, 22)
    points['popup_body'] = (700, 310)

    print("\n--- Screen Detection Debug ---")
    for name, (x, y) in points.items():
        r, g, b = img.getpixel((x, y))[:3]
        print(f"  {name:15s} ({x:4d},{y:4d}): RGB=({r:3d},{g:3d},{b:3d}) sum={r+g+b} avg={(r+g+b)/3:.0f}")

    state = detect_screen_state()
    print(f"\n  >>> Detected: {state}")
    return state


def step1_close_popup():
    """Step 1: Close error popup with Alt."""
    print("\n[STEP 1] Closing error popup (Alt)...")
    state = detect_and_print()
    take_screenshot("before_step1")
    if state != 'error_popup':
        print(f"[STEP 1] WARNING: expected 'error_popup', got '{state}'")
    time.sleep(random.uniform(1.0, 2.0))
    press_key('alt')
    time.sleep(2.0)
    state = detect_and_print()
    take_screenshot("after_step1")
    print(f"[STEP 1] Done. Screen: {state}")


def step2_click_voiti():
    """Step 2: Click ВОЙТИ button."""
    print(f"\n[STEP 2] Clicking 'ВОЙТИ' at {BTN_VOITI}...")
    state = detect_and_print()
    take_screenshot("before_step2")
    if state != 'login':
        print(f"[STEP 2] WARNING: expected 'login', got '{state}'")
    mouse_click_win32(*BTN_VOITI)
    print("[STEP 2] Clicked. Waiting for char select...")
    for i in range(30):
        time.sleep(1)
        state = detect_screen_state()
        print(f"  {i+1}s... screen={state}", end="\r")
        if state == 'char_select':
            print(f"\n[STEP 2] Character select detected after {i+1}s!")
            break
    print()
    detect_and_print()
    take_screenshot("after_step2")
    print("[STEP 2] Done.")


def step3_click_igrat():
    """Step 3: Click ИГРАТЬ button."""
    print(f"\n[STEP 3] Clicking 'ИГРАТЬ' at {BTN_IGRAT}...")
    state = detect_and_print()
    take_screenshot("before_step3")
    if state != 'char_select':
        print(f"[STEP 3] WARNING: expected 'char_select', got '{state}'")
    mouse_click_win32(*BTN_IGRAT)
    # Don't waste time here — step4 will wait for pixel bridge
    print("[STEP 3] Clicked. Handing off to step4...")
    take_screenshot("after_step3_click")
    print("[STEP 3] Done.")


def step4_wait_bridge():
    """Step 4: Wait for pixel bridge to become available.
    Also handles case where char_select appears (clicks ИГРАТЬ)."""
    print("\n[STEP 4] Waiting for pixel bridge (up to 120s)...")
    clicked_igrat = False
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        for i in range(120):  # up to 120s
            state = read_player_state(sct, monitor)
            if state:
                print(f"\n[STEP 4] SUCCESS! Player at ({state.x:.0f}, {state.y:.0f}), "
                      f"heading={math.degrees(state.heading):.1f}, "
                      f"slots={state.free_slots}")
                return True
            screen = detect_screen_state()
            # If char_select appears and we haven't clicked ИГРАТЬ yet
            if screen == 'char_select' and not clicked_igrat:
                print(f"\n[STEP 4] Char select detected — clicking ИГРАТЬ...")
                time.sleep(random.uniform(0.5, 1.5))
                mouse_click_win32(*BTN_IGRAT)
                clicked_igrat = True
            if i % 10 == 9:
                print(f"\n  {i+1}s elapsed, screen={screen}")
            else:
                print(f"  Waiting... {i+1}/120s (screen={screen})", end="\r")
            time.sleep(1.0)
    print("\n[STEP 4] FAILED — pixel bridge not available after 120s")
    take_screenshot("bridge_failed")
    return False


def full_reconnect():
    """Run all 4 steps in sequence with screen detection."""
    print("=" * 60)
    print("  DISCONNECT RECOVERY TEST (with screen detection)")
    print("=" * 60)

    state = detect_and_print()

    if state == 'error_popup':
        step1_close_popup()
        state = detect_screen_state()

    if state == 'login':
        step2_click_voiti()
        state = detect_screen_state()

    # Wait for loading → char_select if still in loading
    if state == 'loading':
        print("[WAIT] Loading screen detected, waiting for char select...")
        for i in range(60):
            time.sleep(1.0)
            state = detect_screen_state()
            if state != 'loading':
                print(f"  Loading done after {i+1}s → {state}")
                break

    if state == 'char_select':
        step3_click_igrat()

    ok = step4_wait_bridge()
    print()
    if ok:
        print("RESULT: SUCCESS — reconnected!")
    else:
        print("RESULT: FAILED — check debug_*.png screenshots")


def main():
    parser = argparse.ArgumentParser(description="Test disconnect recovery")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4],
                        help="Run only a specific step")
    parser.add_argument("--detect", action="store_true",
                        help="Detect current screen state and exit")
    parser.add_argument("--screenshot", action="store_true",
                        help="Just take a screenshot and exit")
    args = parser.parse_args()

    if args.screenshot:
        take_screenshot("manual")
        return

    if args.detect:
        print("Press F5 when ESO is visible...")
        keyboard.wait("f5")
        time.sleep(0.5)
        detect_and_print()
        keyboard.unhook_all()
        return

    print("Press F5 when ESO is visible to start...")
    keyboard.wait("f5")
    time.sleep(0.5)

    if args.step:
        steps = {1: step1_close_popup, 2: step2_click_voiti,
                 3: step3_click_igrat, 4: step4_wait_bridge}
        steps[args.step]()
    else:
        full_reconnect()

    keyboard.unhook_all()


if __name__ == "__main__":
    main()
