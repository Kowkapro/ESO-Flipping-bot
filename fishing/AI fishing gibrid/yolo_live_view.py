"""
YOLO Live View — real-time detection overlay on ESO screen.

Shows what the model sees: bounding boxes, class names, confidence.
Run this, switch to ESO, and walk around to see detections.

Usage:
  python "fishing/AI fishing gibrid/yolo_live_view.py"

Controls:
  Q or ESC — quit (in the OpenCV window)
"""

import os
import sys

import cv2
import mss
import numpy as np
from ultralytics import YOLO

# Colors per class (BGR)
COLORS = {
    "blue_hook":          (255, 100, 0),    # blue
    "bubbles":            (0, 255, 255),     # yellow
    "compass_marker":     (0, 255, 0),       # green
    "enemy":              (0, 0, 255),       # red
    "interaction_prompt": (255, 0, 255),     # magenta
    "hp_bar":             (0, 100, 255),     # orange
    "xp_popup":           (200, 200, 200),   # gray
    "destination_text":   (255, 255, 0),     # cyan
}


def main():
    model_path = os.path.join(
        os.path.dirname(__file__), "runs", "eso_fishing", "weights", "best.pt"
    )
    if not os.path.exists(model_path):
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    print("Loading YOLO model...")
    model = YOLO(model_path)

    # Warmup
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model(dummy, verbose=False)

    sct = mss.mss()
    monitor = sct.monitors[1]
    screen_w = monitor["width"]
    screen_h = monitor["height"]

    # Display at half resolution for performance
    disp_w = screen_w // 2
    disp_h = screen_h // 2

    print(f"Screen: {screen_w}x{screen_h}, display: {disp_w}x{disp_h}")
    print("Switch to ESO and watch the OpenCV window.")
    print("Press Q or ESC to quit.\n")

    cv2.namedWindow("YOLO Live", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("YOLO Live", disp_w, disp_h)

    while True:
        screenshot = sct.grab(monitor)
        frame = np.array(screenshot)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        results = model(frame_bgr, imgsz=640, conf=0.2, verbose=False)

        # Draw detections
        if results[0].boxes is not None:
            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                cls_name = model.names[int(box.cls[0])]
                conf = float(box.conf[0])
                color = COLORS.get(cls_name, (255, 255, 255))

                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, 2)

                label = f"{cls_name} {conf:.2f}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                cv2.rectangle(frame_bgr, (x1, y1 - th - 6), (x1 + tw, y1), color, -1)
                cv2.putText(frame_bgr, label, (x1, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

        # Resize for display
        display = cv2.resize(frame_bgr, (disp_w, disp_h))
        cv2.imshow("YOLO Live", display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):  # Q or ESC
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
