"""
Train YOLO11 on ESO fishing dataset v3.

Usage:
  python "fishing/training/train.py"
  python "fishing/training/train.py" --model yolo11l.pt --epochs 150 --imgsz 1280
"""

import argparse
import os
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description="Train YOLO on ESO fishing data")
    parser.add_argument("--model", default="yolo11s.pt", help="Base model (yolo11n/s/m/l/x)")
    parser.add_argument("--epochs", type=int, default=150, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=1280, help="Image size")
    parser.add_argument("--batch", type=int, default=2, help="Batch size (2 for 8GB VRAM at 1280)")
    parser.add_argument("--workers", type=int, default=2, help="DataLoader workers")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    args = parser.parse_args()

    data_yaml = os.path.join(os.path.dirname(__file__), "dataset", "eso_fishing.yaml")

    print("=" * 50)
    print("  ESO Fishing — YOLO11 Training (v4)")
    print("=" * 50)
    print(f"  Model:  {args.model}")
    print(f"  Epochs: {args.epochs}")
    print(f"  ImgSz:  {args.imgsz}")
    print(f"  Batch:  {args.batch}")
    print(f"  Data:   {data_yaml}")
    print(f"  Resume: {args.resume}")
    print()

    if args.resume:
        last_path = os.path.join(os.path.dirname(__file__), "runs", "eso_fishing_v4", "weights", "last.pt")
        if os.path.exists(last_path):
            model = YOLO(last_path)
            print(f"Resuming from {last_path}")
        else:
            print(f"No checkpoint found at {last_path}, starting fresh")
            model = YOLO(args.model)
    else:
        model = YOLO(args.model)

    results = model.train(
        data=data_yaml,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=os.path.join(os.path.dirname(__file__), "runs"),
        name="eso_fishing_v4",
        exist_ok=True,
        # Augmentation
        hsv_h=0.015,
        hsv_s=0.4,
        hsv_v=0.3,
        flipud=0.0,        # No vertical flip (game UI is always upright)
        fliplr=0.5,         # Horizontal flip is fine
        mosaic=1.0,          # Mosaic augmentation
        mixup=0.1,           # Light mixup
        copy_paste=0.1,      # Copy-paste augmentation
        # Training params
        workers=args.workers,
        patience=25,         # Early stopping (more patience for larger model)
        save=True,
        plots=True,
        amp=True,            # Mixed precision for VRAM savings
    )

    best_path = os.path.join(os.path.dirname(__file__), "runs", "eso_fishing_v4", "weights", "best.pt")
    print()
    print("=" * 50)
    print(f"Training complete!")
    print(f"Best model: {best_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
