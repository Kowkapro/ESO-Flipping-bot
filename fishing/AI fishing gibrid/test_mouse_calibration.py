"""
Mouse Sensitivity Calibration for ESO camera control.

Measures how many mouse pixels = full 360° turn in ESO.
This lets us calculate exact pixel count for any desired angle.

How it works:
1. You face a recognizable landmark (corner, pillar, etc.)
2. Script sends a known amount of mouse pixels
3. You tell it if you did a full 360° or not
4. Binary search narrows down the exact value

Result: PIXELS_PER_360 — how many px of mouse movement = one full rotation.
From this we derive PIXELS_PER_DEGREE = PIXELS_PER_360 / 360.

Usage:
  python "fishing/AI fishing gibrid/test_mouse_calibration.py"

Controls:
  F5 — Send test rotation (switch to ESO first!)
  F6 — Stop
"""

import ctypes
import ctypes.wintypes
import math
import random
import time

import keyboard


# ── Win32 SendInput ──────────────────────────────────────────────────

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT),
    ]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001


def send_mouse_move(dx, dy):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = 0
    inp.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.mi.time = 0
    inp.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def smooth_rotate(total_px, duration=0.5):
    """Rotate camera smoothly over given duration."""
    steps = max(20, int(abs(total_px) / 8))
    dt = duration / steps
    moved = 0

    for i in range(steps):
        t = (i + 1) / steps
        progress = (1 - math.cos(t * math.pi)) / 2
        target = int(total_px * progress)
        dx = target - moved
        moved = target
        send_mouse_move(dx, 0)
        time.sleep(dt)


def main():
    print("=" * 60)
    print("  MOUSE SENSITIVITY CALIBRATION")
    print("=" * 60)
    print()
    print("Instructions:")
    print("  1. Switch to ESO")
    print("  2. Face a recognizable landmark (wall corner, pillar)")
    print("  3. Press F5 — the script will rotate your camera")
    print("  4. Answer: did you end up facing the SAME landmark?")
    print("  5. Repeat until calibrated")
    print()
    print("  F5 — Send rotation")
    print("  F6 — Quit")
    print("=" * 60)

    # Start with a guess: 800 DPI, ESO speed 15
    # Typical range: 3000-8000 px for 360°
    test_px = 5000
    low = 2000
    high = 10000
    iteration = 0

    while True:
        print(f"\n--- Iteration {iteration + 1} ---")
        print(f"  Testing: {test_px} px (range: {low}-{high})")
        print(f"  Press F5 to rotate {test_px}px... (switch to ESO!)")

        event = keyboard.read_event(suppress=False)
        while not (event.event_type == "down" and event.name in ("f5", "f6")):
            event = keyboard.read_event(suppress=False)

        if event.name == "f6":
            print("\n[QUIT]")
            break

        # Wait a moment for user to switch
        time.sleep(0.3)

        print(f"  Rotating {test_px}px...")
        smooth_rotate(test_px, duration=max(0.3, test_px / 8000))
        time.sleep(0.5)

        print()
        print("  Did you end up facing the SAME landmark?")
        print("  [1] YES — exactly back (or very close)")
        print("  [2] OVERSHOT — turned MORE than 360°")
        print("  [3] UNDERSHOT — turned LESS than 360°")
        print("  [4] Skip — try again with same value")
        print("  [5] Manual — enter exact px value to test")

        choice = input("  Your answer (1/2/3/4/5): ").strip()

        if choice == "1":
            print(f"\n{'=' * 60}")
            print(f"  CALIBRATED!")
            print(f"  PIXELS_PER_360 = {test_px}")
            print(f"  PIXELS_PER_DEGREE = {test_px / 360:.2f}")
            print(f"  PIXELS_PER_RADIAN = {test_px / (2 * math.pi):.1f}")
            print(f"{'=' * 60}")
            print()
            print("  Use these values in your bot settings.")
            print(f"  Example: to turn 90°, send {test_px // 4} px")
            print(f"  Example: to turn 45°, send {test_px // 8} px")
            break

        elif choice == "2":
            # Overshot — need fewer pixels
            high = test_px
            test_px = (low + high) // 2
            print(f"  Overshot → reducing to {test_px}px")

        elif choice == "3":
            # Undershot — need more pixels
            low = test_px
            test_px = (low + high) // 2
            print(f"  Undershot → increasing to {test_px}px")

        elif choice == "5":
            try:
                val = int(input("  Enter px value: ").strip())
                test_px = val
                low = min(low, val - 500)
                high = max(high, val + 500)
            except ValueError:
                print("  Invalid number, keeping current value")

        else:
            print("  Retrying same value...")

        iteration += 1

        # Safety: if range is narrow enough, we're done
        if high - low < 100:
            test_px = (low + high) // 2
            print(f"\n{'=' * 60}")
            print(f"  Range narrowed! Best estimate:")
            print(f"  PIXELS_PER_360 ≈ {test_px}")
            print(f"  PIXELS_PER_DEGREE ≈ {test_px / 360:.2f}")
            print(f"  PIXELS_PER_RADIAN ≈ {test_px / (2 * math.pi):.1f}")
            print(f"{'=' * 60}")
            break


if __name__ == "__main__":
    main()
