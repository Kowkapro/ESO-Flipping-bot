"""
Pixel Bridge fishing bot — navigate by exact coordinates, fish at recorded holes.

Architecture:
  FishingNav addon v2 (pixel blocks) → pixel_bridge.py (decode) → this file (navigate + fish)

Loop:
  1. Read player position via pixel bridge
  2. Go to next hole from route_holes.json (sequential, cyclic)
  3. Rotate camera to face hole (bearing from coordinates)
  4. Sprint to hole, correcting heading every 100ms
  5. Stop when distance < threshold
  6. Try to fish (look around, press E, detect bite)
  7. Move to next hole, repeat

Usage:
  python fishing/main_v5.py

Controls:
  F5 — Start (switch to ESO first!)
  F6 — Stop immediately (releases all keys)
"""

import json
import math
import os
import random
import time

import cv2
import keyboard
import mss
import numpy as np
import pydirectinput
import pyautogui

from pixel_bridge import PlayerState, read_player_state
from main import (
    send_mouse_move,
    human_mouse_arc,
    steer_smooth,
    press_key,
    PIXELS_PER_360,
)

# Disconnect recovery
DISCONNECT_TIMEOUT = 15.0       # seconds of bridge failure → disconnect
DISCONNECT_MAX_RETRIES = 3      # max reconnect attempts before giving up
BTN_VOITI = (960, 490)          # "ВОЙТИ" button (login screen, 1920x1080)
BTN_IGRAT = (960, 1050)         # "ИГРАТЬ" button (character select, 1920x1080)

# Fishing constants (from legacy/fishing_bot.py)
CAST_KEY = 'e'
LOOT_KEY = 'r'
SCAN_INTERVAL = 0.05
MAX_WAIT_FOR_HOOK = 45.0
MAX_FAILED_CASTS = 2
DELAY_AFTER_CAST = (1.0, 2.0)
DELAY_REEL_REACTION = (0.05, 0.2)
DELAY_AFTER_REEL = (1.5, 3.0)
DELAY_AFTER_LOOT = (0.5, 1.5)
DELAY_RECAST = (0.3, 0.8)

# Hook detection
HOOK_WHITE_THRESHOLD = 220
HOOK_WHITE_RATIO = 0.08


# ── Navigation constants ────────────────────────────────────────────
ARRIVAL_DIST = 800          # world units — stop sprinting, start fine positioning
FINE_DIST = 200             # world units — close enough, stop fine positioning
FINE_STEP_DURATION = 0.12   # seconds per WASD tap during fine positioning
FINE_TIMEOUT = 15.0         # max seconds in fine positioning before giving up
COURSE_CORRECTION_INTERVAL = 0.1  # seconds between heading checks
HEADING_DEADZONE = 0.05     # radians (~3°) — don't correct smaller errors
STUCK_TIMEOUT = 3.0         # seconds without movement = stuck
STUCK_MIN_MOVE = 30         # world units — less than this in STUCK_TIMEOUT = stuck
ROUTE_FILE = os.path.join(os.path.dirname(__file__), "route_holes.json")

# Combat
COMBAT_AOE_KEY = '5'           # AoE skill key
COMBAT_INVIS_KEY = '4'         # Invisibility skill key (flee)
COMBAT_MAX_PRESSES = 10        # max AoE presses before fleeing
COMBAT_TIMEOUT = 30.0          # max seconds in combat before giving up

# Stuck recovery escalation — diverse obstacle avoidance
STUCK_PROGRESS_DIST = 300   # must get this much closer to reset recovery level

RECOVERY_ACTIONS = [
    ("jump",          lambda: _do_jumps(3)),
    ("sidestep_L",    lambda: _hold_key_for('a', 2.0)),
    ("sidestep_R",    lambda: _hold_key_for('d', 2.0)),
    ("backtrack",     lambda: _hold_key_for('s', 2.0)),
    ("diagonal_L",    lambda: _diagonal_walk('a', 3.0)),
    ("diagonal_R",    lambda: _diagonal_walk('d', 3.0)),
    ("wide_arc_L",    lambda: _wide_arc('a', 4.0)),
    ("wide_arc_R",    lambda: _wide_arc('d', 4.0)),
    ("random",        lambda: _random_walk(5.0)),
]


def _do_jumps(count):
    for _ in range(count):
        press_key('space')
        time.sleep(random.uniform(0.3, 0.5))


