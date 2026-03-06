"""
YOLO Live Overlay — transparent real-time detection overlay on ESO screen.

Shows bounding boxes, class names, confidence directly on top of the game.
The overlay is click-through so it doesn't interfere with gameplay.

Usage:
  python "fishing/tools/yolo_live_view.py"
  python "fishing/tools/yolo_live_view.py" --model v4

Controls:
  F6 — quit
"""

import argparse
import ctypes
import ctypes.wintypes
import os
import sys
import threading
import time
import tkinter as tk

import keyboard
import mss
import numpy as np
from ultralytics import YOLO

# ── Win32 — make overlay click-through ──────────────────────────────

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOPMOST = 0x8
WS_EX_TOOLWINDOW = 0x80  # hide from taskbar

user32 = ctypes.windll.user32
SetWindowLongW = user32.SetWindowLongW
GetWindowLongW = user32.GetWindowLongW

# ── Model paths ─────────────────────────────────────────────────────

MODELS = {
    "v2": os.path.join(os.path.dirname(__file__), "..", "training", "runs", "eso_fishing", "weights", "best.pt"),
    "v3": os.path.join(os.path.dirname(__file__), "..", "training", "runs", "eso_fishing_v3", "weights", "best.pt"),
    "v4": os.path.join(os.path.dirname(__file__), "..", "training", "runs", "eso_fishing_v4", "weights", "best.pt"),
}

# ── Colors per class (tkinter hex) ──────────────────────────────────

COLORS = {
    "red_hook":           "#FF4444",
    "blue_hook":          "#4488FF",
    "bubbles":            "#FFFF00",
    "compass_marker":     "#00FF00",
    "enemy":              "#FF0000",
    "interaction_prompt": "#FF00FF",
    "hp_bar":             "#FF8800",
    "xp_popup":           "#CCCCCC",
    "destination_text":   "#00FFFF",
    "player_icon":        "#FFFFFF",
    "waypoint_pin":       "#FF66AA",
}

TRANSPARENT_COLOR = "#010101"


def main():
    parser = argparse.ArgumentParser(description="YOLO Live Overlay")
    parser.add_argument("--model", default="v4", choices=MODELS.keys(), help="Model version")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--imgsz", type=int, default=1280, help="Inference image size")
    args = parser.parse_args()

    model_path = os.path.normpath(MODELS[args.model])
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    print(f"Loading YOLO model ({args.model}): {model_path}")
    model = YOLO(model_path)

    # Warmup
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print("Model loaded. Warmup done.")

    # Screen info (temporary mss just to get monitor dimensions)
    with mss.mss() as sct_tmp:
        monitor = sct_tmp.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]
    print(f"Screen: {screen_w}x{screen_h}")

    # ── Tkinter transparent overlay ─────────────────────────────────

    root = tk.Tk()
    root.title("YOLO Overlay")
    root.geometry(f"{screen_w}x{screen_h}+0+0")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", TRANSPARENT_COLOR)
    root.config(bg=TRANSPARENT_COLOR)

    canvas = tk.Canvas(
        root, width=screen_w, height=screen_h,
        bg=TRANSPARENT_COLOR, highlightthickness=0
    )
    canvas.pack()

    # Make window click-through via Win32
    root.update_idletasks()
    hwnd = ctypes.windll.user32.FindWindowW(None, "YOLO Overlay")
    if hwnd:
        style = GetWindowLongW(hwnd, GWL_EXSTYLE)
        SetWindowLongW(hwnd, GWL_EXSTYLE,
                       style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        print("Overlay is click-through.")
    else:
        print("[WARN] Could not find overlay window handle")

    # ── Stop flag ───────────────────────────────────────────────────

    stop_flag = [False]

    def on_f6():
        stop_flag[0] = True

    keyboard.on_press_key("f6", lambda _: on_f6())

    # ── FPS counter ─────────────────────────────────────────────────

    fps_data = {"count": 0, "last_time": time.time(), "fps": 0.0}

    # ── Info bar at top ─────────────────────────────────────────────

    info_id = canvas.create_text(
        screen_w // 2, 12, text="", fill="#00FF00",
        font=("Consolas", 12, "bold"), anchor="n"
    )

    # ── Main detection loop (runs in thread) ────────────────────────

    box_items = []

    def detection_loop():
        nonlocal box_items

        # Create mss instance in this thread (mss uses thread-local storage)
        sct = mss.mss()

        while not stop_flag[0]:
            t0 = time.time()

            # Capture screen
            screenshot = sct.grab(monitor)
            frame = np.array(screenshot)[:, :, :3]  # drop alpha, keep BGR

            # YOLO inference
            results = model(frame, imgsz=args.imgsz, conf=args.conf, verbose=False)

            # Collect detections
            detections = []
            if results[0].boxes is not None:
                for box in results[0].boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                    cls_name = model.names[int(box.cls[0])]
                    conf = float(box.conf[0])
                    color = COLORS.get(cls_name, "#FFFFFF")
                    detections.append((x1, y1, x2, y2, cls_name, conf, color))

            # FPS
            fps_data["count"] += 1
            elapsed = time.time() - fps_data["last_time"]
            if elapsed >= 1.0:
                fps_data["fps"] = fps_data["count"] / elapsed
                fps_data["count"] = 0
                fps_data["last_time"] = time.time()

            # Schedule canvas update on main thread
            root.after(0, lambda dets=detections: update_canvas(dets))

            # Cap at ~30 FPS
            dt = time.time() - t0
            if dt < 0.033:
                time.sleep(0.033 - dt)

    def update_canvas(detections):
        nonlocal box_items

        # Clear old drawings
        for item in box_items:
            canvas.delete(item)
        box_items = []

        # Draw new detections
        for x1, y1, x2, y2, cls_name, conf, color in detections:
            # Bounding box
            rect = canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
            box_items.append(rect)

            # Label background
            label = f"{cls_name} {conf:.2f}"
            lbl_bg = canvas.create_rectangle(
                x1, y1 - 18, x1 + len(label) * 8 + 6, y1,
                fill=color, outline=color
            )
            box_items.append(lbl_bg)

            # Label text
            lbl = canvas.create_text(
                x1 + 3, y1 - 9, text=label, fill="black",
                font=("Consolas", 10, "bold"), anchor="w"
            )
            box_items.append(lbl)

        # Update info bar
        n = len(detections)
        canvas.itemconfig(info_id, text=f"YOLO Overlay | {fps_data['fps']:.0f} FPS | {n} detections | F6=quit")

    # Start detection thread
    det_thread = threading.Thread(target=detection_loop, daemon=True)
    det_thread.start()

    print("Overlay running! Switch to ESO. Press F6 to quit.")

    # Tkinter main loop
    def check_stop():
        if stop_flag[0]:
            root.destroy()
            return
        root.after(100, check_stop)

    root.after(100, check_stop)
    root.mainloop()

    keyboard.unhook_all()
    print("Overlay closed.")


if __name__ == "__main__":
    main()
