"""
Train YOLOv8 on ESO fishing dataset.

Usage:
  python "fishing/training/train.py"
  python "fishing/training/train.py" --model yolov8s.pt --epochs 150
"""

import argparse
import os
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description="Train YOLO on ESO fishing data")
    parser.add_argument("--model", default="yolov8s.pt", help="Base model (yolov8n/s/m)")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--batch", type=int, default=4, help="Batch size")
    parser.add_argument("--workers", type=int, default=2, help="DataLoader workers")
    args = parser.parse_args()

    data_yaml = os.path.join(os.path.dirname(__file__), "dataset", "eso_fishing.yaml")

    print("=" * 50)
    print("  ESO Fishing — YOLO Training")
    print("=" * 50)
    print(f"  Model:  {args.model}")
    print(f"  Epochs: {args.epochs}")
    print(f"  ImgSz:  {args.imgsz}")
    print(f"  Batch:  {args.batch}")
    print(f"  Data:   {data_yaml}")
    print()

    model = YOLO(args.model)

    results = model.train(
        data=data_yaml,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=os.path.join(os.path.dirname(__file__), "runs"),
        name="eso_fishing",
        exist_ok=True,
        # Augmentation for small dataset
        hsv_h=0.015,
        hsv_s=0.4,
        hsv_v=0.3,
        flipud=0.0,       # No vertical flip (game UI is always upright)
        fliplr=0.5,       # Horizontal flip is fine
        mosaic=1.0,        # Mosaic augmentation
        mixup=0.1,         # Light mixup
        copy_paste=0.1,    # Copy-paste augmentation
        # Training params
        workers=args.workers,
        patience=20,       # Early stopping
        save=True,
        plots=True,
    )

    # Print results location
    best_path = os.path.join(os.path.dirname(__file__), "runs", "eso_fishing", "weights", "best.pt")
    print()
    print("=" * 50)
    print(f"Training complete!")
    print(f"Best model: {best_path}")
    print(f"Use it in vision_prototype.py or the fishing bot.")
    print("=" * 50)


if __name__ == "__main__":
    main()