def _hold_key_for(key, duration):
    pydirectinput.keyDown(key)
    time.sleep(duration)
    pydirectinput.keyUp(key)


def _diagonal_walk(side_key, duration):
    """Walk forward + sideways simultaneously to go around obstacle."""
    pydirectinput.keyDown('w')
    pydirectinput.keyDown(side_key)
    time.sleep(duration * random.uniform(0.8, 1.0))
    pydirectinput.keyUp(side_key)
    pydirectinput.keyUp('w')


def _wide_arc(side_key, duration):
    """Sidestep then sprint forward — wide arc around obstacle."""
    pydirectinput.keyDown(side_key)
    time.sleep(duration * 0.4)
    pydirectinput.keyUp(side_key)
    time.sleep(0.1)
    pydirectinput.keyDown('w')
    time.sleep(duration * 0.6)
    pydirectinput.keyUp('w')


def _jump_forward():
    """Jump while walking forward — clears small obstacles."""
    pydirectinput.keyDown('w')
    time.sleep(0.1)
    press_key('space')
    time.sleep(0.5)
    pydirectinput.keyUp('w')


def _random_walk(duration):
    key = random.choice(['w', 'a', 's', 'd'])
    pydirectinput.keyDown(key)
    time.sleep(duration * random.uniform(0.7, 1.0))
    pydirectinput.keyUp(key)


# ── Disconnect recovery ──────────────────────────────────────────────

def handle_disconnect(sct, monitor):
    """Handle ESO disconnect: close error → login → select character → load.

    Flow (from screenshots):
      1. Error popup "ОШИБКА" with [Alt] OK → press Alt
      2. Click "ВОЙТИ" button (center screen) → wait for server load
      3. Click "ИГРАТЬ" button (bottom center) → wait for world load
      4. Wait for pixel bridge to become available
    """
    print("\n" + "!" * 60)
    print("  DISCONNECT DETECTED — starting reconnect...")
    print("!" * 60)

    # Step 1: Close error popup
    print("[RECONNECT] Step 1/4: Closing error popup (Alt)...")
    time.sleep(random.uniform(1.0, 2.0))
    press_key('alt')
    time.sleep(random.uniform(1.5, 2.5))

    # Step 2: Click "ВОЙТИ"
    print("[RECONNECT] Step 2/4: Clicking 'ВОЙТИ'...")
    pyautogui.click(*BTN_VOITI)
    wait = random.uniform(18, 25)
    print(f"[RECONNECT] Waiting {wait:.0f}s for server load...")
    time.sleep(wait)

    # Step 3: Click "ИГРАТЬ"
    print("[RECONNECT] Step 3/4: Clicking 'ИГРАТЬ'...")
    pyautogui.click(*BTN_IGRAT)
    wait = random.uniform(12, 18)
    print(f"[RECONNECT] Waiting {wait:.0f}s for world load...")
    time.sleep(wait)

    # Step 4: Wait for pixel bridge
    print("[RECONNECT] Step 4/4: Waiting for pixel bridge...")
    for i in range(30):
        state = read_player_state(sct, monitor)
        if state:
            print(f"[RECONNECT] SUCCESS! Player at ({state.x:.0f}, {state.y:.0f})")
            return True
        time.sleep(1.0)

    print("[RECONNECT] FAILED — pixel bridge not available after 30s")
    return False


# ── Combat ───────────────────────────────────────────────────────────

def handle_combat(sct, monitor, stop_flag):
    """Spam AoE skill until combat ends. Returns 'killed' | 'fled' | 'timeout'."""
    print(f"[COMBAT] Enemy detected! Spamming AoE (key '{COMBAT_AOE_KEY}')...")
    presses = 0
    start = time.time()
    while not stop_flag[0]:
        if time.time() - start > COMBAT_TIMEOUT:
            print("[COMBAT] Timeout — fleeing")
            _flee_combat()
            return "fled"
        state = read_player_state(sct, monitor)
        if state and not state.in_combat:
            print("[COMBAT] Combat over — enemy killed!")
            return "killed"
        press_key(COMBAT_AOE_KEY)
        presses += 1
        if presses >= COMBAT_MAX_PRESSES:
            print(f"[COMBAT] {presses} AoE presses, mob still alive — fleeing!")
            _flee_combat()
            return "fled"
        time.sleep(random.uniform(0.4, 0.7))
    return "timeout"


