"""
Full fishing cycle — open map each time, pick nearest unvisited hook.

Loop:
1. Open map, zoom, YOLO scan for red_hooks
2. Pick nearest unvisited hook to player (center of map)
3. Set waypoint → turn → sprint → detect arrival
4. Fish if hole spawned, skip if not
5. Repeat until no more hooks or F6

Usage:
  python fishing/main.py

Controls:
  F5 — Run (switch to ESO first!)
  F6 — Stop immediately (releases all keys)
"""

import ctypes
import ctypes.wintypes
import math
import os
import random
import sys
import time

import easyocr
import keyboard
import mss
import cv2
import numpy as np
import pyautogui
import pydirectinput
from ultralytics import YOLO


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
    """Send raw mouse move via Win32 SendInput."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = 0
    inp.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.mi.time = 0
    inp.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def human_mouse_arc(total_dx):
    """Move mouse smoothly — no jerks, like dragging with your hand."""
    abs_dx = abs(total_dx)
    if abs_dx == 0:
        return

    sign = 1 if total_dx > 0 else -1
    duration = 0.05 + (abs_dx / 5000) * 0.15
    duration *= random.uniform(0.9, 1.1)
    arc_height = random.uniform(2, 6) * random.choice([-1, 1])

    tick = 0.002
    elapsed = 0.0
    moved_x = 0
    prev_y = 0

    while elapsed < duration:
        t = elapsed / duration
        progress = (1 - math.cos(t * math.pi)) / 2
        target_x = int(abs_dx * progress)
        dx = target_x - moved_x
        cur_y = int(arc_height * math.sin(t * math.pi))
        dy = cur_y - prev_y

        if dx != 0 or dy != 0:
            send_mouse_move(sign * dx, dy)
            moved_x = target_x
            prev_y = cur_y

        time.sleep(tick)
        elapsed += tick

    remaining = abs_dx - moved_x
    if remaining > 0:
        send_mouse_move(sign * remaining, -prev_y)


def steer_smooth(total_dx):
    """Lightweight steering correction while running."""
    abs_dx = abs(total_dx)
    if abs_dx == 0:
        return

    sign = 1 if total_dx > 0 else -1
    duration = 0.04 + (abs_dx / 3000) * 0.10
    tick = 0.002
    elapsed = 0.0
    moved_x = 0

    while elapsed < duration:
        t = elapsed / duration
        progress = (1 - math.cos(t * math.pi)) / 2
        target_x = int(abs_dx * progress)
        dx = target_x - moved_x
        if dx != 0:
            send_mouse_move(sign * dx, random.randint(-1, 1))
            moved_x = target_x
        time.sleep(tick)
        elapsed += tick

    remaining = abs_dx - moved_x
    if remaining > 0:
        send_mouse_move(sign * remaining, 0)


# ── Settings ──────────────────────────────────────────────────────────
# Map / waypoint
MAP_ZOOM_CLICKS = 10
ZOOM_PLUS_REL = (0.659, 0.963)
WAYPOINT_KEY = 'f'
HOOK_MIN_CONF = 0.2
HOOK_DEDUP_DIST = 30       # px — hooks closer than this are duplicates

# Visited hook tracking
JUST_FISHED_RADIUS = 80     # px — hooks closer than this to center = just fished, skip
DIRECTION_BONUS_WEIGHT = 0.4  # how much to favor forward direction (0=ignore, 1=strong)

# Mouse calibration (800 DPI, ESO look speed 15)
PIXELS_PER_360 = 9300
PIXELS_PER_DEGREE = PIXELS_PER_360 / 360

# Compass alignment (Phase B — initial turn)
MARKER_MIN_CONF = 0.3
SCREEN_TO_MOUSE = (PIXELS_PER_360 / 2) / 1920
STEER_DAMPING = 0.9
STEER_MAX_PX = 5000
DEAD_ZONE_FRAC = 0.02
MAX_ALIGN_ATTEMPTS = 20
ALIGN_PAUSE = 0.08

# Running (Phase C)
RUN_STEER_DAMPING = 0.7
RUN_STEER_MAX_PX = 1500
RUN_DEAD_ZONE_FRAC = 0.03
RUN_MAX_DURATION = 60.0
RUN_DETECT_INTERVAL = 0.15
MARKER_LOST_THRESHOLD = 4
MARKER_JUMP_THRESHOLD = 250  # px — if marker offset jumps this much in 1 frame, we passed through

# Stuck detection
STUCK_CHECK_INTERVAL = 2.0
STUCK_MIN_CHANGE_PX = 15
STUCK_JUMP_COUNT = 3

# Circling detection — marker keeps flipping sides = we're orbiting the waypoint
CIRCLING_FLIP_THRESHOLD = 4   # sign changes in last N offsets = circling
CIRCLING_HISTORY_SIZE = 8     # track last N offsets

# Fishing (Phase D)
CAST_KEY = 'e'
LOOT_KEY = 'r'
HOOK_WHITE_THRESHOLD = 220
HOOK_WHITE_RATIO = 0.08
SCAN_INTERVAL = 0.05
MAX_WAIT_FOR_HOOK = 45.0
MAX_FAILED_CASTS = 2
DELAY_AFTER_CAST = (1.0, 2.0)
DELAY_REEL_REACTION = (0.05, 0.2)
DELAY_AFTER_REEL = (1.5, 3.0)
DELAY_AFTER_LOOT = (0.5, 1.5)
DELAY_RECAST = (0.3, 0.8)

# Interaction prompt detection (YOLO + OCR)
INTERACTION_MIN_CONF = 0.3
BUBBLES_MIN_CONF = 0.3
FISHING_KEYWORDS = ["рыбалк", "ловл", "fishing", "рыбн"]  # substrings that indicate fishing hole

# Arrival look-around (Phase C end)
LOOKAROUND_TURN_DEG = 90       # degrees per turn step
LOOKAROUND_STEPS = 4           # 4 × 90° = full 360°
LOOKAROUND_PAUSE = 0.4         # pause after each turn to let YOLO scan


def press_key(key):
    """Press a key via DirectInput with human-like hold time."""
    hold_time = random.uniform(0.04, 0.12)
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


def yolo_detect(model, sct, monitor):
    """Grab screen and run YOLO detection."""
    screenshot = sct.grab(monitor)
    frame = np.array(screenshot)
    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    results = model(frame_bgr, imgsz=1280, conf=0.2, verbose=False)

    detections = []
    if results[0].boxes is not None:
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            cls_id = int(box.cls[0])
            detections.append({
                "class": model.names[cls_id],
                "conf": float(box.conf[0]),
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "cx": float((x1 + x2) / 2),
                "cy": float((y1 + y2) / 2),
            })
    return detections


def has_interaction_prompt(detections):
    """Check if YOLO detections contain interaction_prompt with sufficient confidence."""
    return any(
        d["class"] == "interaction_prompt" and d["conf"] >= INTERACTION_MIN_CONF
        for d in detections
    )


def has_bubbles(detections):
    """Check if YOLO detections contain bubbles (fishing hole splash)."""
    return any(
        d["class"] == "bubbles" and d["conf"] >= BUBBLES_MIN_CONF
        for d in detections
    )


def has_fishing_hole(detections):
    """Check if YOLO detections contain interaction_prompt OR bubbles."""
    return has_interaction_prompt(detections) or has_bubbles(detections)


def is_fishing_prompt(ocr_reader, detections, sct, monitor):
    """Check if any interaction_prompt contains fishing-related text via OCR.

    Returns True only if YOLO sees interaction_prompt AND OCR reads fishing keywords.
    Returns False for wayshrines, NPCs, doors, etc.
    """
    prompts = [d for d in detections
               if d["class"] == "interaction_prompt" and d["conf"] >= INTERACTION_MIN_CONF]
    if not prompts:
        return False

    prompt = max(prompts, key=lambda d: d["conf"])

    # Crop the prompt region from screen
    pad = 10
    x1 = max(0, int(prompt["x1"]) - pad)
    y1 = max(0, int(prompt["y1"]) - pad)
    x2 = int(prompt["x2"]) + pad
    y2 = int(prompt["y2"]) + pad

    region = {
        "left": monitor["left"] + x1,
        "top": monitor["top"] + y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }
    screenshot = sct.grab(region)
    crop = np.array(screenshot)
    crop_bgr = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)

    results = ocr_reader.readtext(crop_bgr, detail=0)
    text = " ".join(results).lower()
    is_fishing = any(kw in text for kw in FISHING_KEYWORDS)
    print(f"[OCR] \"{' '.join(results)}\" → {'FISHING' if is_fishing else 'skip'}")
    return is_fishing


def detect_hook_bite(sct, monitor, screen_w, screen_h):
    """Detect white hook icon in center of screen (Votan's Fisherman addon)."""
    try:
        center_x, center_y = screen_w // 2, screen_h // 2
        hook_size = min(screen_w, screen_h) // 4
        x = (center_x - hook_size // 2) + monitor["left"]
        y = (center_y - hook_size // 2) + monitor["top"]

        region = {"left": x, "top": y, "width": hook_size, "height": hook_size}
        screenshot = sct.grab(region)
        frame = np.array(screenshot)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

        white_pixels = np.sum(gray > HOOK_WHITE_THRESHOLD)
        ratio = white_pixels / gray.size
        return ratio > HOOK_WHITE_RATIO
    except Exception as e:
        print(f"[WARN] detect_hook_bite error: {e}")
        return False


def look_around_for_hole(model, ocr_reader, sct, monitor, stop_flag):
    """Stop and look around 360° searching for bubbles or interaction_prompt.

    Returns: "interaction" if found, "no_spawn" if nothing after full rotation.
    """
    print("[LOOK] Stopping and looking around for fishing hole...")

    for step in range(LOOKAROUND_STEPS):
        if stop_flag[0]:
            return "no_spawn"

        # YOLO scan at current view
        detections = yolo_detect(model, sct, monitor)

        if has_interaction_prompt(detections):
            if is_fishing_prompt(ocr_reader, detections, sct, monitor):
                print(f"[LOOK] Fishing prompt confirmed at step {step+1}!")
                return "interaction"
            else:
                print(f"[LOOK] Non-fishing prompt at step {step+1}, skipping...")

        if has_bubbles(detections):
            print(f"[LOOK] bubbles found at step {step+1}! Walking toward them...")
            # Walk forward briefly toward the bubbles, then check for prompt
            pydirectinput.keyDown('w')
            time.sleep(random.uniform(0.8, 1.5))
            pydirectinput.keyUp('w')
            time.sleep(0.3)

            recheck = yolo_detect(model, sct, monitor)
            if has_interaction_prompt(recheck) and is_fishing_prompt(ocr_reader, recheck, sct, monitor):
                print("[LOOK] Fishing prompt found after walking to bubbles!")
                return "interaction"
            # Even if no prompt, bubbles = hole exists, try pressing E
            print("[LOOK] bubbles visible, trying to interact...")
            return "interaction"

        if step < LOOKAROUND_STEPS - 1:
            # Turn ~90° to look in next direction
            turn_px = int(LOOKAROUND_TURN_DEG * PIXELS_PER_DEGREE)
            print(f"[LOOK] Step {step+1}/{LOOKAROUND_STEPS} — nothing, turning {LOOKAROUND_TURN_DEG}°...")
            human_mouse_arc(turn_px)
            time.sleep(LOOKAROUND_PAUSE)
            # Take a small step so character faces camera direction
            pydirectinput.keyDown('w')
            time.sleep(0.1)
            pydirectinput.keyUp('w')
            time.sleep(0.2)

    print("[LOOK] Full rotation — no fishing hole found")
    return "no_spawn"


def open_map_and_zoom(screen_w, screen_h):
    """Open map and zoom in. Returns (zoom_x, zoom_y)."""
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))
    zoom_x = int(screen_w * ZOOM_PLUS_REL[0])
    zoom_y = int(screen_h * ZOOM_PLUS_REL[1])
    for _ in range(MAP_ZOOM_CLICKS):
        pyautogui.click(zoom_x, zoom_y)
        time.sleep(random.uniform(0.05, 0.10))
    time.sleep(random.uniform(0.3, 0.5))
    return zoom_x, zoom_y


# ── Pick nearest unvisited hook and set waypoint ─────────────────────

def deduplicate_hooks(hooks, min_dist=HOOK_DEDUP_DIST):
    """Remove duplicate hooks within a single YOLO scan (proximity-based)."""
    unique = []
    for h in hooks:
        is_dup = any(
            abs(u["cx"] - h["cx"]) < min_dist and abs(u["cy"] - h["cy"]) < min_dist
            for u in unique
        )
        if not is_dup:
            unique.append(h)
    return unique


def multi_frame_detect(model, sct, monitor, n_frames=3, delay=0.3):
    """Aggregate detections across multiple frames to reduce flickering misses."""
    all_detections = []
    for i in range(n_frames):
        dets = yolo_detect(model, sct, monitor)
        all_detections.extend(dets)
        if i < n_frames - 1:
            time.sleep(delay)

    # Deduplicate: group nearby detections of same class, keep highest conf
    merged = []
    for d in sorted(all_detections, key=lambda x: x["conf"], reverse=True):
        is_dup = any(
            m["class"] == d["class"]
            and abs(m["cx"] - d["cx"]) < HOOK_DEDUP_DIST
            and abs(m["cy"] - d["cy"]) < HOOK_DEDUP_DIST
            for m in merged
        )
        if not is_dup:
            merged.append(d)
    return merged


def save_debug_map(frame_bgr, hooks, picked, center_x, center_y, hook_num):
    """Save annotated map screenshot showing all hooks, distances, and selection."""
    debug = frame_bgr.copy()
    # Draw player center crosshair
    cv2.drawMarker(debug, (center_x, center_y), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
    cv2.putText(debug, "PLAYER", (center_x + 15, center_y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    for i, h in enumerate(hooks):
        hx, hy = int(h["cx"]), int(h["cy"])
        dist = ((hx - center_x)**2 + (hy - center_y)**2) ** 0.5
        is_picked = (h is picked)
        color = (0, 255, 255) if is_picked else (0, 0, 255)  # yellow=picked, red=other
        thickness = 3 if is_picked else 1

        # Line from player to hook
        cv2.line(debug, (center_x, center_y), (hx, hy), color, thickness)
        # Circle on hook
        cv2.circle(debug, (hx, hy), 12, color, thickness)
        # Label
        label = f"#{i+1} d={dist:.0f} c={h['conf']:.2f}"
        if is_picked:
            label = f">>> {label} <<<"
        cv2.putText(debug, label, (hx + 15, hy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    path = os.path.join(os.path.dirname(__file__), f"debug_map_hook{hook_num}.png")
    cv2.imwrite(path, debug)
    print(f"[DEBUG] Map saved: {path}")


def pick_and_set_waypoint(model, sct, monitor, screen_w, screen_h, last_direction):
    """Open map, YOLO scan, pick nearest hook.

    Uses screen center as player position (ESO map always centers on player).
    On first hook (last_direction=None): no filtering, pick pure nearest.
    On subsequent hooks: skip hooks within JUST_FISHED_RADIUS of center
    (player is standing at the just-fished hole).
    Multi-frame scan (3 frames) to catch flickering detections.
    """
    screen_cx = screen_w // 2
    screen_cy = screen_h // 2
    is_first_hook = last_direction is None

    print("\n[WP] Opening map to find next hook...")
    open_map_and_zoom(screen_w, screen_h)

    # Multi-frame YOLO scan (3 frames to reduce flicker misses)
    detections = multi_frame_detect(model, sct, monitor, n_frames=3, delay=0.3)

    # Grab last frame for debug screenshot
    debug_screenshot = sct.grab(monitor)
    debug_frame = np.array(debug_screenshot)
    debug_frame_bgr = cv2.cvtColor(debug_frame, cv2.COLOR_BGRA2BGR)

    hooks = [
        d for d in detections
        if d["class"] == "red_hook" and d["conf"] >= HOOK_MIN_CONF
    ]

    print(f"[WP] YOLO: {len(hooks)} red_hook total (3-frame merge)")

    # Only filter near-center hooks on hook 2+ (skip just-fished hole)
    if not is_first_hook:
        before = len(hooks)
        hooks = [h for h in hooks
                 if ((h["cx"] - screen_cx)**2 + (h["cy"] - screen_cy)**2) ** 0.5 > JUST_FISHED_RADIUS]
        filtered = before - len(hooks)
        if filtered:
            print(f"[WP] Filtered {filtered} hooks within {JUST_FISHED_RADIUS}px of center (just-fished)")

    for i, h in enumerate(sorted(hooks, key=lambda h: h["conf"], reverse=True)):
        dist = ((h["cx"] - screen_cx)**2 + (h["cy"] - screen_cy)**2) ** 0.5
        print(f"  #{i+1}: pos=({h['cx']:.0f},{h['cy']:.0f}) conf={h['conf']:.3f} dist={dist:.0f}px")

    if not hooks:
        print("[WP] No hooks visible — closing map")
        press_key('m')
        time.sleep(random.uniform(0.8, 1.2))
        return None

    # Compute offset from screen center (= player position on ESO map)
    for h in hooks:
        h["dx"] = h["cx"] - screen_cx
        h["dy"] = h["cy"] - screen_cy
        h["dist"] = (h["dx"]**2 + h["dy"]**2) ** 0.5

    # Sort by pure distance — nearest first
    hooks.sort(key=lambda h: h["dist"])

    # Score: distance with direction bonus (forward = lower score = preferred)
    for h in hooks:
        if last_direction and h["dist"] > 0:
            ld_len = (last_direction[0]**2 + last_direction[1]**2) ** 0.5
            if ld_len > 0:
                dot = (h["dx"] * last_direction[0] + h["dy"] * last_direction[1]) / (h["dist"] * ld_len)
                h["score"] = h["dist"] * (1 - DIRECTION_BONUS_WEIGHT * dot)
            else:
                h["score"] = h["dist"]
        else:
            h["score"] = h["dist"]

    hooks.sort(key=lambda h: h["score"])

    dir_str = f"({last_direction[0]:+.0f},{last_direction[1]:+.0f})" if last_direction else "none"
    print(f"[WP] Scored hooks (last_dir={dir_str}):")
    for i, h in enumerate(hooks):
        print(f"  #{i+1}: offset=({h['dx']:+.0f},{h['dy']:+.0f}) dist={h['dist']:.0f}px score={h['score']:.0f}")

    nearest = hooks[0]
    print(f"[WP] PICKED hook at ({nearest['cx']:.0f}, {nearest['cy']:.0f}), "
          f"dist={nearest['dist']:.0f}px, score={nearest['score']:.0f}, conf={nearest['conf']:.3f}")

    # Save debug screenshot
    hook_num = getattr(pick_and_set_waypoint, '_hook_num', 0) + 1
    pick_and_set_waypoint._hook_num = hook_num
    save_debug_map(debug_frame_bgr, hooks, nearest, screen_cx, screen_cy, hook_num)

    # Remove old waypoint first
    press_key(WAYPOINT_KEY)
    time.sleep(random.uniform(0.2, 0.4))

    # Click on the hook to set new waypoint
    target_x = int(nearest["cx"])
    target_y = int(nearest["cy"])
    pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.3, 0.5))
    time.sleep(random.uniform(0.5, 0.7))
    press_key(WAYPOINT_KEY)
    time.sleep(random.uniform(0.3, 0.5))

    # Close map
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))

    return nearest


# ── Phase B: Turn to face waypoint ───────────────────────────────────

def phase_b_turn_to_waypoint(model, sct, monitor, screen_cx, dead_zone_px, stop_flag):
    """Turn camera to center compass_marker."""
    print()
    print("=" * 40)
    print("  PHASE B: Turn to face waypoint")
    print("=" * 40)
    print()

    centered = False
    for attempt in range(1, MAX_ALIGN_ATTEMPTS + 1):
        if stop_flag[0]:
            break

        detections = yolo_detect(model, sct, monitor)
        markers = [d for d in detections
                   if d["class"] == "compass_marker" and d["conf"] >= MARKER_MIN_CONF]

        if not markers:
            print(f"  [{attempt}/{MAX_ALIGN_ATTEMPTS}] No marker — searching...")
            human_mouse_arc(random.randint(800, 1500))
            time.sleep(ALIGN_PAUSE)
            continue

        marker = max(markers, key=lambda m: m["conf"])
        offset_screen = marker["cx"] - screen_cx
        print(f"  [{attempt}] offset={offset_screen:+.0f}px, conf={marker['conf']:.3f}")

        if abs(offset_screen) <= dead_zone_px:
            print(f"\n[B] CENTERED!")
            centered = True
            break

        mouse_px = offset_screen * SCREEN_TO_MOUSE
        correction = int(mouse_px * STEER_DAMPING)
        correction = max(-STEER_MAX_PX, min(STEER_MAX_PX, correction))
        human_mouse_arc(correction)
        time.sleep(random.uniform(0.08, 0.15))

    return centered


# ── Phase C: Run to waypoint ─────────────────────────────────────────

def phase_c_run_to_waypoint(model, ocr_reader, sct, monitor, screen_w, screen_cx, stop_flag):  # noqa: C901
    """Sprint toward waypoint with compass steering.

    Stops when:
    - compass_marker lost for N frames → quick check for interaction_prompt
    - YOLO detects interaction_prompt (fishing hole nearby)
    - F6 pressed or timeout

    Returns: "interaction", "no_spawn", "timeout", "stopped", "arrived"
    """
    print()
    print("=" * 40)
    print("  PHASE C: Run to waypoint")
    print("=" * 40)
    print()

    run_dead_zone = screen_w * RUN_DEAD_ZONE_FRAC
    marker_lost_count = 0
    steer_count = 0
    jump_count = 0
    prev_offset = None
    offset_history = []   # track sign changes for circling detection
    start_time = time.time()

    # Stuck detection state
    last_stuck_check_time = time.time()
    last_marker_x = None

    # Start sprinting
    print("[C] Starting sprint (W + Shift)...")
    pydirectinput.keyDown('shift')
    time.sleep(0.05)
    pydirectinput.keyDown('w')
    time.sleep(0.1)

    try:
        while not stop_flag[0]:
            elapsed = time.time() - start_time
            if elapsed > RUN_MAX_DURATION:
                print(f"\n[C] Max run time ({RUN_MAX_DURATION}s) reached!")
                return "timeout"

            # YOLO detect
            detections = yolo_detect(model, sct, monitor)
            markers = [d for d in detections
                       if d["class"] == "compass_marker" and d["conf"] >= MARKER_MIN_CONF]

            # Check for interaction_prompt + OCR to verify it's a fishing hole
            if has_interaction_prompt(detections):
                if is_fishing_prompt(ocr_reader, detections, sct, monitor):
                    print(f"\n[C] Fishing hole confirmed by OCR — stopping!")
                    return "interaction"

            if not markers:
                marker_lost_count += 1
                if marker_lost_count >= MARKER_LOST_THRESHOLD:
                    # Marker gone — we're near the waypoint, stop and look around
                    print(f"\n[C] Marker lost — arrived at waypoint area")
                    return "arrived"

                if marker_lost_count % 3 == 0:
                    print(f"  [{elapsed:.1f}s] Marker lost ({marker_lost_count}/{MARKER_LOST_THRESHOLD})...")
                time.sleep(RUN_DETECT_INTERVAL)
                continue

            # Marker found — reset lost counter
            marker_lost_count = 0
            # Pick marker closest to center (waypoint should be ~centered after Phase B)
            # Using highest-conf picks quest markers at compass edges instead
            marker = min(markers, key=lambda m: abs(m["cx"] - screen_cx))
            offset_screen = marker["cx"] - screen_cx
            marker_x = marker["cx"]
            # Detect passing through waypoint: marker jumps from one side to the other
            if prev_offset is not None:
                offset_jump = abs(offset_screen - prev_offset)
                if offset_jump >= MARKER_JUMP_THRESHOLD:
                    print(f"\n[C] Marker jumped {offset_jump:.0f}px "
                          f"({prev_offset:+.0f} → {offset_screen:+.0f}) — passed waypoint!")
                    return "arrived"
            prev_offset = offset_screen

            # Circling detection: track sign changes
            offset_history.append(offset_screen)
            if len(offset_history) > CIRCLING_HISTORY_SIZE:
                offset_history.pop(0)
            if len(offset_history) >= CIRCLING_HISTORY_SIZE:
                signs = [1 if o >= 0 else -1 for o in offset_history]
                flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
                if flips >= CIRCLING_FLIP_THRESHOLD:
                    print(f"\n[C] Circling detected ({flips} flips in {CIRCLING_HISTORY_SIZE} frames) — arrived!")
                    return "arrived"

            # Log every frame (temporary — to calibrate jump detection)
            steer_count += 1
            print(f"  [{elapsed:.1f}s] offset={offset_screen:+.0f}px, conf={marker['conf']:.3f}")

            # Stuck detection
            now = time.time()
            if now - last_stuck_check_time >= STUCK_CHECK_INTERVAL:
                if last_marker_x is not None:
                    marker_change = abs(marker_x - last_marker_x)
                    if marker_change < STUCK_MIN_CHANGE_PX:
                        jumps = random.randint(2, STUCK_JUMP_COUNT)
                        jump_count += jumps
                        print(f"  [{elapsed:.1f}s] STUCK! jumping {jumps}x")
                        for _ in range(jumps):
                            press_key('space')
                            time.sleep(random.uniform(0.3, 0.5))
                last_marker_x = marker_x
                last_stuck_check_time = now

            # Correct if drifting
            if abs(offset_screen) > run_dead_zone:
                mouse_px = offset_screen * SCREEN_TO_MOUSE
                correction = int(mouse_px * RUN_STEER_DAMPING)
                correction = max(-RUN_STEER_MAX_PX, min(RUN_STEER_MAX_PX, correction))
                steer_smooth(correction)

            time.sleep(RUN_DETECT_INTERVAL)

    finally:
        pydirectinput.keyUp('w')
        time.sleep(0.05)
        pydirectinput.keyUp('shift')
        print("[C] Stopped running.")

    total_time = time.time() - start_time
    print(f"[C] Ran for {total_time:.1f}s, {steer_count} steers, {jump_count} jumps")
    return "stopped"


# ── Phase D: Fish at the hole ────────────────────────────────────────

def phase_d_fish(sct, monitor, screen_w, screen_h, stop_flag):
    """Fish at the current hole until depleted or stopped.

    Cycle: cast (E) → wait for hook icon → reel (E) → loot (R) → repeat.
    Votan's Fisherman addon shows white hook icon when fish bites.

    Returns: (fish_caught, casts_made)
    """
    print()
    print("=" * 40)
    print("  PHASE D: FISHING!")
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

        # Wait for hook icon (white flash in center)
        print(f"  [Cast {casts_made}] Waiting for bite...")
        hook_start = time.time()
        got_bite = False

        while not stop_flag[0]:
            if time.time() - hook_start > MAX_WAIT_FOR_HOOK:
                break
            if detect_hook_bite(sct, monitor, screen_w, screen_h):
                got_bite = True
                break
            time.sleep(SCAN_INTERVAL)

        if stop_flag[0]:
            break

        if not got_bite:
            failed_casts += 1
            print(f"  [Cast {casts_made}] No bite! (failed: {failed_casts}/{MAX_FAILED_CASTS})")
            if failed_casts >= MAX_FAILED_CASTS:
                print(f"\n[D] Hole depleted! Fish: {fish_caught}, Casts: {casts_made}")
                break
            time.sleep(random.uniform(*DELAY_RECAST))
            continue

        # Got a bite! Reel in
        failed_casts = 0
        time.sleep(random.uniform(*DELAY_REEL_REACTION))
        print(f"  [Cast {casts_made}] BITE! Reeling in...")
        press_key(CAST_KEY)  # same key to reel

        time.sleep(random.uniform(*DELAY_AFTER_REEL))

        # Loot
        fish_caught += 1
        print(f"  [Cast {casts_made}] Fish #{fish_caught}! Looting...")
        press_key(LOOT_KEY)
        time.sleep(0.3)
        press_key(LOOT_KEY)  # double-tap for safety
        time.sleep(random.uniform(*DELAY_AFTER_LOOT))

    return fish_caught, casts_made


# ── Main ─────────────────────────────────────────────────────────────

def main():
    model_path = os.path.join(
        os.path.dirname(__file__), "training", "runs", "eso_fishing_v4", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    print("=" * 60)
    print("  FISHING BOT — Fresh Scan Each Iteration")
    print("  Open map → pick nearest hook → run → fish → repeat")
    print("=" * 60)
    print("  F5 — Start (switch to ESO first!)")
    print("  F6 — Stop immediately")
    print("=" * 60)

    print("[YOLO] Loading model...")
    model = YOLO(model_path)
    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    screen_cx = screen_w // 2
    dead_zone_px = screen_w * DEAD_ZONE_FRAC

    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"[YOLO] Ready. Screen: {screen_w}x{screen_h}")

    print("[OCR] Loading EasyOCR (ru+en)...")
    ocr_reader = easyocr.Reader(["ru", "en"], gpu=True, verbose=False)
    print("[OCR] Ready.")
    print("\nPress F5 when ESO is focused...\n")

    stop_flag = [False]
    def on_f6():
        stop_flag[0] = True
        print("\n[F6] STOP!")
    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)

    keyboard.wait("f5")
    time.sleep(0.5)

    # ── Route loop — fresh scan each iteration ──
    last_direction = None   # (dx, dy) of last movement — used to prefer forward hooks
    total_fish = 0
    total_casts = 0
    fished_count = 0
    skipped_count = 0
    hook_num = 0

    while not stop_flag[0]:
        hook_num += 1

        print()
        print("#" * 60)
        print(f"  HOOK {hook_num}")
        print("#" * 60)

        # Open map, scan, pick best hook (direction-aware), set waypoint
        hook = pick_and_set_waypoint(model, sct, monitor, screen_w, screen_h, last_direction)

        if hook is None:
            print("\n[DONE] No more hooks visible!")
            break

        # Remember direction for next iteration
        last_direction = (hook["dx"], hook["dy"])

        if stop_flag[0]:
            break

        # Turn to face waypoint
        centered = phase_b_turn_to_waypoint(model, sct, monitor, screen_cx, dead_zone_px, stop_flag)

        if stop_flag[0]:
            break
        if not centered:
            print(f"[SKIP] Hook {hook_num} — couldn't find waypoint marker")
            skipped_count += 1
            continue

        # Run to waypoint
        arrival = phase_c_run_to_waypoint(model, ocr_reader, sct, monitor, screen_w, screen_cx, stop_flag)

        if stop_flag[0]:
            break

        print(f"\n[ARRIVAL] Hook {hook_num}: {arrival}")

        # If we arrived but didn't see prompt during run, look around
        if arrival == "arrived":
            arrival = look_around_for_hole(model, ocr_reader, sct, monitor, stop_flag)
            print(f"[LOOK RESULT] Hook {hook_num}: {arrival}")

        if stop_flag[0]:
            break

        if arrival == "interaction":
            time.sleep(random.uniform(0.3, 0.5))
            fish, casts = phase_d_fish(sct, monitor, screen_w, screen_h, stop_flag)
            total_fish += fish
            total_casts += casts
            fished_count += 1
            print(f"[DONE] Hook {hook_num}: caught {fish} fish")

        elif arrival == "no_spawn":
            skipped_count += 1
            print(f"[SKIP] Hook {hook_num} — no spawn")

        elif arrival == "timeout":
            skipped_count += 1
            print(f"[SKIP] Hook {hook_num} — timeout")

        else:
            skipped_count += 1
            print(f"[SKIP] Hook {hook_num} — {arrival}")

    # ── Summary ──
    print()
    print("=" * 60)
    print("  ROUTE COMPLETE!")
    print(f"  Hooks visited: {fished_count + skipped_count}")
    print(f"  Fished:  {fished_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Total fish caught: {total_fish}")
    print(f"  Total casts: {total_casts}")
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
        # Safety: release any held keys
        try:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('shift')
        except Exception:
            pass
        input("\nPress Enter to exit...")
