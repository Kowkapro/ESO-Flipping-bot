"""
Test 3: Map → Set waypoint on blue_hook → Close map → Turn to face it

Full cycle test:
1. Open map, zoom in (centered on player)
2. YOLO detect blue_hook → pick nearest → set waypoint
3. Close map
4. Rotate camera until compass_marker is centered ("Ваш пункт назначения")

The bot will NOT run — only set waypoint and rotate.

Usage:
  python "fishing/tests/test_waypoint_and_turn.py"

Controls:
  F5 — Run test (switch to ESO first!)
  F6 — Stop
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


# ── Win32 SendInput for mouse (ESO ignores pydirectinput mouse moves) ──

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
    """Move mouse smoothly — no jerks, like dragging with your hand.

    Sends 1-2px per tick at high frequency (~500 Hz).
    Speed follows a sine curve: slow start → peak → slow end.
    Slight Y-axis arc for natural feel.
    """
    abs_dx = abs(total_dx)
    if abs_dx == 0:
        return

    sign = 1 if total_dx > 0 else -1

    # Duration: 0.12s for small, 0.4s for big (scales with distance)
    duration = 0.10 + (abs_dx / 5000) * 0.30
    duration *= random.uniform(0.9, 1.1)

    # Arc: gentle Y curve
    arc_height = random.uniform(2, 6) * random.choice([-1, 1])

    tick = 0.002  # 2ms per tick (~500 Hz) — buttery smooth
    elapsed = 0.0
    moved_x = 0
    prev_y = 0

    while elapsed < duration:
        t = elapsed / duration
        # S-curve progress
        progress = (1 - math.cos(t * math.pi)) / 2

        target_x = int(abs_dx * progress)
        dx = target_x - moved_x

        # Y arc
        cur_y = int(arc_height * math.sin(t * math.pi))
        dy = cur_y - prev_y

        if dx != 0 or dy != 0:
            send_mouse_move(sign * dx, dy)
            moved_x = target_x
            prev_y = cur_y

        time.sleep(tick)
        elapsed += tick

    # Finish any remaining pixels
    remaining = abs_dx - moved_x
    if remaining > 0:
        send_mouse_move(sign * remaining, -prev_y)


# ── Settings ──────────────────────────────────────────────────────────
# Map / waypoint
MAP_ZOOM_CLICKS = 10
ZOOM_PLUS_REL = (0.659, 0.963)
WAYPOINT_KEY = 'f'
HOOK_MIN_CONF = 0.3

# Mouse calibration (800 DPI, ESO look speed 15)
PIXELS_PER_360 = 9300          # calibrated in-game
PIXELS_PER_DEGREE = PIXELS_PER_360 / 360  # ~25.83

# Compass alignment
MARKER_MIN_CONF = 0.3
# Screen px to mouse px: compass shows ~180° FOV, so full screen width ≈ 180°
# 180° = 9300/2 = 4650 mouse px. For 1920 screen: 4650/1920 ≈ 2.42
SCREEN_TO_MOUSE = (PIXELS_PER_360 / 2) / 1920  # auto-calc from calibration
STEER_DAMPING = 0.9            # correct 90% per step
STEER_MAX_PX = 5000            # allow up to ~180° per step
DEAD_ZONE_FRAC = 0.02
MAX_ALIGN_ATTEMPTS = 20
ALIGN_PAUSE = 0.15


def press_key(key):
    """Press a key via DirectInput with human-like hold time."""
    hold_time = random.uniform(0.04, 0.12)
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


def yolo_detect(model, sct, monitor):
    """Grab screen and run YOLO detection, return list of detections."""
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


def main():
    model_path = os.path.join(
        os.path.dirname(__file__), "..", "training", "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    print("=" * 60)
    print("  TEST 3: Map → Waypoint → Close → Turn to face it")
    print("=" * 60)
    print("  F5 — Run test (switch to ESO first!)")
    print("  F6 — Stop")
    print("=" * 60)

    # Load model
    print("[YOLO] Loading model...")
    model = YOLO(model_path)
    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    screen_cx = screen_w // 2
    screen_cy = screen_h // 2
    dead_zone_px = screen_w * DEAD_ZONE_FRAC

    # Warm up
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"[YOLO] Model loaded. Screen: {screen_w}x{screen_h}")
    print(f"[YOLO] Dead zone: ±{dead_zone_px:.0f}px")
    print("\nPress F5 when ESO is focused...\n")

    stop_flag = [False]
    def on_f6():
        stop_flag[0] = True
        print("\n[F6] Stopping...")
    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)

    keyboard.wait("f5")
    time.sleep(0.5)

    # ================================================================
    # PHASE A: Open map → zoom → find hook → set waypoint → close map
    # ================================================================

    print("=" * 40)
    print("  PHASE A: Set waypoint on nearest hook")
    print("=" * 40)

    # Step 1: Open map
    print("\n[A1] Opening map...")
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))

    # Step 2: Zoom in via "+"
    zoom_x = int(screen_w * ZOOM_PLUS_REL[0])
    zoom_y = int(screen_h * ZOOM_PLUS_REL[1])
    print(f"[A2] Zooming in ({MAP_ZOOM_CLICKS} clicks on '+')...")
    for _ in range(MAP_ZOOM_CLICKS):
        pyautogui.click(zoom_x, zoom_y)
        time.sleep(random.uniform(0.05, 0.10))
    time.sleep(random.uniform(0.3, 0.5))

    # Step 3: YOLO detect
    print("[A3] Running YOLO detection on map...")
    detections = yolo_detect(model, sct, monitor)

    hooks = [d for d in detections if d["class"] == "blue_hook" and d["conf"] >= HOOK_MIN_CONF]
    print(f"[A3] Found {len(hooks)} blue_hooks (conf >= {HOOK_MIN_CONF})")

    if not hooks:
        print("[A3] No hooks found! Closing map and aborting.")
        press_key('m')
        keyboard.unhook_all()
        return

    # Step 4: Pick nearest to player (center of map)
    best = min(hooks, key=lambda d:
        (d["cx"] - screen_cx) ** 2 + (d["cy"] - screen_cy) ** 2)
    dist = math.sqrt((best["cx"] - screen_cx) ** 2 + (best["cy"] - screen_cy) ** 2)
    print(f"[A4] Nearest hook: conf={best['conf']:.3f}, "
          f"at ({best['cx']:.0f}, {best['cy']:.0f}), dist={dist:.0f}px")

    # Step 5: Set waypoint
    target_x = int(best["cx"])
    target_y = int(best["cy"])
    print(f"[A5] Setting waypoint at ({target_x}, {target_y})...")
    pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.3, 0.5))
    time.sleep(0.15)
    press_key(WAYPOINT_KEY)
    time.sleep(random.uniform(0.3, 0.5))

    # Step 6: Close map
    print("[A6] Closing map...")
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))

    if stop_flag[0]:
        keyboard.unhook_all()
        return

    # ================================================================
    # PHASE B: Turn camera to face the waypoint
    # ================================================================

    print()
    print("=" * 40)
    print("  PHASE B: Turn to face waypoint")
    print("=" * 40)
    print()

    for attempt in range(1, MAX_ALIGN_ATTEMPTS + 1):
        if stop_flag[0]:
            break

        detections = yolo_detect(model, sct, monitor)

        # Debug: show what YOLO sees
        class_counts = {}
        for d in detections:
            class_counts[d["class"]] = class_counts.get(d["class"], 0) + 1
        print(f"  [{attempt}/{MAX_ALIGN_ATTEMPTS}] Detected: {class_counts}")

        # Find compass_marker
        markers = [d for d in detections
                   if d["class"] == "compass_marker" and d["conf"] >= MARKER_MIN_CONF]

        if not markers:
            print(f"  [{attempt}] No compass_marker — rotating to search...")
            human_mouse_arc(random.randint(800, 1500))
            time.sleep(ALIGN_PAUSE)
            continue

        marker = max(markers, key=lambda m: m["conf"])
        offset_screen = marker["cx"] - screen_cx

        print(f"  [{attempt}] Marker at x={marker['cx']:.0f}, "
              f"offset={offset_screen:+.0f}px (screen), conf={marker['conf']:.3f}")

        if abs(offset_screen) <= dead_zone_px:
            print(f"\n[B] CENTERED! Offset {offset_screen:+.0f}px within ±{dead_zone_px:.0f}px")
            break

        # Convert screen pixels to mouse pixels and apply correction
        mouse_px = offset_screen * SCREEN_TO_MOUSE
        correction = int(mouse_px * STEER_DAMPING)
        correction = max(-STEER_MAX_PX, min(STEER_MAX_PX, correction))
        direction = "RIGHT" if correction > 0 else "LEFT"
        print(f"  [{attempt}] Turning {direction}: {abs(correction)} mouse px")

        human_mouse_arc(correction)
        time.sleep(random.uniform(0.15, 0.35))
    else:
        print(f"\n[B] Max attempts ({MAX_ALIGN_ATTEMPTS}) reached.")

    # ================================================================
    # Final result
    # ================================================================
    print()
    print("=" * 60)
    print("[TEST 3] DONE!")
    print("  Check in-game:")
    print("  - Is 'Ваш пункт назначения' visible on screen?")
    print("  - Is the waypoint diamond centered on compass?")
    print("  - Does the camera face toward the fishing hook?")
    print("=" * 60)

    keyboard.unhook_all()


if __name__ == "__main__":
    main()