def _flee_combat():
    """Press invisibility to disengage. Navigation loop will walk to target."""
    press_key(COMBAT_INVIS_KEY)
    time.sleep(0.3)
    print("[COMBAT] Fled (invis) — walking to target without sprint")


# ── Hook detection (mss-based, replaces ImageGrab) ──────────────────

# Scan regions — set by init_scan_regions()
SCAN_REGION_HOOK = None

def init_scan_regions():
    """Calculate hook scan region based on screen resolution."""
    global SCAN_REGION_HOOK
    screen_w, screen_h = pyautogui.size()
    center_x, center_y = screen_w // 2, screen_h // 2
    hook_size = min(screen_w, screen_h) // 4
    SCAN_REGION_HOOK = (
        center_x - hook_size // 2,
        center_y - hook_size // 2,
        hook_size,
        hook_size,
    )
    print(f"[INFO] Screen: {screen_w}x{screen_h}")
    print(f"[INFO] Hook scan region: {SCAN_REGION_HOOK}")


def detect_hook_mss(sct):
    """Detect white hook icon using mss (no ImageGrab conflict)."""
    x, y, w, h = SCAN_REGION_HOOK
    mon = {"left": x, "top": y, "width": w, "height": h}
    img = sct.grab(mon)
    frame = np.array(img)  # BGRA
    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    white_pixels = np.sum(gray > HOOK_WHITE_THRESHOLD)
    ratio = white_pixels / gray.size
    return ratio > HOOK_WHITE_RATIO


# ── Geometry helpers ─────────────────────────────────────────────────

def distance(x1, y1, x2, y2):
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def bearing_to(from_x, from_y, to_x, to_y):
    """Calculate bearing from one point to another.

    ESO coordinate system (verified from pixel bridge movement data):
    - Heading 0 = North (Y decreasing)
    - Heading increases COUNTER-clockwise (90°=West, 180°=South, 270°=East)
    - Direction vector for heading θ: dx=-sin(θ), dy=-cos(θ)
    - Inverse: θ = atan2(-dx, -dy)
    Returns radians [0, 2*pi).
    """
    dx = to_x - from_x
    dy = to_y - from_y
    angle = math.atan2(-dx, -dy)
    if angle < 0:
        angle += 2 * math.pi
    return angle


def normalize_angle(angle):
    """Normalize angle to [-pi, pi]."""
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def angle_to_mouse_px(angle_rad):
    """Convert a rotation angle (radians) to mouse pixels.

    ESO heading is CCW, but mouse right = CW turn = heading decreases.
    So negate: positive angle (CCW) → negative mouse px (move left).
    """
    return -angle_rad / (2 * math.pi) * PIXELS_PER_360


# ── Route loading ────────────────────────────────────────────────────

def load_route():
    """Load fishing holes from route_holes.json."""
    with open(ROUTE_FILE) as f:
        return json.load(f)


def rotate_to_target(state, target_x, target_y):
    """Rotate camera to face target. Takes one W step to sync character heading."""
    target_bearing = bearing_to(state.x, state.y, target_x, target_y)
    turn = normalize_angle(target_bearing - state.heading)
    mouse_px = int(angle_to_mouse_px(turn))

    if abs(mouse_px) > 10:
        human_mouse_arc(mouse_px)
        time.sleep(0.1)

    # Step forward to sync character heading with camera
    pydirectinput.keyDown('w')
    time.sleep(0.15)
    pydirectinput.keyUp('w')
    time.sleep(0.1)


