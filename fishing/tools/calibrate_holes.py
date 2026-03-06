"""
Hole Calibration Tool — walk to each fishing hole and press F5 to record exact coordinates.

Usage:
  python fishing/tools/calibrate_holes.py

Controls:
  F5 — Record current position as next hole
  F6 — Save and exit
  F7 — Undo last recorded hole

Outputs updated route_holes.json with calibrated coordinates.
"""

import json
import math
import os
import sys
import time

import keyboard
import mss

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixel_bridge import read_player_state

ROUTE_FILE = os.path.join(os.path.dirname(__file__), "..", "route_holes.json")


def main():
    # Load existing route
    if os.path.exists(ROUTE_FILE):
        with open(ROUTE_FILE, "r") as f:
            old_holes = json.load(f)
        print(f"[INFO] Existing route: {len(old_holes)} holes")
    else:
        old_holes = []
        print("[INFO] No existing route found")

    sct = mss.mss()
    monitor = sct.monitors[1]

    print()
    print("=" * 60)
    print("  HOLE CALIBRATION TOOL")
    print("=" * 60)
    print("  F5 — Record current position as next hole")
    print("  F6 — Save and exit")
    print("  F7 — Undo last recorded hole")
    print("=" * 60)
    print()

    # Show existing holes for reference
    if old_holes:
        print("Existing holes (for reference):")
        for i, h in enumerate(old_holes):
            print(f"  #{i+1}: ({h['x']}, {h['y']})")
        print()

    new_holes = []
    stop = [False]
    debounce = [0.0]

    def on_f5(_):
        if time.time() - debounce[0] < 1.5:
            return
        debounce[0] = time.time()

        state = read_player_state(sct, monitor)
        if not state:
            print("[ERROR] Can't read pixel bridge!")
            return

        idx = len(new_holes)
        new_holes.append({"x": int(state.x), "y": int(state.y)})

        # Show distance from old hole if exists
        old_info = ""
        if idx < len(old_holes):
            old = old_holes[idx]
            dx = state.x - old["x"]
            dy = state.y - old["y"]
            dist = math.sqrt(dx*dx + dy*dy)
            old_info = f"  (was ({old['x']}, {old['y']}), delta={dist:.0f})"

        print(f"  [#{idx+1}] Recorded: ({int(state.x)}, {int(state.y)}) "
              f"fish={state.is_fishing}{old_info}")

    def on_f6(_):
        if time.time() - debounce[0] < 1.5:
            return
        debounce[0] = time.time()
        stop[0] = True

    def on_f7(_):
        if time.time() - debounce[0] < 1.5:
            return
        debounce[0] = time.time()
        if new_holes:
            removed = new_holes.pop()
            print(f"  [UNDO] Removed #{len(new_holes)+1}: ({removed['x']}, {removed['y']})")
        else:
            print("  [UNDO] Nothing to undo")

    keyboard.on_press_key("f5", on_f5, suppress=False)
    keyboard.on_press_key("f6", on_f6, suppress=False)
    keyboard.on_press_key("f7", on_f7, suppress=False)

    print("Walk to each hole and press F5. Press F6 when done.\n")

    # Show live coordinates
    while not stop[0]:
        state = read_player_state(sct, monitor)
        if state:
            print(f"\r  Player: ({int(state.x)}, {int(state.y)}) "
                  f"fish={state.is_fishing} swim={state.is_swimming} "
                  f"| Recorded: {len(new_holes)} holes   ", end="", flush=True)
        time.sleep(0.5)

    print("\n")

    if not new_holes:
        print("[INFO] No holes recorded. Keeping old route.")
        return

    # Save
    with open(ROUTE_FILE, "w") as f:
        json.dump(new_holes, f, indent=2)
    print(f"[SAVED] {len(new_holes)} holes -> {ROUTE_FILE}")

    # Summary
    print("\nCalibrated holes:")
    for i, h in enumerate(new_holes):
        old_info = ""
        if i < len(old_holes):
            old = old_holes[i]
            dx = h["x"] - old["x"]
            dy = h["y"] - old["y"]
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 10:
                old_info = f"  MOVED {dist:.0f} units"
            else:
                old_info = "  (same)"
        else:
            old_info = "  NEW"
        print(f"  #{i+1}: ({h['x']}, {h['y']}){old_info}")


if __name__ == "__main__":
    main()
