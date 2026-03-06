"""
Test YOLO-World zero-shot detection on ESO screenshots.

YOLO-World can detect objects by text prompts without training.
We test it on map screenshots to find blue fishing hook icons.
"""

import os
import sys
from pathlib import Path
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont

# Paths
DATASET_DIR = Path(__file__).parent / "dataset" / "images"
PREVIEW_DIR = Path(__file__).parent / "yolo_world_preview"
PREVIEW_DIR.mkdir(exist_ok=True)

# Text prompts for zero-shot detection per category
# Each category gets a fresh model load to avoid CUDA set_classes bug
CATEGORIES = {
    "map": [
        "blue pin icon",           # fishing hooks on map
        "blue triangle arrow",     # player icon
        "diamond waypoint marker", # waypoint pin
    ],
    "compass": [
        "white arrow marker",      # waypoint marker on compass
        "quest marker icon",       # quest markers on compass
    ],
    "interaction": [
        "water bubbles",           # fishing hole bubbles
        "text prompt overlay",     # [E] interaction prompt
    ],
    "combat": [
        "enemy character",         # hostile NPC
        "health bar",              # HP bar
    ],
}

COLORS = [
    (0, 120, 255),   # blue
    (0, 255, 0),     # green
    (255, 0, 255),   # magenta
    (255, 255, 0),   # yellow
    (255, 128, 0),   # orange
    (0, 255, 255),   # cyan
    (255, 0, 0),     # red
]


def test_category(category: str, classes: list[str], max_images: int = 3):
    """Test YOLO-World on a category of screenshots."""
    img_dir = DATASET_DIR / category
    if not img_dir.exists():
        print(f"  [SKIP] No directory: {img_dir}")
        return

    images = sorted(img_dir.glob("*.png"))[:max_images]
    if not images:
        print(f"  [SKIP] No images in {img_dir}")
        return

    # Load fresh model for each category (avoids CUDA set_classes bug)
    model = YOLO("yolov8s-worldv2.pt")
    model.set_classes(classes)

    print(f"\n{'='*60}")
    print(f"  Category: {category}")
    print(f"  Classes: {classes}")
    print(f"  Testing {len(images)} images")
    print(f"{'='*60}")

    for img_path in images:
        print(f"\n  Image: {img_path.name}")

        # Run inference
        results = model.predict(
            str(img_path),
            conf=0.05,  # low threshold to see what it finds
            imgsz=1280,
            verbose=False,
        )

        result = results[0]
        boxes = result.boxes

        if len(boxes) == 0:
            print(f"    No detections (conf >= 0.05)")
            continue

        # Print detections
        for box in boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            w, h = x2 - x1, y2 - y1
            cls_name = classes[cls_id]
            print(f"    [{cls_name}] conf={conf:.3f}  pos=({x1:.0f},{y1:.0f})  size={w:.0f}x{h:.0f}")

        # Draw preview
        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        for box in boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            color = COLORS[cls_id % len(COLORS)]
            cls_name = classes[cls_id]

            # Draw box
            for t in range(3):  # thick border
                draw.rectangle([x1 - t, y1 - t, x2 + t, y2 + t], outline=color)

            # Label
            label = f"{cls_name} {conf:.2f}"
            draw.text((x1, y1 - 15), label, fill=color)

        # Save preview
        out_dir = PREVIEW_DIR / category
        out_dir.mkdir(exist_ok=True)
        preview_path = out_dir / img_path.name
        img.save(preview_path)
        print(f"    Preview: {preview_path}")


def main():
    print("YOLO-World Zero-Shot Detection Test")
    print("=" * 60)

    for category, classes in CATEGORIES.items():
        test_category(category, classes, max_images=2)

    print(f"\n\nAll previews saved to: {PREVIEW_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