def navigate_to_hole(hole, sct, monitor, stop_flag):
    """Sprint to a fishing hole using pixel bridge coordinates.

    Returns: "fishing" | "arrived" | "stuck" | "stopped"
    """
    target_x, target_y = hole["x"], hole["y"]

    # Initial rotation
    state = read_player_state(sct, monitor)
    if not state:
        time.sleep(0.5)
        state = read_player_state(sct, monitor)
    if not state:
        print("[NAV] Can't read pixel bridge — is ESO visible?")
        return "stopped"

    dist = distance(state.x, state.y, target_x, target_y)
    target_bearing = bearing_to(state.x, state.y, target_x, target_y)
    turn = normalize_angle(target_bearing - state.heading)
    print(f"[NAV] Player: ({state.x:.0f}, {state.y:.0f}), heading={math.degrees(state.heading):.0f}°")
    print(f"[NAV] Target: ({target_x:.0f}, {target_y:.0f}), dist={dist:.0f}")
    print(f"[NAV] Bearing={math.degrees(target_bearing):.0f}°, turn={math.degrees(turn):.0f}°")

    rotate_to_target(state, target_x, target_y)

    # Start sprinting
    pydirectinput.keyDown('w')
    time.sleep(0.05)
    pydirectinput.keyDown('shift')

    prev_x, prev_y = state.x, state.y
    best_dist = dist              # track best distance for recovery reset
    stuck_timer = 0.0
    recovery_level = 0
    last_time = time.time()
    bridge_fail_start = None      # track consecutive bridge failures

    try:
        while not stop_flag[0]:
            time.sleep(COURSE_CORRECTION_INTERVAL)
            now = time.time()
            dt = now - last_time
            last_time = now

            state = read_player_state(sct, monitor)
            if not state:
                if bridge_fail_start is None:
                    bridge_fail_start = time.time()
                elif time.time() - bridge_fail_start > DISCONNECT_TIMEOUT:
                    return "disconnect"
                continue
            bridge_fail_start = None  # reset on success

            dist = distance(state.x, state.y, target_x, target_y)

            # Combat check — stop sprinting, fight or flee, resume
            if state.in_combat:
                pydirectinput.keyUp('w')
                pydirectinput.keyUp('shift')
                time.sleep(0.1)
                result = handle_combat(sct, monitor, stop_flag)
                if stop_flag[0]:
                    return "stopped"
                # Re-orient and resume sprint
                state = read_player_state(sct, monitor)
                if state:
                    rotate_to_target(state, target_x, target_y)
                pydirectinput.keyDown('w')
                time.sleep(0.05)
                if result == "killed":
                    pydirectinput.keyDown('shift')
                prev_x, prev_y = state.x if state else prev_x, state.y if state else prev_y
                stuck_timer = 0.0
                continue

            # Arrived? — switch to fine positioning
            if dist < ARRIVAL_DIST:
                print(f"[NAV] Arrived! dist={dist:.0f}")
                return "arrived"

            # Course correction
            target_bearing = bearing_to(state.x, state.y, target_x, target_y)
            error = normalize_angle(target_bearing - state.heading)
            if abs(error) > HEADING_DEADZONE:
                correction_px = int(angle_to_mouse_px(error) * 0.7)
                correction_px = max(-2000, min(2000, correction_px))
                steer_smooth(correction_px)

            # Stuck detection
            moved = distance(state.x, state.y, prev_x, prev_y)
            if moved < STUCK_MIN_MOVE:
                stuck_timer += dt
                if stuck_timer >= STUCK_TIMEOUT:
                    if recovery_level < len(RECOVERY_ACTIONS):
                        name, action = RECOVERY_ACTIONS[recovery_level]
                        print(f"[NAV] Stuck! Recovery: {name} (level {recovery_level})")
                        # Stop sprinting for recovery
                        pydirectinput.keyUp('w')
                        pydirectinput.keyUp('shift')
                        time.sleep(0.1)
                        action()
                        time.sleep(0.2)
                        # Re-read position and re-orient
                        state = read_player_state(sct, monitor)
                        if state:
                            rotate_to_target(state, target_x, target_y)
                            prev_x, prev_y = state.x, state.y
                        # Resume sprint
                        pydirectinput.keyDown('w')
                        time.sleep(0.05)
                        pydirectinput.keyDown('shift')
                        recovery_level += 1
                    else:
                        print("[NAV] All recovery failed — skipping hole")
                        return "stuck"
                    stuck_timer = 0.0
            else:
                stuck_timer = 0.0
                prev_x, prev_y = state.x, state.y
                # Only reset recovery level if we made real progress toward target
                if dist < (best_dist - STUCK_PROGRESS_DIST):
                    recovery_level = 0
                    best_dist = dist

            # Log periodically
            if random.random() < 0.1:
                print(f"  dist={dist:.0f} heading={math.degrees(state.heading):.0f}° "
                      f"error={math.degrees(error):.1f}°")

    finally:
        pydirectinput.keyUp('w')
        time.sleep(0.05)
        pydirectinput.keyUp('shift')

    return "stopped"


