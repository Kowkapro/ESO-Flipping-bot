"""
Test 5: Full cycle — Map → Waypoint → Run → FISH

Complete fishing cycle test:
1. Open map, zoom, YOLO find nearest blue_hook, set waypoint
2. Close map, turn to face waypoint
3. Sprint toward waypoint with live compass steering
4. Detect arrival: compass_marker lost + "рыбалки" text on screen
5. Stop, face the fishing hole, cast line, catch fish, repeat

Arrival detection:
  - compass_marker disappears (within ~10m, distance label gone)
  - AND/OR YOLO detects `interaction_prompt` class (e.g. "[E] Ловить рыбу")

Fishing detection:
  - Votan's Fisherman addon shows white hook icon on bite
  - Pixel-based detection in center of screen

Usage:
  python "fishing/AI fishing gibrid/test_full_fishing_cycle.py"

Controls:
  F5 — Run test (switch to ESO first!)
  F6 — Stop immediately (releases all keys)
"""

import ctypes
import ctypes.wintypes
import math
import os
import random
import sys
import time

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
    duration = 0.10 + (abs_dx / 5000) * 0.30
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
HOOK_MIN_CONF = 0.3

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
ALIGN_PAUSE = 0.15

# Running (Phase C)
RUN_STEER_DAMPING = 0.7
RUN_STEER_MAX_PX = 1500
RUN_DEAD_ZONE_FRAC = 0.03
RUN_MAX_DURATION = 60.0
RUN_DETECT_INTERVAL = 0.15
MARKER_LOST_THRESHOLD = 8
MARKER_LOST_MAX_RETRIES = 5     # max times to retry after marker lost (jump+nudge)

# Stuck detection
STUCK_CHECK_INTERVAL = 2.0
STUCK_MIN_CHANGE_PX = 15
STUCK_JUMP_COUNT = 3

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

# Interaction prompt detection (YOLO)
INTERACTION_MIN_CONF = 0.3


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
    results = model(frame_bgr, imgsz=640, conf=0.2, verbose=False)

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


# ── Phase A: Set waypoint ────────────────────────────────────────────

def phase_a_set_waypoint(model, sct, monitor, screen_w, screen_h, screen_cx, screen_cy):
    """Open map, zoom, find nearest blue_hook, set waypoint, close map."""
    print("=" * 40)
    print("  PHASE A: Set waypoint on nearest hook")
    print("=" * 40)

    print("\n[A1] Opening map...")
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))

    zoom_x = int(screen_w * ZOOM_PLUS_REL[0])
    zoom_y = int(screen_h * ZOOM_PLUS_REL[1])
    print(f"[A2] Zooming in ({MAP_ZOOM_CLICKS} clicks on '+')...")
    for _ in range(MAP_ZOOM_CLICKS):
        pyautogui.click(zoom_x, zoom_y)
        time.sleep(random.uniform(0.05, 0.10))
    time.sleep(random.uniform(0.3, 0.5))

    print("[A3] Running YOLO detection on map...")
    detections = yolo_detect(model, sct, monitor)
    hooks = [d for d in detections if d["class"] == "blue_hook" and d["conf"] >= HOOK_MIN_CONF]
    print(f"[A3] Found {len(hooks)} blue_hooks")

    if not hooks:
        print("[A3] No hooks found! Closing map.")
        press_key('m')
        return False

    best = min(hooks, key=lambda d:
        (d["cx"] - screen_cx) ** 2 + (d["cy"] - screen_cy) ** 2)
    dist = math.sqrt((best["cx"] - screen_cx) ** 2 + (best["cy"] - screen_cy) ** 2)
    print(f"[A4] Nearest hook: conf={best['conf']:.3f}, dist={dist:.0f}px")

    target_x = int(best["cx"])
    target_y = int(best["cy"])
    print(f"[A5] Setting waypoint at ({target_x}, {target_y})...")
    pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.3, 0.5))
    time.sleep(0.15)
    press_key(WAYPOINT_KEY)
    time.sleep(random.uniform(0.3, 0.5))

    print("[A6] Closing map...")
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))
    return True


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
        time.sleep(random.uniform(0.15, 0.35))

    return centered


# ── Phase C: Run to waypoint ─────────────────────────────────────────

