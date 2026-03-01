"""
Navigation module for ESO Fishing Bot.

Handles movement between waypoints using:
- FishingNav Lua addon for player position/heading
- pydirectinput for WASD movement and mouse rotation
- Combat detection and sprint escape

Coordinate system:
  ESO uses GetUnitRawWorldPosition which returns worldX, worldZ, worldY
  Our FishingNav addon saves worldX, worldY, worldZ (already swapped)
  Heading from GetMapPlayerPosition is in radians, 0 = North, increases clockwise
"""

import json
import math
import os
import random
import re
import time

import pydirectinput

# ─── Settings ──────────────────────────────────────────────────────
ARRIVAL_THRESHOLD = 5.0        # Distance (world units) to consider "arrived" at waypoint
POSITION_READ_INTERVAL = 0.2   # How often to read position while moving (seconds)
STUCK_TIMEOUT = 10.0           # Seconds without movement before declaring stuck
STUCK_DISTANCE = 2.0           # Min distance to move in STUCK_TIMEOUT to not be stuck
SPRINT_ESCAPE_DURATION = 5.0   # Seconds to sprint when fleeing from combat
COMBAT_CHECK_INTERVAL = 1.0    # How often to check combat state while moving

# Mouse sensitivity for rotation (pixels per radian)
# This needs calibration — depends on ESO mouse sensitivity settings
MOUSE_SENSITIVITY = 400.0

# Movement keys
KEY_FORWARD = 'w'
KEY_SPRINT = 'shift'

SAVED_VARS_DIR = os.path.join(
    "d:", os.sep, "Documents", "Elder Scrolls Online", "live", "SavedVariables"
)
FISHINGNAV_FILE = os.path.join(SAVED_VARS_DIR, "FishingNav_Data.lua")


