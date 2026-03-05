"""
Vision Prototype — YOLOv8 real-time screen detection for ESO.

Captures the screen, runs YOLO inference on each frame,
and displays detections in a separate OpenCV window.

Controls:
  F6 — stop
  1  — switch to ESO custom model (trained)
  2  — switch to YOLOv8s (COCO pretrained)
  3  — switch to YOLOv8n (COCO pretrained, fastest)
"""

import time
import os
import cv2
import numpy as np
import mss
import keyboard
from ultralytics import YOLO


# ── Settings ─────────────────────────────────────────────────────────
MONITOR_INDEX = 1        # 1 = primary monitor (mss uses 1-based index)
INFERENCE_SIZE = 640     # YOLO input size (pixels)
CONFIDENCE = 0.3         # Min confidence threshold
DISPLAY_SCALE = 0.5      # Scale down display window (0.5 = half size)

# Path to our trained ESO model
ESO_MODEL = os.path.join(os.path.dirname(__file__), "runs", "eso_fishing", "weights", "best.pt")

# Class colors (BGR) for our ESO classes
CLASS_COLORS = {
    "blue_hook": (255, 150, 0),       # Blue
    "bubbles": (255, 255, 0),         # Cyan
    "waypoint_marker": (0, 255, 255), # Yellow
    "enemy": (0, 0, 255),             # Red
}

# ── State ────────────────────────────────────────────────────────────
running = True
current_model_name = ""
model = None
switch_model_to = None


def stop_callback(event):
    global running
    running = False
    print("\n[F6] Stopping...")


def switch_eso(event):
    global switch_model_to
    switch_model_to = ESO_MODEL


def switch_coco_s(event):
    global switch_model_to
    switch_model_to = "yolov8s.pt"


def switch_coco_n(event):
    global switch_model_to
    switch_model_to = "yolov8n.pt"


def load_model(model_path):
    """Load a YOLO model and warm up."""
    global model, current_model_name
    display_name = "ESO custom" if "best.pt" in model_path else model_path
    print(f"Loading {display_name}...")
    model = YOLO(model_path)
    current_model_name = display_name
    # Warm up
    dummy = np.zeros((INFERENCE_SIZE, INFERENCE_SIZE, 3), dtype=np.uint8)
    model(dummy, verbose=False)
    print(f"Model loaded on {model.device}")
    if hasattr(model, 'names'):
        print(f"Classes: {model.names}")


def main():
    global running, model, switch_model_to

    print("=" * 50)
    print("  ESO Vision — Custom YOLO Model")
    print("=" * 50)
    print("Controls:")
    print("  F6 — stop")
    print("  1  — ESO custom model (blue_hook, bubbles, waypoint, enemy)")
    print("  2  — YOLOv8s COCO (generic objects)")
    print("  3  — YOLOv8n COCO (fastest)")
    print()

    # Register hotkeys
    keyboard.on_press_key("F6", stop_callback, suppress=False)
    keyboard.on_press_key("1", switch_eso, suppress=False)
    keyboard.on_press_key("2", switch_coco_s, suppress=False)
    keyboard.on_press_key("3", switch_coco_n, suppress=False)

    # Load ESO model by default
    if os.path.exists(ESO_MODEL):
        load_model(ESO_MODEL)
    else:
        print(f"WARNING: ESO model not found at {ESO_MODEL}")
        print("Falling back to yolov8s.pt")
        load_model("yolov8s.pt")

    # Setup screen capture
    sct = mss.mss()
    monitor = sct.monitors[MONITOR_INDEX]
    print(f"Capturing monitor {MONITOR_INDEX}: {monitor['width']}x{monitor['height']}")
    print("Starting inference loop...\n")

    # FPS tracking
    frame_times = []
    fps_display = 0.0

    try:
        while running:
            t_start = time.perf_counter()

            # Check model switch request
            if switch_model_to and switch_model_to != current_model_name:
                load_model(switch_model_to)
                switch_model_to = None

            # Capture screen
            screenshot = sct.grab(monitor)
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # Run inference
            results = model(
                frame,
                imgsz=INFERENCE_SIZE,
                conf=CONFIDENCE,
                verbose=False,
            )

            # Draw results on frame
            annotated = results[0].plot()

            # Calculate FPS
            t_end = time.perf_counter()
            frame_times.append(t_end - t_start)
            if len(frame_times) > 30:
                frame_times.pop(0)
            fps_display = len(frame_times) / sum(frame_times)

            # Count detections per class
            det_counts = {}
            if results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0])
                    cls_name = model.names[cls_id]
                    det_counts[cls_name] = det_counts.get(cls_name, 0) + 1

            # Add info overlay
            info_text = f"FPS: {fps_display:.1f} | Model: {current_model_name}"
            cv2.putText(
                annotated, info_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )

            # Show detection counts
            if det_counts:
                det_text = " | ".join(f"{k}: {v}" for k, v in det_counts.items())
                cv2.putText(
                    annotated, det_text, (10, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2,
                )

            # Resize for display
            if DISPLAY_SCALE != 1.0:
                h, w = annotated.shape[:2]
                new_w = int(w * DISPLAY_SCALE)
                new_h = int(h * DISPLAY_SCALE)
                annotated = cv2.resize(annotated, (new_w, new_h))

            # Show window
            cv2.imshow("ESO Vision — Custom Model", annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        cv2.destroyAllWindows()
        keyboard.unhook_all()
        print(f"\nFinal avg FPS: {fps_display:.1f}")
        print("Done.")


if __name__ == "__main__":
    main()
