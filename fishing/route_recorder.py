"""
Route Recorder for ESO Fishing Bot.

Walk manually between fishing holes and press F7 to mark each waypoint.
The recorded route is saved as JSON for the navigation module.

Controls:
  F7  - Mark current position as a fishing waypoint
  F8  - Mark current position as a walk-through waypoint (no fishing)
  F9  - Save route and exit
  F10 - Discard and exit

Requires: FishingNav Lua addon running in ESO to provide coordinates.
"""

import ctypes
import json
import math
import os
import re
import sys
import time

SAVED_VARS_DIR = os.path.join(
    "d:", os.sep, "Documents", "Elder Scrolls Online", "live", "SavedVariables"
)
FISHINGNAV_FILE = os.path.join(SAVED_VARS_DIR, "FishingNav_Data.lua")
ROUTES_DIR = os.path.join(os.path.dirname(__file__), "routes")


def read_player_position():
    """Read current player position from FishingNav SavedVariables.

    Returns dict with x, y, z, heading, zoneName, mapName, inCombat
    or None if data unavailable.
    """
    if not os.path.exists(FISHINGNAV_FILE):
        return None

    try:
        with open(FISHINGNAV_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    data = {}
    # Parse key-value pairs from Lua SavedVariables
    for key in ["worldX", "worldY", "worldZ", "heading", "timestamp"]:
        match = re.search(rf'\["{key}"\]\s*=\s*(-?\d+\.?\d*)', content)
        if match:
            data[key] = float(match.group(1))

    for key in ["zoneName", "mapName"]:
        match = re.search(rf'\["{key}"\]\s*=\s*"([^"]*)"', content)
        if match:
            data[key] = match.group(1)

    match = re.search(r'\["inCombat"\]\s*=\s*(true|false)', content)
    if match:
        data["inCombat"] = match.group(1) == "true"

    if "worldX" not in data:
        return None

    return data


def distance_2d(p1, p2):
    """Calculate 2D distance between two points."""
    dx = p1["worldX"] - p2["worldX"]
    dy = p1["worldY"] - p2["worldY"]
    return math.sqrt(dx * dx + dy * dy)


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
    print("  Walk between fishing holes, pressing F7 at each one.")
    print("  Use F8 for corners/turns where bot needs to change direction.")
    print("=" * 50)

    # Check FishingNav data is available
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
    print(f"[REC] Position: x={pos['worldX']:.1f}, y={pos['worldY']:.1f}")
    print(f"\n[REC] Ready. Start walking and press F7 at fishing holes.\n")

    waypoints = []

    # Windows virtual key codes
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79

    last_press_time = 0

    while True:
        now = time.time()

        # Debounce (300ms)
        if now - last_press_time < 0.3:
            time.sleep(0.05)
            continue

        if ctypes.windll.user32.GetAsyncKeyState(VK_F7) & 0x8000:
            pos = read_player_position()
            if pos:
                wp = {
                    "x": pos["worldX"],
                    "y": pos["worldY"],
                    "z": pos["worldZ"],
                    "heading": pos.get("heading", 0),
                    "type": "fishing",
                }
                waypoints.append(wp)
                print(
                    f"  [#{len(waypoints)}] FISHING at "
                    f"x={wp['x']:.1f}, y={wp['y']:.1f}"
                )
            last_press_time = now

        elif ctypes.windll.user32.GetAsyncKeyState(VK_F8) & 0x8000:
            pos = read_player_position()
            if pos:
                wp = {
                    "x": pos["worldX"],
                    "y": pos["worldY"],
                    "z": pos["worldZ"],
                    "heading": pos.get("heading", 0),
                    "type": "walk",
                }
                waypoints.append(wp)
                print(
                    f"  [#{len(waypoints)}] WALK at "
                    f"x={wp['x']:.1f}, y={wp['y']:.1f}"
                )
            last_press_time = now

        elif ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8000:
            if not waypoints:
                print("\n[REC] No waypoints recorded! Nothing to save.")
            else:
                save_route(waypoints, zone)
            break

        elif ctypes.windll.user32.GetAsyncKeyState(VK_F10) & 0x8000:
            print("\n[REC] Discarded. No route saved.")
            break

        time.sleep(0.05)


def save_route(waypoints, zone):
    """Save recorded route to a JSON file."""
    zone_clean = zone.lower().replace(" ", "_")
    fishing_count = sum(1 for wp in waypoints if wp["type"] == "fishing")

    route = {
        "zone": zone,
        "fishing_holes": fishing_count,
        "total_waypoints": len(waypoints),
        "waypoints": waypoints,
    }

    # Generate filename
    existing = [f for f in os.listdir(ROUTES_DIR) if f.startswith(zone_clean)]
    index = len(existing) + 1
    filename = f"{zone_clean}_route_{index}.json"
    filepath = os.path.join(ROUTES_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(route, f, indent=2)

    print(f"\n[REC] Route saved: {filepath}")
    print(f"  Waypoints: {len(waypoints)} ({fishing_count} fishing, "
          f"{len(waypoints) - fishing_count} walk)")

    # Show route summary
    print(f"\n  Route preview:")
    for i, wp in enumerate(waypoints):
        marker = "🎣" if wp["type"] == "fishing" else "🚶"
        print(f"    {marker} #{i+1}: x={wp['x']:.1f}, y={wp['y']:.1f}")
        if i > 0:
            prev = waypoints[i - 1]
            dist = math.sqrt(
                (wp["x"] - prev["x"]) ** 2 + (wp["y"] - prev["y"]) ** 2
            )
            print(f"       (distance from prev: {dist:.0f} units)")


if __name__ == "__main__":
    main()
