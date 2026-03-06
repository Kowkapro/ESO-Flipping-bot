"""
Merge all CVAT YOLO exports from exports/ and rebuild train/val dataset.

Usage:
    python "fishing/training/build_dataset.py"
"""

import zipfile
import os
import shutil
import random
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
EXPORTS_DIR = BASE_DIR / "exports"
DATASET_DIR = BASE_DIR / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
TRAIN_DIR = DATASET_DIR / "train"
VAL_DIR = DATASET_DIR / "val"

CLASS_NAMES = {
    0: "blue_hook",
    1: "bubbles",
    2: "compass_marker",
    3: "enemy",
    4: "interaction_prompt",
    5: "hp_bar",
    6: "xp_popup",
    7: "destination_text",
    8: "player_icon",
    9: "waypoint_pin",
}

TRAIN_RATIO = 0.8
RANDOM_SEED = 42


def find_image(basename):
    """Find image file in dataset/images/ subdirectories."""
    for subdir in IMAGES_DIR.iterdir():
        if not subdir.is_dir():
            continue
        for ext in [".png", ".jpg", ".jpeg"]:
            img_path = subdir / (basename + ext)
            if img_path.exists():
                return str(img_path)
    return None


def merge_exports():
    """Merge all zip exports. Returns {basename: label_content}."""
    merged = defaultdict(list)

    zips = sorted(EXPORTS_DIR.glob("*.zip"))
    print(f"Found {len(zips)} export(s):")
    for z in zips:
        print(f"  - {z.name}")

    for zip_path in zips:
        with zipfile.ZipFile(zip_path) as zf:
            labels = [
                n for n in zf.namelist()
                if n.endswith(".txt") and "obj_train_data/" in n
            ]
            for label_name in labels:
                basename = os.path.splitext(os.path.basename(label_name))[0]
                content = zf.read(label_name).decode().strip()
                if content:
                    for line in content.split("\n"):
                        line = line.strip()
                        if line:
                            merged[basename].append(line)

    # Deduplicate lines per image
    result = {}
    for basename, lines in merged.items():
        unique_lines = list(dict.fromkeys(lines))
        result[basename] = "\n".join(unique_lines)

    return result


def build_dataset():
    print("=== Building YOLO dataset from CVAT exports ===\n")

    # Merge all exports
    merged = merge_exports()
    print(f"\nTotal unique images with labels: {len(merged)}")

    # Find matching images
    pairs = []
    missing = []
    for basename, label_content in sorted(merged.items()):
        img_path = find_image(basename)
        if img_path:
            pairs.append((img_path, basename, label_content))
        else:
            missing.append(basename)

    if missing:
        print(f"\nWARNING: {len(missing)} labels have no matching image:")
        for m in missing[:10]:
            print(f"  - {m}")

    print(f"Matched image-label pairs: {len(pairs)}")

    # Count annotations per class
    class_counts = Counter()
    for _, _, content in pairs:
        for line in content.split("\n"):
            cls_id = int(line.split()[0])
            class_counts[cls_id] += 1

    print(f"\nTotal annotations: {sum(class_counts.values())}")
    print("Per class:")
    for cls_id in sorted(CLASS_NAMES.keys()):
        count = class_counts.get(cls_id, 0)
        status = "OK" if count >= 20 else "LOW" if count > 0 else "MISSING"
        print(f"  {cls_id}: {CLASS_NAMES[cls_id]:25s} = {count:4d}  [{status}]")

    # Clean old train/val
    for split_dir in [TRAIN_DIR, VAL_DIR]:
        if split_dir.exists():
            shutil.rmtree(split_dir)
        (split_dir / "images").mkdir(parents=True)
        (split_dir / "labels").mkdir(parents=True)

    # Shuffle and split
    random.seed(RANDOM_SEED)
    random.shuffle(pairs)
    split_idx = int(len(pairs) * TRAIN_RATIO)
    train_pairs = pairs[:split_idx]
    val_pairs = pairs[split_idx:]
    print(f"\nSplit: {len(train_pairs)} train / {len(val_pairs)} val")

    # Copy files
    for split_name, split_pairs in [("train", train_pairs), ("val", val_pairs)]:
        split_dir = DATASET_DIR / split_name
        for img_path, basename, label_content in split_pairs:
            ext = os.path.splitext(img_path)[1]
            shutil.copy2(img_path, split_dir / "images" / (basename + ext))
            with open(split_dir / "labels" / (basename + ".txt"), "w") as f:
                f.write(label_content + "\n")

    # Print split class distribution
    for split_name in ["train", "val"]:
        labels_dir = DATASET_DIR / split_name / "labels"
        counts = Counter()
        for lbl_file in labels_dir.glob("*.txt"):
            for line in lbl_file.read_text().strip().split("\n"):
                if line.strip():
                    counts[int(line.split()[0])] += 1
        print(f"\n{split_name} class distribution:")
        for cls_id in sorted(CLASS_NAMES.keys()):
            print(f"  {CLASS_NAMES[cls_id]:25s} = {counts.get(cls_id, 0)}")

    print("\nDataset build complete!")


if __name__ == "__main__":
    build_dataset()
