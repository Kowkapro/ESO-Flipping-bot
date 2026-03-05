"""
Calibration tool for ESO Fishing Bot Phase 3.

Measures:
  1. Sprint speed (world units/sec)
  2. Mouse sensitivity (pixels/radian)

Controls:
  F7  - Start/stop sprint speed test
  F8  - Start mouse sensitivity test
  F10 - Exit

Requires: FishingNav addon active in ESO, admin rights for keyboard hooks.
"""

import math
import time
import threading

import keyboard
import pydirectinput

from navigation import (
    read_player_position,
    force_reloadui_and_read,
    distance_2d,
    _send_mouse_move,
    RELOADUI_WAIT,
)

# ─── State ────────────────────────────────────────────────────────
busy = False
done = False


def sprint_speed_test():
    """Measure sprint speed by sprinting in a straight line.

    1. /reloadui -> read start position
    2. Sprint forward for N seconds
    3. /reloadui -> read end position
    4. Calculate distance / time = speed
    """
    global busy
    if busy:
        return
    busy = True

    SPRINT_DURATION = 8.0  # seconds to sprint

    print("\n[CAL] === Sprint Speed Test ===")
    print("[CAL] Step 1: Reading start position (/reloadui)...")
    print("[CAL] Make sure you're facing open terrain with no obstacles!")

    start_pos = force_reloadui_and_read()
    if not start_pos:
        print("[CAL] ERROR: Could not read position!")
        busy = False
        return

    print(f"[CAL] Start: x={start_pos['worldX']:.1f}, y={start_pos['worldY']:.1f}")
    print(f"[CAL] Waiting for UI to reload...")
    time.sleep(RELOADUI_WAIT)

    print(f"[CAL] Step 2: Sprinting forward for {SPRINT_DURATION} sec...")
    pydirectinput.keyDown('shift')
    time.sleep(0.05)
    pydirectinput.keyDown('w')

    start_time = time.time()
    time.sleep(SPRINT_DURATION)
    elapsed = time.time() - start_time

    pydirectinput.keyUp('w')
    pydirectinput.keyUp('shift')
    time.sleep(0.3)

    print(f"[CAL] Sprinted for {elapsed:.2f} sec")
    print(f"[CAL] Step 3: Reading end position (/reloadui)...")

    end_pos = force_reloadui_and_read()
    if not end_pos:
        print("[CAL] ERROR: Could not read end position!")
        busy = False
        return

    print(f"[CAL] End: x={end_pos['worldX']:.1f}, y={end_pos['worldY']:.1f}")

    dist = distance_2d(
        start_pos["worldX"], start_pos["worldY"],
        end_pos["worldX"], end_pos["worldY"],
    )
    speed = dist / elapsed

    print(f"\n[CAL] ========== RESULT ==========")
    print(f"[CAL] Distance: {dist:.1f} world units")
    print(f"[CAL] Time: {elapsed:.2f} sec")
    print(f"[CAL] Sprint speed: {speed:.1f} units/sec")
    print(f"[CAL] ==============================")
    print(f"[CAL] Set SPRINT_SPEED = {speed:.1f} in navigation.py")

    busy = False


