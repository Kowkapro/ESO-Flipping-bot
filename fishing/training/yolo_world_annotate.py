"""
YOLO-World auto-annotator for map screenshots.

Runs zero-shot detection on map screenshots to find fishing hooks
and player icons, then saves YOLO-format .txt annotation files.

Usage:
  python fishing/training/yolo_world_annotate.py
  python fishing/training/yolo_world_annotate.py --conf 0.05 --preview
"""

import argparse
import os
from pathlib import Path
from ultralytics import YOLO
from PIL import Image, ImageDraw

# v3 class IDs for map objects
CLASS_MAP = {
    "blue pin icon": 0,        # fishing_hook
    "blue triangle arrow": 1,  # player_icon
}

COLORS = {
    0: (0, 120, 255),   # blue for hooks
    1: (0, 255, 0),     # green for player
}

CLASS_NAMES = {
    0: "fishing_hook",
    1: "player_icon",
}


def annotate_maps(screenshots_dir: Path, output_dir: Path, conf: float, preview: bool, preview_dir: Path):
    """Run YOLO-World on map screenshots and save YOLO annotations."""
    images = sorted(screenshots_dir.glob("*.png"))
    if not images:
        print(f"No images found in {screenshots_dir}")
        return

    print(f"Loading YOLO-World model...")
    model = YOLO("yolov8s-worldv2.pt")
    classes = list(CLASS_MAP.keys())
    model.set_classes(classes)
    print(f"Model loaded. Classes: {classes}")
    print(f"Processing {len(images)} images (conf >= {conf})...\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    if preview:
        preview_dir.mkdir(parents=True, exist_ok=True)

    total_annotations = 0
    total_images_with_detections = 0

    for i, img_path in enumerate(images):
        results = model.predict(
            str(img_path),
            conf=conf,
            imgsz=1280,
            verbose=False,
        )

        result = results[0]
        boxes = result.boxes
        img_w, img_h = result.orig_shape[1], result.orig_shape[0]

        # Convert to YOLO format
        lines = []
        for box in boxes:
            cls_idx = int(box.cls[0])
            class_name = classes[cls_idx]
            v3_class_id = CLASS_MAP[class_name]

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cx = (x1 + x2) / 2 / img_w
            cy = (y1 + y2) / 2 / img_h
            w = (x2 - x1) / img_w
            h = (y2 - y1) / img_h

            lines.append(f"{v3_class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

        # Save annotation
        txt_path = output_dir / (img_path.stem + ".txt")
        txt_path.write_text("\n".join(lines) if lines else "")

        n = len(lines)
        total_annotations += n
        if n > 0:
            total_images_with_detections += 1

        # Progress
        hooks = sum(1 for l in lines if l.startswith("0 "))
        players = sum(1 for l in lines if l.startswith("1 "))
        status = f"hooks={hooks}, player={players}" if n > 0 else "empty"
        print(f"  [{i+1}/{len(images)}] {img_path.name}: {status}")

        # Draw preview
        if preview and n > 0:
            img = Image.open(img_path).convert("RGB")
            draw = ImageDraw.Draw(img)
            for box in boxes:
                cls_idx = int(box.cls[0])
                class_name = classes[cls_idx]
                v3_id = CLASS_MAP[class_name]
                conf_val = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                color = COLORS.get(v3_id, (255, 255, 255))

                for t in range(3):
                    draw.rectangle([x1 - t, y1 - t, x2 + t, y2 + t], outline=color)
                draw.text((x1, y1 - 15), f"{CLASS_NAMES[v3_id]} {conf_val:.2f}", fill=color)

            img.save(preview_dir / img_path.name)

    print(f"\nDone!")
    print(f"  Images processed: {len(images)}")
    print(f"  Images with detections: {total_images_with_detections}")
    print(f"  Total annotations: {total_annotations}")
    print(f"  Annotations saved to: {output_dir}")
    if preview:
        print(f"  Previews saved to: {preview_dir}")


def main():
    parser = argparse.ArgumentParser(description="YOLO-World auto-annotator for map screenshots")
    parser.add_argument("--conf", type=float, default=0.05, help="Confidence threshold")
    parser.add_argument("--preview", action="store_true", help="Save preview images with boxes")
    parser.add_argument("--input", type=str, default=None, help="Input directory (default: screenshots/map)")
    args = parser.parse_args()

    base = Path(__file__).parent
    screenshots_dir = Path(args.input) if args.input else base / "screenshots" / "map"
    output_dir = base / "annotations" / "map"
    preview_dir = base / "yolo_world_preview" / "map"

    annotate_maps(screenshots_dir, output_dir, args.conf, args.preview, preview_dir)


if __name__ == "__main__":
    main()
