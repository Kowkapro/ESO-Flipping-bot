"""
Navigation module for ESO Fishing Bot.

Handles movement between waypoints using:
- FishingNav Lua addon for player position/heading (via SavedVariables)
- pydirectinput for WASD movement and mouse rotation
- "Blind navigation" via /reloadui for Phase 3 dynamic mode

Coordinate system:
  ESO uses GetUnitRawWorldPosition which returns worldX, worldZ, worldY
  Our FishingNav addon saves worldX, worldY, worldZ (already swapped)
  Heading from GetMapPlayerPosition is in radians, 0 = North, increases clockwise
"""

import ctypes
import json
import math
import os
import random
import re
import time

import pydirectinput

# ─── Paths ────────────────────────────────────────────────────────
SAVED_VARS_DIR = os.path.join(
    "d:", os.sep, "Documents", "Elder Scrolls Online", "live", "SavedVariables"
)
FISHINGNAV_FILE = os.path.join(SAVED_VARS_DIR, "FishingNav.lua")

# ─── Movement settings ───────────────────────────────────────────
ARRIVAL_THRESHOLD = 15.0       # Distance (world units) to consider "arrived"
POSITION_READ_INTERVAL = 0.2   # How often to read position while moving (seconds)
STUCK_TIMEOUT = 10.0           # Seconds without movement before declaring stuck
STUCK_DISTANCE = 2.0           # Min distance to move in STUCK_TIMEOUT to not be stuck
SPRINT_ESCAPE_DURATION = 5.0   # Seconds to sprint when fleeing from combat
COMBAT_CHECK_INTERVAL = 1.0    # How often to check combat state while moving

# Mouse sensitivity for rotation (pixels per radian)
# Needs calibration — depends on ESO mouse sensitivity settings
MOUSE_SENSITIVITY = 400.0

# Blind navigation constants (Phase 3)
SPRINT_SPEED = 550.0           # World units per second while sprinting (needs calibration)
WALK_SPEED = 250.0             # World units per second while walking
MAX_BLIND_MOVE_SEC = 10.0      # Max duration for a single blind movement segment
RELOADUI_WAIT = 8.0            # Seconds to wait after /reloadui for game to reload

# Movement keys
KEY_FORWARD = 'w'
KEY_SPRINT = 'shift'


# ─── Position reading (SavedVariables) ───────────────────────────

def read_player_position():
    """Read current player position from FishingNav SavedVariables.

    Returns dict with worldX, worldY, worldZ, heading, zoneName, inCombat
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


def get_file_mtime():
    """Get modification timestamp of FishingNav SavedVariables file."""
    try:
        return os.path.getmtime(FISHINGNAV_FILE)
    except OSError:
        return 0


def force_reloadui_and_read(timeout=15.0):
    """Send /reloadui to ESO and wait for SavedVariables to update.

    This forces ESO to flush all SavedVariables to disk, giving us
    fresh player coordinates. Takes ~5-8 seconds.

    Returns updated position dict or None on timeout.
    """
    mtime_before = get_file_mtime()

    # Switch to English keyboard layout before typing
    EN_US = 0x0409
    ctypes.windll.user32.PostMessageW(
        ctypes.windll.user32.GetForegroundWindow(),
        0x0050,  # WM_INPUTLANGCHANGEREQUEST
        0,
        EN_US,
    )
    time.sleep(0.15)

    # Type /reloadui in ESO chat
    pydirectinput.press('enter')
    time.sleep(0.2)
    pydirectinput.typewrite('/reloadui', interval=0.03)
    time.sleep(0.1)
    pydirectinput.press('enter')

    # Wait for file to update (reloadui saves then reloads UI)
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.5)
        if get_file_mtime() > mtime_before:
            time.sleep(0.3)  # Extra wait for write to complete
            return read_player_position()

    return None


# ─── Geometry helpers ─────────────────────────────────────────────

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
    while diff > math.pi:
        diff -= 2 * math.pi
    while diff < -math.pi:
        diff += 2 * math.pi
    return diff


def distance_2d(x1, y1, x2, y2):
    """2D distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# ─── Camera / movement ───────────────────────────────────────────

def rotate_camera(angle_diff):
    """Rotate the camera by angle_diff radians using mouse movement.

    Positive = turn right, Negative = turn left.
    """
    pixels = int(angle_diff * MOUSE_SENSITIVITY)
    if abs(pixels) < 1:
        return

    pydirectinput.moveRel(pixels, 0)
    time.sleep(0.1)


def press_key_hold(key, duration):
    """Hold a key for a duration (seconds)."""
    pydirectinput.keyDown(key)
    time.sleep(duration)
    pydirectinput.keyUp(key)


def move_blind_segment(target_x, target_y, current_pos, sprint=True):
    """Rotate toward target and sprint/walk blind for calculated duration.

    This is used for Phase 3 "blind navigation" where we can't read
    position in real-time. We calculate bearing and distance, then
    move for distance/speed seconds.

    Args:
        target_x, target_y: Target world coordinates
        current_pos: Dict with worldX, worldY, heading
        sprint: Whether to sprint (True) or walk (False)

    Returns:
        Estimated duration of movement in seconds
    """
    cx = current_pos["worldX"]
    cy = current_pos["worldY"]
    heading = current_pos.get("heading", 0)

    dist = distance_2d(cx, cy, target_x, target_y)
    if dist < ARRIVAL_THRESHOLD:
        return 0.0

    # Rotate toward target
    target_angle = calculate_angle(cx, cy, target_x, target_y)
    turn = angle_difference(heading, target_angle)
    if abs(turn) > 0.05:
        rotate_camera(turn)
        time.sleep(0.15)

    # Calculate move duration
    speed = SPRINT_SPEED if sprint else WALK_SPEED
    duration = dist / speed
    duration = min(duration, MAX_BLIND_MOVE_SEC)
    # Add slight randomness for human-like behavior
    duration += random.uniform(-0.1, 0.2)
    duration = max(0.3, duration)

    # Move forward (sprint if requested)
    if sprint:
        pydirectinput.keyDown(KEY_SPRINT)
        time.sleep(0.05)

    pydirectinput.keyDown(KEY_FORWARD)
    time.sleep(duration)
    pydirectinput.keyUp(KEY_FORWARD)

    if sprint:
        pydirectinput.keyUp(KEY_SPRINT)

    time.sleep(0.1)
    return duration


# ─── Route-based navigation (Phase 2 — kept for compatibility) ───

def move_to_waypoint(target_x, target_y, check_running, on_combat=None,
                     on_stuck=None):
    """Navigate to a target position using real-time position reading.

    Note: This relies on FishingNav addon updating position in real-time
    via SavedVariables. For Phase 3, use move_blind_segment() instead.

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