def read_player_position():
    """Read current player position from FishingNav SavedVariables.

    Returns dict with worldX, worldY, worldZ, heading, inCombat
    or None if unavailable.
    """
    if not os.path.exists(FISHINGNAV_FILE):
        return None

    try:
        with open(FISHINGNAV_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    data = {}
    for key in ["worldX", "worldY", "worldZ", "heading", "timestamp"]:
        match = re.search(rf'\["{key}"\]\s*=\s*(-?\d+\.?\d*)', content)
        if match:
            data[key] = float(match.group(1))

    match = re.search(r'\["inCombat"\]\s*=\s*(true|false)', content)
    if match:
        data["inCombat"] = match.group(1) == "true"
    else:
        data["inCombat"] = False

    if "worldX" not in data:
        return None

    return data


def calculate_angle(current_x, current_y, target_x, target_y):
    """Calculate angle from current position to target (radians, 0=North, CW).

    ESO heading: 0 = North, pi/2 = East, pi = South, 3pi/2 = West
    """
    dx = target_x - current_x
    dy = target_y - current_y
    # atan2 gives angle from positive X axis, CCW
    # Convert to ESO heading (from North, CW)
    angle = math.atan2(dx, dy)
    if angle < 0:
        angle += 2 * math.pi
    return angle


def angle_difference(current, target):
    """Calculate shortest signed angle difference (radians).

    Positive = turn right, Negative = turn left.
    """
    diff = target - current
    # Normalize to [-pi, pi]
    while diff > math.pi:
        diff -= 2 * math.pi
    while diff < -math.pi:
        diff += 2 * math.pi
    return diff


def distance_2d(x1, y1, x2, y2):
    """2D distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def rotate_camera(angle_diff):
    """Rotate the camera by angle_diff radians using mouse movement.

    Positive = turn right, Negative = turn left.
    """
    pixels = int(angle_diff * MOUSE_SENSITIVITY)
    if abs(pixels) < 1:
        return

    # Move mouse horizontally to rotate camera
    # pydirectinput.moveRel moves the mouse relative to current position
    pydirectinput.moveRel(pixels, 0)
    time.sleep(0.1)


def press_key_hold(key, duration):
    """Hold a key for a duration (seconds)."""
    pydirectinput.keyDown(key)
    time.sleep(duration)
    pydirectinput.keyUp(key)


def move_to_waypoint(target_x, target_y, check_running, on_combat=None,
                     on_stuck=None):
    """Navigate to a target position.

    Args:
        target_x, target_y: Target world coordinates
        check_running: Callable that returns False if bot should stop
        on_combat: Callable when combat is detected (returns True to continue)
        on_stuck: Callable when stuck is detected (returns True to continue)

    Returns:
        True if arrived, False if interrupted
    """
    last_pos = None
    last_move_time = time.time()
    last_combat_check = 0

    while check_running():
        pos = read_player_position()
        if not pos:
            time.sleep(POSITION_READ_INTERVAL)
            continue

        current_x = pos["worldX"]
        current_y = pos["worldY"]
        current_heading = pos.get("heading", 0)

        # Check if arrived
        dist = distance_2d(current_x, current_y, target_x, target_y)
        if dist < ARRIVAL_THRESHOLD:
            pydirectinput.keyUp(KEY_FORWARD)
            return True

        # Check combat
        now = time.time()
        if now - last_combat_check > COMBAT_CHECK_INTERVAL:
            last_combat_check = now
            if pos.get("inCombat", False) and on_combat:
                pydirectinput.keyUp(KEY_FORWARD)
                should_continue = on_combat()
                if not should_continue:
                    return False

        # Check if stuck
        if last_pos:
            moved = distance_2d(
                current_x, current_y, last_pos["worldX"], last_pos["worldY"]
            )
            if moved > STUCK_DISTANCE:
                last_move_time = now
                last_pos = pos
            elif now - last_move_time > STUCK_TIMEOUT:
                pydirectinput.keyUp(KEY_FORWARD)
                if on_stuck:
                    should_continue = on_stuck()
                    if not should_continue:
                        return False
                    last_move_time = now
                else:
                    return False
        else:
            last_pos = pos
            last_move_time = now

        # Calculate desired heading
        target_angle = calculate_angle(current_x, current_y, target_x, target_y)
        turn = angle_difference(current_heading, target_angle)

        # Rotate camera if needed (threshold to avoid jitter)
        if abs(turn) > 0.1:
            pydirectinput.keyUp(KEY_FORWARD)
            rotate_camera(turn)
            time.sleep(0.05)

        # Move forward
        pydirectinput.keyDown(KEY_FORWARD)
        time.sleep(POSITION_READ_INTERVAL)

    # Stopped externally
    pydirectinput.keyUp(KEY_FORWARD)
    return False


def sprint_escape(duration=None):
    """Sprint forward to escape combat.

    Args:
        duration: How long to sprint (default: SPRINT_ESCAPE_DURATION)
    """
    if duration is None:
        duration = SPRINT_ESCAPE_DURATION

    print("[NAV] Sprinting to escape combat!")
    pydirectinput.keyDown(KEY_FORWARD)
    pydirectinput.keyDown(KEY_SPRINT)
    time.sleep(duration + random.uniform(-0.5, 0.5))
    pydirectinput.keyUp(KEY_SPRINT)
    pydirectinput.keyUp(KEY_FORWARD)


def navigate_route(waypoints, check_running, on_arrive_fishing=None,
                   on_combat=None, on_stuck=None, on_waypoint_start=None):
    """Navigate through a list of waypoints.

    Args:
        waypoints: List of dicts with x, y, type ("fishing"/"walk")
        check_running: Callable, returns False to stop
        on_arrive_fishing: Callable(waypoint_index) when arriving at fishing spot
        on_combat: Callable when combat detected, returns True to continue
        on_stuck: Callable when stuck, returns True to continue
        on_waypoint_start: Callable(waypoint_index, waypoint) at start of navigation

    Returns:
        Number of waypoints completed
    """
    completed = 0

    for i, wp in enumerate(waypoints):
        if not check_running():
            break

        if on_waypoint_start:
            on_waypoint_start(i, wp)

        print(f"[NAV] Moving to waypoint #{i+1}/{len(waypoints)} "
              f"({wp['type']}) x={wp['x']:.0f}, y={wp['y']:.0f}")

        arrived = move_to_waypoint(
            wp["x"], wp["y"],
            check_running=check_running,
            on_combat=on_combat,
            on_stuck=on_stuck,
        )

        if not arrived:
            print(f"[NAV] Failed to reach waypoint #{i+1}")
            break

        completed += 1
        print(f"[NAV] Arrived at waypoint #{i+1}")

        if wp["type"] == "fishing" and on_arrive_fishing:
            on_arrive_fishing(i)

    return completed


def load_route(filepath):
    """Load a route from a JSON file.

    Returns dict with zone, waypoints list.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
