"""
Test 1: Map → Find blue_hook → Set waypoint

Verifies that the YOLO model can:
1. Detect blue_hook icons on the map
2. Click the nearest one and set a waypoint

Usage:
  python "fishing/AI fishing gibrid/test_map_waypoint.py"

Controls:
  F5 — Run test (switch to ESO first!)
  F6 — Stop
"""

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


# ── Settings ──────────────────────────────────────────────────────────
MAP_ZOOM_CLICKS = 10          # clicks on "+" button to max-zoom centered on player
ZOOM_PLUS_REL = (0.659, 0.963)  # "+" button position (fraction of screen W/H)
WAYPOINT_KEY = 'f'
HOOK_MIN_CONF = 0.3


def press_key(key):
    """Press a key via DirectInput with human-like hold time."""
    hold_time = random.uniform(0.04, 0.12)
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


def build_route_nn(points, start):
    """Build a route using nearest-neighbor heuristic (greedy TSP).

    Args:
        points: list of dicts with 'cx', 'cy' keys
        start: (x, y) starting position (player on map)

    Returns:
        list of points in visit order
    """
    remaining = list(points)
    route = []
    cur_x, cur_y = start

    while remaining:
        nearest = min(remaining, key=lambda p:
            (p["cx"] - cur_x) ** 2 + (p["cy"] - cur_y) ** 2)
        route.append(nearest)
        cur_x, cur_y = nearest["cx"], nearest["cy"]
        remaining.remove(nearest)

    return route


def route_total_dist(route, start):
    """Calculate total travel distance for a route."""
    total = 0.0
    cx, cy = start
    for p in route:
        total += math.sqrt((p["cx"] - cx) ** 2 + (p["cy"] - cy) ** 2)
        cx, cy = p["cx"], p["cy"]
    return total


def main():
    model_path = os.path.join(
        os.path.dirname(__file__), "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        print("Run train.py first!")
        sys.exit(1)

    print("=" * 55)
    print("  TEST 1: Map → blue_hook → Waypoint")
    print("=" * 55)
    print("  F5 — Run test (switch to ESO first!)")
    print("  F6 — Stop")
    print("=" * 55)

    # Load model
    print("[YOLO] Loading model...")
    model = YOLO(model_path)
    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    screen_cx = screen_w // 2
    screen_cy = screen_h // 2

    # Warm up
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"[YOLO] Model loaded. Classes: {model.names}")
    print(f"[YOLO] Screen: {screen_w}x{screen_h}")
    print("\nPress F5 when ESO is focused...\n")

    # Wait for F5
    keyboard.wait("f5")
    time.sleep(0.5)

    # === Step 1: Open map ===
    print("[TEST] Opening map...")
    press_key('m')
    time.sleep(random.uniform(0.8, 1.2))

    # === Step 2: Zoom in via "+" button (centers on player) ===
    zoom_x = int(screen_w * ZOOM_PLUS_REL[0])
    zoom_y = int(screen_h * ZOOM_PLUS_REL[1])
    print(f"[TEST] Zooming in ({MAP_ZOOM_CLICKS} clicks on '+' at ({zoom_x}, {zoom_y}))...")
    for i in range(MAP_ZOOM_CLICKS):
        pyautogui.click(zoom_x, zoom_y)
        time.sleep(random.uniform(0.05, 0.10))
    time.sleep(random.uniform(0.3, 0.5))

    # === Step 3: YOLO detect ===
    print("[TEST] Running YOLO detection...")
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

    # Print ALL detections
    print(f"\n[TEST] All detections ({len(detections)}):")
    for d in sorted(detections, key=lambda x: -x["conf"]):
        print(f"  {d['class']:20s} conf={d['conf']:.3f} "
              f"at ({d['cx']:.0f}, {d['cy']:.0f}) "
              f"box=({d['x1']:.0f},{d['y1']:.0f})-({d['x2']:.0f},{d['y2']:.0f})")

    # Filter blue_hooks
    hooks = [d for d in detections if d["class"] == "blue_hook" and d["conf"] >= HOOK_MIN_CONF]
    print(f"\n[TEST] Blue hooks (conf >= {HOOK_MIN_CONF}): {len(hooks)}")

    if not hooks:
        print("[TEST] No blue_hooks found! Closing map...")
        press_key('m')
        return

    # === Step 4: Build optimal route (nearest-neighbor TSP) ===
    player_pos = (screen_cx, screen_cy)
    route = build_route_nn(hooks, player_pos)
    total_dist = route_total_dist(route, player_pos)

    print(f"\n[TEST] Route planned: {len(route)} hooks, "
          f"total distance: {total_dist:.0f}px")
    print("[TEST] Order:")
    cx, cy = player_pos
    for i, hook in enumerate(route, 1):
        seg = math.sqrt((hook["cx"] - cx) ** 2 + (hook["cy"] - cy) ** 2)
        print(f"  {i:2d}. ({hook['cx']:.0f}, {hook['cy']:.0f}) "
              f"conf={hook['conf']:.3f}  +{seg:.0f}px")
        cx, cy = hook["cx"], hook["cy"]

    # === Step 5: Set waypoint on each hook along the route ===
    print(f"\n[TEST] Walking the route...")
    for i, hook in enumerate(route, 1):
        target_x = int(hook["cx"])
        target_y = int(hook["cy"])

        print(f"\n[TEST] [{i}/{len(route)}] conf={hook['conf']:.3f}, "
              f"at ({target_x}, {target_y})")

        pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.2, 0.4))
        time.sleep(0.1)

        press_key(WAYPOINT_KEY)
        print(f"  -> Waypoint set! Waiting 2s...")
        time.sleep(2.0)

    # === Step 6: Close map ===
    print(f"\n[TEST] All {len(route)} waypoints tested! Closing map...")
    press_key('m')
    time.sleep(0.5)

    print("\n[TEST] DONE! Check:")
    print(f"  - Did all {len(route)} waypoints follow a logical route?")
    print("  - Any hooks missed by YOLO?")


if __name__ == "__main__":
    main()