# ── Fine positioning ─────────────────────────────────────────────────

def fine_position(target_x, target_y, sct, monitor, stop_flag):
    """Walk to exact target coordinates using small WASD taps.

    After sprinting gets us within ARRIVAL_DIST, this function uses
    short key taps to position precisely on the recorded coordinates.

    Returns: True if positioned within FINE_DIST, False if timeout/stopped.
    """
    FINE_RECOVERY = [
        ("jump_fwd",    lambda: _jump_forward()),
        ("back+jump",   lambda: (_hold_key_for('s', 1.0), _jump_forward())),
        ("sidestep_L",  lambda: _diagonal_walk('a', 1.5)),
        ("jump_L",      lambda: (_hold_key_for('a', 0.5), _jump_forward())),
        ("back_R",      lambda: (_hold_key_for('s', 0.8), _hold_key_for('d', 1.0))),
        ("sidestep_R",  lambda: _diagonal_walk('d', 1.5)),
        ("jump_R",      lambda: (_hold_key_for('d', 0.5), _jump_forward())),
        ("back_L",      lambda: (_hold_key_for('s', 0.8), _hold_key_for('a', 1.0))),
        ("wide_L",      lambda: (_hold_key_for('s', 1.5), _diagonal_walk('a', 2.0))),
        ("wide_R",      lambda: (_hold_key_for('s', 1.5), _diagonal_walk('d', 2.0))),
        ("back+jump_L", lambda: (_hold_key_for('s', 1.0), _hold_key_for('a', 0.5), _jump_forward())),
        ("back+jump_R", lambda: (_hold_key_for('s', 1.0), _hold_key_for('d', 0.5), _jump_forward())),
    ]

    print(f"[FINE] Fine positioning to ({target_x:.0f}, {target_y:.0f})...")
    prev_dist = float('inf')
    no_progress_count = 0
    recovery_idx = 0

    while not stop_flag[0]:
        state = read_player_state(sct, monitor)
        if not state:
            time.sleep(0.2)
            continue

        dist = distance(state.x, state.y, target_x, target_y)
        if dist < FINE_DIST:
            print(f"[FINE] Positioned! dist={dist:.0f}")
            return True

        # Stuck detection — cycle through recovery actions, never give up
        if dist >= prev_dist - 20:
            no_progress_count += 1
            if no_progress_count >= 3:
                name, action = FINE_RECOVERY[recovery_idx % len(FINE_RECOVERY)]
                print(f"[FINE] Stuck at dist={dist:.0f} — {name}")
                action()
                time.sleep(0.2)
                recovery_idx += 1
                no_progress_count = 0
                prev_dist = float('inf')
                continue
        else:
            no_progress_count = 0
            if dist < prev_dist - 50:
                recovery_idx = 0  # making progress, reset recovery
        prev_dist = dist

        # Turn to face target
        target_bearing = bearing_to(state.x, state.y, target_x, target_y)
        turn = normalize_angle(target_bearing - state.heading)
        mouse_px = int(angle_to_mouse_px(turn))

        if abs(mouse_px) > 10:
            steer_smooth(int(mouse_px * 0.7))
            time.sleep(0.1)

        # Small step forward (W tap) — shorter step when closer
        step_dur = FINE_STEP_DURATION * min(1.0, dist / ARRIVAL_DIST)
        step_dur = max(0.05, step_dur)
        pydirectinput.keyDown('w')
        time.sleep(step_dur)
        pydirectinput.keyUp('w')
        time.sleep(0.15)

        # Log
        if random.random() < 0.3:
            print(f"  [FINE] dist={dist:.0f}, step={step_dur:.2f}s")

    return False


# ── Fishing (adapted from legacy/fishing_bot.py) ────────────────────