def mouse_sensitivity_test():
    """Measure mouse sensitivity (pixels per radian).

    1. /reloadui -> read heading
    2. Move mouse by PIXELS_TO_MOVE horizontally
    3. /reloadui -> read new heading
    4. Calculate pixels / delta_heading
    """
    global busy
    if busy:
        return
    busy = True

    PIXELS_TO_MOVE = 800  # pixels to move mouse

    print("\n[CAL] === Mouse Sensitivity Test ===")
    print("[CAL] Step 1: Reading start heading (/reloadui)...")
    print("[CAL] Don't touch the mouse after pressing F8!")

    start_pos = force_reloadui_and_read()
    if not start_pos:
        print("[CAL] ERROR: Could not read position!")
        busy = False
        return

    start_heading = start_pos.get("heading", 0)
    print(f"[CAL] Start heading: {start_heading:.4f} rad ({math.degrees(start_heading):.1f} deg)")
    print(f"[CAL] Waiting for UI to reload...")
    time.sleep(RELOADUI_WAIT)

    print(f"[CAL] Step 2: Moving mouse {PIXELS_TO_MOVE} pixels right (SendInput)...")
    time.sleep(0.5)

    # Move in small steps via Win32 SendInput (ESO ignores pydirectinput mouse)
    step_px = 50
    steps = PIXELS_TO_MOVE // step_px
    remainder = PIXELS_TO_MOVE % step_px
    for _ in range(steps):
        _send_mouse_move(step_px, 0)
        time.sleep(0.02)
    if remainder > 0:
        _send_mouse_move(remainder, 0)

    time.sleep(0.3)

    # Take a brief step forward so the character turns to face the camera direction
    # (GetMapPlayerPosition returns character heading, not camera heading)
    print(f"[CAL] Step 3: Taking a step forward (so character faces camera)...")
    pydirectinput.keyDown('w')
    time.sleep(0.5)
    pydirectinput.keyUp('w')
    time.sleep(0.3)

    print(f"[CAL] Step 4: Reading end heading (/reloadui)...")

    end_pos = force_reloadui_and_read()
    if not end_pos:
        print("[CAL] ERROR: Could not read end position!")
        busy = False
        return

    end_heading = end_pos.get("heading", 0)
    print(f"[CAL] End heading: {end_heading:.4f} rad ({math.degrees(end_heading):.1f} deg)")

    # Calculate angle difference (handle wraparound)
    delta = end_heading - start_heading
    while delta > math.pi:
        delta -= 2 * math.pi
    while delta < -math.pi:
        delta += 2 * math.pi

    if abs(delta) < 0.01:
        print("[CAL] ERROR: No rotation detected! Is the game focused?")
        busy = False
        return

    sensitivity = PIXELS_TO_MOVE / abs(delta)

    print(f"\n[CAL] ========== RESULT ==========")
    print(f"[CAL] Pixels moved: {PIXELS_TO_MOVE}")
    print(f"[CAL] Angle rotated: {abs(delta):.4f} rad ({abs(math.degrees(delta)):.1f} deg)")
    print(f"[CAL] Direction: {'right' if delta > 0 else 'left'}")
    print(f"[CAL] Sensitivity: {sensitivity:.1f} pixels/radian")
    print(f"[CAL] ==============================")
    print(f"[CAL] Set MOUSE_SENSITIVITY = {sensitivity:.1f} in navigation.py")

    busy = False


def main():
    global done

    print("=" * 50)
    print("  ESO Fishing Bot — Calibration Tool")
    print("=" * 50)
    print()
    print("  F7  - Sprint speed test")
    print("        (sprints 8 sec, measures distance)")
    print("  F8  - Mouse sensitivity test")
    print("        (rotates camera, measures angle)")
    print("  F10 - Exit")
    print()
    print("  Make sure ESO is focused before pressing F7/F8!")
    print("  Each test does /reloadui twice (~10-15 sec total)")
    print("=" * 50)

    def on_f7():
        threading.Thread(target=sprint_speed_test, daemon=True).start()

    def on_f8():
        threading.Thread(target=mouse_sensitivity_test, daemon=True).start()

    def on_f10():
        global done
        done = True

    keyboard.on_press_key("f7", lambda _: on_f7(), suppress=False)
    keyboard.on_press_key("f8", lambda _: on_f8(), suppress=False)
    keyboard.on_press_key("f10", lambda _: on_f10(), suppress=False)

    print("\n[CAL] Ready. Press F7 or F8 to start a test.\n")

    while not done:
        time.sleep(0.1)

    keyboard.unhook_all()
    print("\n[CAL] Done.")


if __name__ == "__main__":
    main()
