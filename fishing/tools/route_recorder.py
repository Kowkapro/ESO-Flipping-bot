"""
Route Recorder for ESO Fishing Bot.

Walk manually between fishing holes and press F7 to mark each waypoint.
The recorded route is saved as JSON for the navigation module.

Controls:
  F7  - Mark current position as a fishing waypoint
  F8  - Mark current position as a walk-through waypoint (no fishing)
  F9  - Save route and exit
  F10 - Discard and exit

How it works:
  On F7/F8 press, the script sends /script ReloadUI() to ESO chat,
  which forces SavedVariables to flush to disk with fresh coordinates.
  Takes ~5 seconds per waypoint.

Requires: FishingNav Lua addon running in ESO to provide coordinates.
"""

import json
import math
import os
import re
import sys
import time
import threading

# Add parent dir (fishing/) to path so we can import navigation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import keyboard

from navigation import (
    read_player_position,
    force_reloadui_and_read as force_save_and_read,
    FISHINGNAV_FILE,
)

ROUTES_DIR = os.path.join(os.path.dirname(__file__), "routes")


def main():
    print("=" * 50)
    print("  ESO Route Recorder")
    print("=" * 50)
    print()
    print("  F7  - Mark FISHING waypoint (bot will fish here)")
    print("  F8  - Mark WALK waypoint (just pass through)")
    print("  F9  - Save route and exit")
    print("  F10 - Discard and exit")
    print()
    print("  NOTE: Each F7/F8 will trigger /reloadui in ESO (~5 sec)")
    print("  Make sure ESO is focused when you press F7/F8!")
    print("=" * 50)

    # Check FishingNav data
    print("\n[REC] Checking FishingNav addon data...")
    pos = read_player_position()
    if not pos:
        print("[ERROR] Cannot read FishingNav data!")
        print(f"  File: {FISHINGNAV_FILE}")
        print("  Make sure:")
        print("  1. FishingNav addon is installed and enabled in ESO")
        print("  2. You have logged in and moved around")
        print("  3. ESO has saved the data (try /reloadui)")
        sys.exit(1)

    zone = pos.get("zoneName", "unknown")
    map_name = pos.get("mapName", "unknown")
    print(f"[REC] Connected! Zone: {zone}, Map: {map_name}")
    print(f"[REC] Position: x={pos['worldX']:.0f}, y={pos['worldY']:.0f}")
    print(f"\n[REC] Ready. Go to a fishing hole and press F7.\n")

    waypoints = []
    done = False
    busy = False  # Prevent concurrent reloadui calls

    def record_waypoint(wp_type):
        nonlocal busy
        if busy:
            return
        busy = True

        print(f"  [..] Saving position ({wp_type})... /reloadui sent")
        pos = force_save_and_read()
        if pos:
            wp = {
                "x": pos["worldX"],
                "y": pos["worldY"],
                "z": pos["worldZ"],
                "heading": pos.get("heading", 0),
                "type": wp_type,
            }
            waypoints.append(wp)
            label = "FISHING" if wp_type == "fishing" else "WALK"
            print(
                f"  [#{len(waypoints)}] {label} at "
                f"x={wp['x']:.0f}, y={wp['y']:.0f}"
            )
        else:
            print("  [!] Timeout waiting for position update")

        busy = False

    def on_f7():
        threading.Thread(target=record_waypoint, args=("fishing",), daemon=True).start()

    def on_f8():
        threading.Thread(target=record_waypoint, args=("walk",), daemon=True).start()

    def on_f9():
        nonlocal done
        done = True

    def on_f10():
        nonlocal done
        waypoints.clear()
        done = True

    keyboard.on_press_key("f7", lambda _: on_f7(), suppress=False)
    keyboard.on_press_key("f8", lambda _: on_f8(), suppress=False)
    keyboard.on_press_key("f9", lambda _: on_f9(), suppress=False)
    keyboard.on_press_key("f10", lambda _: on_f10(), suppress=False)

    while not done:
        time.sleep(0.1)

    keyboard.unhook_all()

    if waypoints:
        save_route(waypoints, zone)
    else:
        print("\n[REC] No waypoints recorded. Nothing saved.")


def save_route(waypoints, zone):
    """Save recorded route to a JSON file."""
    zone_clean = re.sub(r'\^[FMNfmn]', '', zone)
    zone_clean = zone_clean.strip().lower().replace(" ", "_")
    _translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
        'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    zone_clean = ''.join(_translit.get(c, c) for c in zone_clean)
    fishing_count = sum(1 for wp in waypoints if wp["type"] == "fishing")

    route = {
        "zone": zone,
        "fishing_holes": fishing_count,
        "total_waypoints": len(waypoints),
        "waypoints": waypoints,
    }

    os.makedirs(ROUTES_DIR, exist_ok=True)

    existing = [f for f in os.listdir(ROUTES_DIR) if f.startswith(zone_clean)]
    index = len(existing) + 1
    filename = f"{zone_clean}_route_{index}.json"
    filepath = os.path.join(ROUTES_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(route, f, indent=2)

    print(f"\n[REC] Route saved: {filepath}")
    print(f"  Waypoints: {len(waypoints)} ({fishing_count} fishing, "
          f"{len(waypoints) - fishing_count} walk)")

    print(f"\n  Route preview:")
    for i, wp in enumerate(waypoints):
        marker = "[FISH]" if wp["type"] == "fishing" else "[WALK]"
        print(f"    {marker} #{i+1}: x={wp['x']:.0f}, y={wp['y']:.0f}")
        if i > 0:
            prev = waypoints[i - 1]
            dist = math.sqrt(
                (wp["x"] - prev["x"]) ** 2 + (wp["y"] - prev["y"]) ** 2
            )
            print(f"       (distance from prev: {dist:.0f} units)")


if __name__ == "__main__":
    main()