def fish_one_hole(sct, monitor, stop_flag):
    """Fish at current hole until depleted or stopped.

    Returns: (fish_caught, casts_made)
    """
    print()
    print("=" * 40)
    print("  FISHING!")
    print("=" * 40)
    print()

    fish_caught = 0
    casts_made = 0
    failed_casts = 0

    while not stop_flag[0]:
        casts_made += 1
        print(f"  [Cast {casts_made}] Casting line...")
        press_key(CAST_KEY)
        time.sleep(random.uniform(*DELAY_AFTER_CAST))

        # Wait for hook icon (white flash)
        print(f"  [Cast {casts_made}] Waiting for bite...")
        hook_start = time.time()
        got_bite = False

        while not stop_flag[0]:
            if time.time() - hook_start > MAX_WAIT_FOR_HOOK:
                break
            if detect_hook_mss(sct):
                got_bite = True
                break
            time.sleep(SCAN_INTERVAL)

        if stop_flag[0]:
            break

        if not got_bite:
            failed_casts += 1
            print(f"  [Cast {casts_made}] No bite! (failed: {failed_casts}/{MAX_FAILED_CASTS})")
            if failed_casts >= MAX_FAILED_CASTS:
                print(f"\n[FISH] Hole depleted! Fish: {fish_caught}, Casts: {casts_made}")
                break
            time.sleep(random.uniform(*DELAY_RECAST))
            continue

        # Got a bite — reel in
        failed_casts = 0
        time.sleep(random.uniform(*DELAY_REEL_REACTION))
        print(f"  [Cast {casts_made}] BITE! Reeling in...")
        press_key(CAST_KEY)

        # Wait for loot
        time.sleep(random.uniform(*DELAY_AFTER_REEL))

        # Loot
        fish_caught += 1
        print(f"  [Cast {casts_made}] Fish #{fish_caught}! Looting...")
        press_key(LOOT_KEY)
        time.sleep(0.3)
        press_key(LOOT_KEY)
        time.sleep(random.uniform(*DELAY_AFTER_LOOT))

        # Check if hole is depleted (fishing prompt disappeared)
        state = read_player_state(sct, monitor)
        if state and not state.is_fishing:
            print(f"\n[FISH] Hole depleted! Fish: {fish_caught}, Casts: {casts_made}")
            break

    return fish_caught, casts_made


LOOK_STEPS = 12           # 360° / 12 = 30° per step
LOOK_STEP_PX = int(PIXELS_PER_360 / LOOK_STEPS)


