"""
Test 2: Find compass_marker → Turn camera toward it (NO running)

Verifies that the YOLO model can:
1. Detect compass_marker on the compass bar
2. Calculate offset from screen center
3. Turn the camera to center the marker

The bot will NOT run — only rotate camera in place.

Usage:
  python "fishing/tests/test_compass_steer.py"

Controls:
  F5 — Run test (switch to ESO first! Have a waypoint set!)
  F6 — Stop

Prerequisite: Set a waypoint in ESO before running this test.
"""

import ctypes
import ctypes.wintypes
import os
import sys
import time

import keyboard
import mss
import cv2
import numpy as np
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


# ── Settings ──────────────────────────────────────────────────────────
MARKER_MIN_CONF = 0.3
STEER_DAMPING = 0.4           # Fraction of offset to correct per step
STEER_MAX_PX = 120            # Max mouse correction pixels per step
DEAD_ZONE_FRAC = 0.02         # Dead zone as fraction of screen width
MAX_ALIGN_ATTEMPTS = 15       # Max rotation attempts
ALIGN_PAUSE = 0.3             # Seconds between attempts


def main():
    model_path = os.path.join(
        os.path.dirname(__file__), "..", "training", "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        print("Run train.py first!")
        sys.exit(1)

    print("=" * 55)
    print("  TEST 2: compass_marker → Camera rotation")
    print("=" * 55)
    print("  F5 — Run test (have a waypoint set!)")
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
    dead_zone_px = screen_w * DEAD_ZONE_FRAC

    # Warm up
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"[YOLO] Model loaded. Classes: {model.names}")
    print(f"[YOLO] Screen: {screen_w}x{screen_h}, center_x={screen_cx}")
    print(f"[YOLO] Dead zone: ±{dead_zone_px:.0f}px")
    print("\nPress F5 when ESO is focused (with waypoint set)...\n")

    # Wait for F5
    stop_flag = [False]

    def on_f6():
        stop_flag[0] = True
        print("\n[F6] Stopping...")

    keyboard.on_press_key("f6", lambda _: on_f6(), suppress=False)
    keyboard.wait("f5")
    time.sleep(0.3)

    print("[TEST] Starting compass alignment...\n")

    for attempt in range(1, MAX_ALIGN_ATTEMPTS + 1):
        if stop_flag[0]:
            break

        # Capture screen
        screenshot = sct.grab(monitor)
        frame = np.array(screenshot)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        # YOLO detect
        results = model(frame_bgr, imgsz=640, conf=0.2, verbose=False)

        detections = []
        if results[0].boxes is not None:
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                cls_id = int(box.cls[0])
                detections.append({
                    "class": model.names[cls_id],
                    "conf": float(box.conf[0]),
                    "cx": float((x1 + x2) / 2),
                    "cy": float((y1 + y2) / 2),
                    "w": float(x2 - x1),
                })

        # Find compass_marker
        markers = [d for d in detections if d["class"] == "compass_marker" and d["conf"] >= MARKER_MIN_CONF]

        # Also show all detections for debugging
        all_classes = {}
        for d in detections:
            cls = d["class"]
            all_classes[cls] = all_classes.get(cls, 0) + 1
        print(f"  [{attempt}/{MAX_ALIGN_ATTEMPTS}] All: {all_classes}")

        if not markers:
            print(f"  [{attempt}] No compass_marker found! (try turning around)")
            # Small rotation to search
            send_mouse_move(100, 0)
            time.sleep(ALIGN_PAUSE)
            continue

        # Pick highest confidence marker
        marker = max(markers, key=lambda m: m["conf"])
        marker_x = marker["cx"]
        offset = marker_x - screen_cx

        print(f"  [{attempt}] Marker at x={marker_x:.0f}, "
              f"offset={offset:+.0f}px, conf={marker['conf']:.3f}")

        # Check if centered
        if abs(offset) <= dead_zone_px:
            print(f"\n[TEST] CENTERED! Marker is within dead zone (±{dead_zone_px:.0f}px)")
            print(f"[TEST] Final offset: {offset:+.0f}px")
            break

        # Calculate correction
        correction = int(offset * STEER_DAMPING)
        correction = max(-STEER_MAX_PX, min(STEER_MAX_PX, correction))

        direction = "RIGHT" if correction > 0 else "LEFT"
        print(f"  [{attempt}] Turning {direction}: {abs(correction)}px")

        # Apply mouse movement in small steps
        step = 30
        remaining = abs(correction)
        sign = 1 if correction > 0 else -1
        while remaining > 0:
            move = min(step, remaining)
            send_mouse_move(sign * move, 0)
            remaining -= move
            time.sleep(0.005)

        time.sleep(ALIGN_PAUSE)
    else:
        print(f"\n[TEST] Max attempts ({MAX_ALIGN_ATTEMPTS}) reached.")

    # Final check
    time.sleep(0.3)
    screenshot = sct.grab(monitor)
    frame = np.array(screenshot)
    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    results = model(frame_bgr, imgsz=640, conf=0.2, verbose=False)

    final_markers = []
    if results[0].boxes is not None:
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            if model.names[cls_id] == "compass_marker":
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                final_markers.append({
                    "conf": float(box.conf[0]),
                    "cx": float((x1 + x2) / 2),
                })

    if final_markers:
        best = max(final_markers, key=lambda m: m["conf"])
        final_offset = best["cx"] - screen_cx
        print(f"\n[TEST] Final marker position: x={best['cx']:.0f}, "
              f"offset={final_offset:+.0f}px, conf={best['conf']:.3f}")
        if abs(final_offset) <= dead_zone_px:
            print("[TEST] SUCCESS — marker is centered!")
        else:
            print(f"[TEST] NOT YET CENTERED (offset={final_offset:+.0f}px > ±{dead_zone_px:.0f}px)")
    else:
        print("\n[TEST] No marker detected in final check.")

    print("\n[TEST] DONE! Check visually:")
    print("  - Is the waypoint diamond centered on the compass?")
    print("  - Does the camera face toward the waypoint?")

    keyboard.unhook_all()


if __name__ == "__main__":
    main()
