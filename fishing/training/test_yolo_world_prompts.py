"""
Test different YOLO-World models and prompts on map screenshots.

Compares small vs medium vs large models and various text prompts
to find the best combination for fishing hook detection.
"""

import time
from pathlib import Path
from ultralytics import YOLO

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots" / "map"
TEST_IMAGES = sorted(SCREENSHOTS_DIR.glob("*.png"))[:10]  # test on 10 images

MODELS = [
    "yolov8s-worldv2",
    "yolov8m-worldv2",
    "yolov8l-worldv2",
]

PROMPTS = [
    ["blue pin icon"],                          # original
    ["small blue fishing hook icon on map"],    # more descriptive
    ["blue map marker"],                        # simpler
    ["blue diamond shape on map"],              # shape-based
    ["fishing spot icon"],                      # semantic
    ["small blue icon"],                        # minimal
]

CONF = 0.05


def count_ground_truth(img_path: Path) -> int:
    """Count annotations from YOLO-World run (as pseudo ground truth)."""
    txt = Path(__file__).parent / "annotations" / "map" / (img_path.stem + ".txt")
    if not txt.exists():
        return 0
    lines = txt.read_text().strip().split("\n")
    return sum(1 for l in lines if l.startswith("0 "))


def test_combination(model_name: str, classes: list[str]):
    """Test a model + prompt combination on test images."""
    model = YOLO(f"{model_name}.pt")
    model.set_classes(classes)

    total_detections = 0
    total_gt = 0
    imgs_with_det = 0

    for img_path in TEST_IMAGES:
        results = model.predict(str(img_path), conf=CONF, imgsz=1280, verbose=False, device="cpu")
        n = len(results[0].boxes)
        gt = count_ground_truth(img_path)
        total_detections += n
        total_gt += gt
        if n > 0:
            imgs_with_det += 1

    return total_detections, imgs_with_det, total_gt


def main():
    if not TEST_IMAGES:
        print("No test images found!")
        return

    print(f"Testing on {len(TEST_IMAGES)} images, conf={CONF}")
    print(f"{'Model':<22} {'Prompt':<42} {'Det':>5} {'Imgs':>5} {'GT':>5}")
    print("-" * 85)

    # First test all prompts with small model to find best prompt
    print("\n=== Phase 1: Find best prompts (small model) ===\n")
    best_prompts = []
    for classes in PROMPTS:
        prompt_str = classes[0]
        t0 = time.time()
        det, imgs, gt = test_combination("yolov8s-worldv2", classes)
        dt = time.time() - t0
        print(f"{'yolov8s-worldv2':<22} {prompt_str:<42} {det:>5} {imgs:>5} {gt:>5}  ({dt:.1f}s)")
        best_prompts.append((det, prompt_str, classes))

    # Sort by detections (more = better recall)
    best_prompts.sort(key=lambda x: x[0], reverse=True)
    top3 = best_prompts[:3]

    print(f"\n=== Phase 2: Test top 3 prompts on larger models ===\n")
    for model_name in ["yolov8m-worldv2", "yolov8l-worldv2"]:
        for _, prompt_str, classes in top3:
            t0 = time.time()
            det, imgs, gt = test_combination(model_name, classes)
            dt = time.time() - t0
            print(f"{model_name:<22} {prompt_str:<42} {det:>5} {imgs:>5} {gt:>5}  ({dt:.1f}s)")
        print()

    print("Done! Det=total detections, Imgs=images with detections, GT=ground truth count")


if __name__ == "__main__":
    main()