def look_for_fishing_hole(sct, monitor, stop_flag):
    """Rotate 360° in 30° steps, checking is_fishing flag via pixel bridge.

    When addon detects reticle on fishing hole (GetInteractionType == INTERACTION_FISH),
    the is_fishing flag goes True. This works when standing close to the hole.

    Returns: True if fishing interaction found, False otherwise.
    """
    print("[LOOK] Scanning for fishing hole (360° rotation)...")

    for step in range(LOOK_STEPS):
        if stop_flag[0]:
            return False

        # Check flag
        state = read_player_state(sct, monitor)
        if state and state.is_fishing:
            print(f"[LOOK] Found fishing hole at step {step + 1}!")
            return True

        # Turn 30°
        human_mouse_arc(LOOK_STEP_PX)
        time.sleep(0.3)

    print("[LOOK] Full rotation — no fishing hole found")
    return False


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  FISHING BOT v5 — Pixel Bridge + Route Navigation")
    print("  Sequential route → arrive → fish → next hole (cyclic)")
    print("=" * 60)
    print("  F5 — Start (switch to ESO first!)")
    print("  F6 — Stop immediately")
    print("=" * 60)

    # Load route
    print("\n[INIT] Loading route...")
    holes = load_route()
    if not holes:
        print(f"[ERROR] No holes in {ROUTE_FILE}!")
        return
    print(f"[INIT] {len(holes)} fishing holes loaded")

    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    print(f"[INIT] Screen: {screen_w}x{screen_h}")

    # Init hook scan region
    init_scan_regions()

    # Test pixel bridge
    print("[INIT] Testing pixel bridge...")
    state = read_player_state(sct, monitor)
    if state:
        print(f"[INIT] Player at ({state.x:.0f}, {state.y:.0f}), "
              f"heading={math.degrees(state.heading):.1f}°")
    else:
        print("[WARN] Pixel bridge not detected — make sure ESO is visible!")

    print("\nPress F5 when ESO is focused...\n")

    stop_flag = [False]

    def on_f6():
        stop_flag[0] = True
        print("\n[F6] STOP!")

    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)
    keyboard.wait("f5")
    time.sleep(0.5)

    # ── Find nearest hole to start from ──
    state = read_player_state(sct, monitor)
    if state:
        best_idx = 0
        best_dist = float('inf')
        for i, h in enumerate(holes):
            d = distance(state.x, state.y, h["x"], h["y"])
            if d < best_dist:
                best_dist = d
                best_idx = i
        print(f"[INIT] Starting from hole {best_idx + 1}/{len(holes)} "
              f"(nearest, dist={best_dist:.0f})")
    else:
        best_idx = 0
        print("[INIT] Starting from hole 1 (no pixel bridge)")

    # ── Main loop ──
    total_fish = 0
    total_casts = 0
    fished_count = 0
    skipped_count = 0
    reconnect_count = 0
    lap = 1
    idx = best_idx
    bridge_fail_start = None      # track bridge failures in main loop

    while not stop_flag[0]:
        hole = holes[idx]
        hole_label = f"Lap {lap}, Hole {idx + 1}/{len(holes)}"
        print()
        print("#" * 60)
        print(f"  {hole_label}")
        print("#" * 60)

        # Read current position
        state = read_player_state(sct, monitor)
        if not state:
            # Track bridge failures for disconnect detection
            if bridge_fail_start is None:
                bridge_fail_start = time.time()
                print("[WAIT] Pixel bridge not available, waiting...")
            elif time.time() - bridge_fail_start > DISCONNECT_TIMEOUT:
                # Disconnect detected — attempt reconnect
                bridge_fail_start = None
                ok = False
                for attempt in range(1, DISCONNECT_MAX_RETRIES + 1):
                    print(f"[RECONNECT] Attempt {attempt}/{DISCONNECT_MAX_RETRIES}")
                    if handle_disconnect(sct, monitor):
                        ok = True
                        reconnect_count += 1
                        break
                    print(f"[RECONNECT] Attempt {attempt} failed, retrying...")
                if not ok:
                    print("[RECONNECT] All attempts failed — stopping bot")
                    break
                continue  # re-read state and resume from current hole
            time.sleep(1.0)
            continue
        bridge_fail_start = None  # reset on success

        dist = distance(state.x, state.y, hole["x"], hole["y"])
        print(f"[HOLE] Target: ({hole['x']}, {hole['y']}), dist={dist:.0f}")

        if stop_flag[0]:
            break

        # Navigate to hole
        result = navigate_to_hole(hole, sct, monitor, stop_flag)
        print(f"[NAV RESULT] {result}")

        if stop_flag[0]:
            break

        # Handle disconnect during navigation
        if result == "disconnect":
            bridge_fail_start = time.time() - DISCONNECT_TIMEOUT  # trigger reconnect on next iteration
            continue

        # Handle result
        if result == "arrived":
            # Fine positioning — walk precisely to recorded coordinates
            time.sleep(random.uniform(0.2, 0.4))
            fine_position(hole["x"], hole["y"], sct, monitor, stop_flag)

            if stop_flag[0]:
                break

            # Now look for fishing prompt
            time.sleep(random.uniform(0.3, 0.5))
            found = look_for_fishing_hole(sct, monitor, stop_flag)
            if found and not stop_flag[0]:
                time.sleep(random.uniform(0.3, 0.5))
                fish, casts = fish_one_hole(sct, monitor, stop_flag)
                total_fish += fish
                total_casts += casts
                fished_count += 1
                print(f"[DONE] {hole_label}: caught {fish} fish")
            else:
                skipped_count += 1
                print(f"[SKIP] {hole_label} — no fishing hole found")

        elif result == "stuck":
            skipped_count += 1
            print(f"[SKIP] {hole_label} — stuck")

        else:
            skipped_count += 1
            print(f"[SKIP] {hole_label} — {result}")

        # Next hole (cyclic)
        idx = (idx + 1) % len(holes)
        if idx == best_idx:
            print(f"\n[LAP] Lap {lap} complete!")
            lap += 1

        # Human-like delay between holes
        time.sleep(random.uniform(0.5, 1.5))

    # ── Summary ──
    print()
    print("=" * 60)
    print("  SESSION COMPLETE!")
    print(f"  Laps: {lap}")
    print(f"  Holes visited: {fished_count + skipped_count}")
    print(f"  Fished:  {fished_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Total fish caught: {total_fish}")
    print(f"  Total casts: {total_casts}")
    print(f"  Reconnects: {reconnect_count}")
    print("=" * 60)

    keyboard.unhook_all()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('shift')
        except Exception:
            pass
        input("\nPress Enter to exit...")