def phase_c_run_to_waypoint(model, sct, monitor, screen_w, screen_cx, stop_flag):  # noqa: C901
    """Sprint toward waypoint with compass steering.

    Stops when:
    - compass_marker lost for N frames (arrived)
    - YOLO detects interaction_prompt (fishing hole nearby)
    - F6 pressed or timeout

    Returns: "arrived", "interaction", "timeout", "stopped"
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
    start_time = time.time()

    # Stuck detection state
    last_stuck_check_time = time.time()
    last_marker_x = None

    # Marker-lost-but-stuck retry counter
    marker_lost_stuck_count = 0

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

            # YOLO detect — only compass_marker matters while running
            detections = yolo_detect(model, sct, monitor)
            markers = [d for d in detections
                       if d["class"] == "compass_marker" and d["conf"] >= MARKER_MIN_CONF]

            # Check for interaction_prompt in current detections (early arrival)
            if has_interaction_prompt(detections):
                print(f"\n[C] interaction_prompt detected — ARRIVED!")
                return "interaction"

            if not markers:
                marker_lost_count += 1
                if marker_lost_count >= MARKER_LOST_THRESHOLD:
                    # Marker gone — do one more YOLO check for interaction prompt
                    recheck = yolo_detect(model, sct, monitor)
                    if has_interaction_prompt(recheck):
                        print(f"\n[C] Marker lost + interaction_prompt visible — ARRIVED!")
                        return "interaction"

                    # No interaction prompt = probably stuck, NOT arrived
                    # Jump to get unstuck and keep running
                    marker_lost_stuck_count += 1
                    print(f"\n[C] Marker lost but NO interaction text — STUCK! "
                          f"(attempt {marker_lost_stuck_count}/{MARKER_LOST_MAX_RETRIES})")

                    if marker_lost_stuck_count >= MARKER_LOST_MAX_RETRIES:
                        print(f"[C] Gave up after {MARKER_LOST_MAX_RETRIES} stuck retries.")
                        return "arrived"

                    # Jump to get unstuck
                    for _ in range(random.randint(2, 3)):
                        press_key('space')
                        time.sleep(random.uniform(0.3, 0.5))

                    # Small random turn to try a different angle
                    nudge = random.randint(200, 600) * random.choice([-1, 1])
                    steer_smooth(nudge)
                    print(f"  Nudged {nudge}px, continuing...")

                    # Reset lost counter to give it another chance
                    marker_lost_count = 0
                    time.sleep(RUN_DETECT_INTERVAL)
                    continue

                if marker_lost_count % 3 == 0:
                    print(f"  [{elapsed:.1f}s] Marker lost ({marker_lost_count}/{MARKER_LOST_THRESHOLD})...")
                time.sleep(RUN_DETECT_INTERVAL)
                continue

            # Marker found — reset lost counter
            marker_lost_count = 0
            marker = max(markers, key=lambda m: m["conf"])
            offset_screen = marker["cx"] - screen_cx
            marker_x = marker["cx"]

            # Log periodically
            steer_count += 1
            if steer_count % 5 == 1:
                print(f"  [{elapsed:.1f}s] marker offset={offset_screen:+.0f}px, "
                      f"conf={marker['conf']:.3f}")

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
        os.path.dirname(__file__), "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    print("=" * 60)
    print("  TEST 5: Full Fishing Cycle")
    print("  Map → Waypoint → Run → FISH")
    print("=" * 60)
    print("  F5 — Run test (switch to ESO first!)")
    print("  F6 — Stop immediately")
    print("=" * 60)

    print("[YOLO] Loading model...")
    model = YOLO(model_path)
    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    screen_cx = screen_w // 2
    screen_cy = screen_h // 2
    dead_zone_px = screen_w * DEAD_ZONE_FRAC

    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"[YOLO] Ready. Screen: {screen_w}x{screen_h}")
    print("\nPress F5 when ESO is focused...\n")

    stop_flag = [False]
    def on_f6():
        stop_flag[0] = True
        print("\n[F6] STOP!")
    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)

    keyboard.wait("f5")
    time.sleep(0.5)

    # ── Phase A: Set waypoint ──
    if not phase_a_set_waypoint(model, sct, monitor, screen_w, screen_h, screen_cx, screen_cy):
        keyboard.unhook_all()
        return

    if stop_flag[0]:
        keyboard.unhook_all()
        return

    # ── Phase B: Turn to face ──
    centered = phase_b_turn_to_waypoint(model, sct, monitor, screen_cx, dead_zone_px, stop_flag)

    if stop_flag[0] or not centered:
        keyboard.unhook_all()
        return

    # ── Phase C: Run to waypoint ──
    arrival = phase_c_run_to_waypoint(model, sct, monitor, screen_w, screen_cx, stop_flag)

    if stop_flag[0]:
        keyboard.unhook_all()
        return

    print(f"\n[ARRIVAL] Reason: {arrival}")

    if arrival in ("arrived", "interaction"):
        # Small pause to settle after running
        time.sleep(random.uniform(0.5, 1.0))

        # Verify we see interaction_prompt via YOLO before fishing
        detections = yolo_detect(model, sct, monitor)
        has_interaction = has_interaction_prompt(detections)
        print(f"[CHECK] interaction_prompt visible: {has_interaction}")

        if not has_interaction:
            # Walk forward a bit and recheck (might be just out of range)
            print("[CHECK] No prompt yet — walking forward a bit...")
            pydirectinput.keyDown('w')
            time.sleep(random.uniform(1.0, 2.0))
            pydirectinput.keyUp('w')
            time.sleep(0.3)
            detections = yolo_detect(model, sct, monitor)
            has_interaction = has_interaction_prompt(detections)
            print(f"[CHECK] Recheck: {has_interaction}")

        if has_interaction:
            # ── Phase D: FISH! ──
            fish_caught, casts_made = phase_d_fish(sct, monitor, screen_w, screen_h, stop_flag)

            print()
            print("=" * 60)
            print(f"[TEST 5] FISHING COMPLETE!")
            print(f"  Fish caught: {fish_caught}")
            print(f"  Casts made: {casts_made}")
            print("=" * 60)
        else:
            print("[CHECK] No interaction_prompt after walking up.")
            print("[CHECK] Might not be at the right spot.")
    else:
        print(f"[RESULT] Did not arrive at fishing hole (reason: {arrival})")

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
