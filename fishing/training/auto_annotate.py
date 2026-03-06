"""
Auto-annotate ESO screenshots using Claude Vision API.

Sends screenshots to Claude, gets bounding box annotations back,
saves in YOLO format. Includes visual preview mode to verify accuracy.

Usage:
  # Test on 5 images with visual preview:
  python fishing/training/auto_annotate.py --test

  # Annotate all screenshots in a category:
  python fishing/training/auto_annotate.py --category map

  # Annotate everything:
  python fishing/training/auto_annotate.py --all
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

# Load API key from .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
POLZA_BASE_URL = os.getenv("POLZA_BASE_URL", "https://api.polza.ai/v1")

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "dataset", "images")
ANNOTATIONS_DIR = os.path.join(os.path.dirname(__file__), "annotations")
PREVIEW_DIR = os.path.join(os.path.dirname(__file__), "annotation_preview")

# Screen resolution (for coordinate validation)
SCREEN_W = 1920
SCREEN_H = 1080

# Model v3 classes
CLASSES = {
    "fishing_hook": 0,
    "player_icon": 1,
    "waypoint_pin": 2,
    "waypoint_marker": 3,
    "quest_marker": 4,
    "fishing_prompt": 5,
    "npc_prompt": 6,
    "bubbles": 7,
    "enemy": 8,
    "hp_bar": 9,
}

# Which classes to look for in each screenshot category
CATEGORY_CLASSES = {
    "map": ["fishing_hook", "player_icon", "waypoint_pin"],
    "compass": ["waypoint_marker", "quest_marker"],
    "fishing": ["fishing_prompt", "bubbles", "waypoint_marker", "quest_marker"],
    "npc": ["npc_prompt", "waypoint_marker", "quest_marker"],
    "interaction": ["fishing_prompt", "npc_prompt", "bubbles"],
    "gameplay": ["fishing_prompt", "npc_prompt", "bubbles", "enemy", "hp_bar",
                 "waypoint_marker", "quest_marker"],
    "combat": ["enemy", "hp_bar", "waypoint_marker", "quest_marker"],
    "navigation": ["waypoint_marker", "quest_marker"],
    "general": list(CLASSES.keys()),
    "xp": ["waypoint_marker", "quest_marker"],
    "running": ["waypoint_marker", "quest_marker"],
}

# Class descriptions for Claude prompt
CLASS_DESCRIPTIONS = {
    "fishing_hook": (
        "Blue fishing hook icon from HarvestMap addon on the game map. "
        "Small blue hook-shaped icons (~20-30px) scattered across the map near water. "
        "NOT the player's blue triangle arrow."
    ),
    "player_icon": (
        "Blue triangular arrow icon showing the player's position on the map. "
        "Always near the center of the map. Points in the direction the player faces. "
        "It's a filled blue triangle, NOT a hook shape."
    ),
    "waypoint_pin": (
        "Diamond-shaped waypoint marker placed on the map by the player. "
        "Appears as a small diamond/rhombus icon on the map where the player set a waypoint."
    ),
    "waypoint_marker": (
        "The player's custom waypoint marker on the compass bar at the top of the screen. "
        "Appears as a small pointed marker/chevron on the compass strip. "
        "This is the marker for the destination the player set with F key. "
        "It moves along the compass as the player turns."
    ),
    "quest_marker": (
        "Quest objective marker on the compass bar at the top of the screen. "
        "Can be a black arrow/chevron, a door icon, or other quest-related markers. "
        "These are NOT the player's custom waypoint — they show quest objectives. "
        "Often appears as a dark/black downward-pointing arrow on the compass."
    ),
    "fishing_prompt": (
        'Interaction prompt for fishing holes. Shows Russian text like '
        '"[E] Место рыбалки на реке" or "[E] Место рыбалки на озере" or similar. '
        "Appears in the center-bottom area of the screen when near a fishing hole. "
        "The key element is [E] followed by text about fishing (рыбалка/рыба)."
    ),
    "npc_prompt": (
        'Non-fishing interaction prompt. Shows Russian text like '
        '"[E] Поговорить", "[E] Путешествовать", "[E] Открыть", "[E] Использовать" etc. '
        "Any [E] prompt that is NOT about fishing. "
        "Appears in the center area of the screen when near an NPC, wayshrine, or object."
    ),
    "bubbles": (
        "Water splash/bubbles effect on the water surface indicating an active fishing hole. "
        "Appears as white/light circular ripples or splashing on the water. "
        "Usually visible near riverbanks or lake shores where fish can be caught."
    ),
    "enemy": (
        "Hostile NPC/enemy creature in the game world. "
        "Has a red health bar above them or shows hostile behavior. "
        "Can be wolves, bandits, undead, daedra, or other hostile creatures."
    ),
    "hp_bar": (
        "Health/HP bar — either the player's HP bar at the top of the screen "
        "or an enemy's HP bar floating above them. "
        "Rectangular bar, usually red/green colored, showing health amount."
    ),
}

# Colors for bbox visualization (BGR)
CLASS_COLORS = {
    "fishing_hook": (255, 165, 0),    # orange
    "player_icon": (255, 0, 0),       # blue
    "waypoint_pin": (0, 255, 255),    # yellow
    "waypoint_marker": (0, 255, 0),   # green
    "quest_marker": (0, 0, 255),      # red
    "fishing_prompt": (255, 255, 0),  # cyan
    "npc_prompt": (128, 0, 128),      # purple
    "bubbles": (255, 200, 200),       # light blue
    "enemy": (0, 0, 200),             # dark red
    "hp_bar": (0, 128, 0),            # dark green
}


def encode_image_base64(image_path):
    """Read image and encode as base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def build_prompt(category):
    """Build the annotation prompt for Claude based on image category."""
    classes_to_find = CATEGORY_CLASSES.get(category, list(CLASSES.keys()))

    class_list = ""
    for cls_name in classes_to_find:
        desc = CLASS_DESCRIPTIONS[cls_name]
        class_list += f'  - "{cls_name}": {desc}\n'

    return f"""You are an expert annotator for an Elder Scrolls Online (ESO) bot training dataset.
The game uses Russian localization. Screen resolution is {SCREEN_W}x{SCREEN_H}.

Analyze this ESO screenshot and find ALL instances of these objects:

{class_list}

For each object found, provide a tight bounding box in pixel coordinates.

IMPORTANT RULES:
- Return ONLY objects you are confident about (>80% sure)
- Bounding boxes must be tight — as close to the object edges as possible
- Coordinates are in pixels: x1,y1 = top-left corner, x2,y2 = bottom-right corner
- x ranges from 0 to {SCREEN_W}, y ranges from 0 to {SCREEN_H}
- Small icons (hooks, markers) are typically 15-35 pixels wide
- If you see NO objects of any class, return an empty list
- Do NOT hallucinate objects that aren't clearly visible

Return ONLY valid JSON (no markdown, no explanation):
{{"objects": [{{"class": "class_name", "bbox": [x1, y1, x2, y2]}}]}}"""


def call_claude_api(image_path, category):
    """Send image to Claude Vision API and get annotations."""
    import httpx

    image_b64 = encode_image_base64(image_path)

    # Determine media type
    ext = Path(image_path).suffix.lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"

    prompt = build_prompt(category)

    try:
        response = httpx.post(
            f"{POLZA_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {POLZA_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "anthropic/claude-sonnet-4",
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            },
            timeout=120.0,
        )
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
        print(f"    Connection error: {type(e).__name__}")
        return None

    if response.status_code != 200:
        print(f"    API error {response.status_code}: {response.text[:200]}")
        return None

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    # Parse JSON from response
    try:
        # Handle case where Claude wraps in markdown code block
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        result = json.loads(content.strip())
        return result
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        print(f"  Raw response: {content[:300]}")
        return None


def validate_bbox(bbox, cls_name):
    """Validate and clamp bounding box coordinates."""
    x1, y1, x2, y2 = bbox

    # Clamp to screen bounds
    x1 = max(0, min(x1, SCREEN_W))
    y1 = max(0, min(y1, SCREEN_H))
    x2 = max(0, min(x2, SCREEN_W))
    y2 = max(0, min(y2, SCREEN_H))

    # Ensure x2 > x1, y2 > y1
    if x2 <= x1 or y2 <= y1:
        return None

    # Minimum size check (at least 5px)
    if (x2 - x1) < 5 or (y2 - y1) < 5:
        return None

    return [x1, y1, x2, y2]


def bbox_to_yolo(bbox, img_w, img_h):
    """Convert [x1, y1, x2, y2] to YOLO format [x_center, y_center, width, height] normalized."""
    x1, y1, x2, y2 = bbox
    x_center = ((x1 + x2) / 2) / img_w
    y_center = ((y1 + y2) / 2) / img_h
    width = (x2 - x1) / img_w
    height = (y2 - y1) / img_h
    return [x_center, y_center, width, height]


def save_yolo_annotations(objects, output_path, img_w, img_h):
    """Save annotations in YOLO format."""
    lines = []
    for obj in objects:
        cls_name = obj["class"]
        if cls_name not in CLASSES:
            continue
        bbox = validate_bbox(obj["bbox"], cls_name)
        if bbox is None:
            continue
        cls_id = CLASSES[cls_name]
        yolo_bbox = bbox_to_yolo(bbox, img_w, img_h)
        lines.append(f"{cls_id} {yolo_bbox[0]:.6f} {yolo_bbox[1]:.6f} {yolo_bbox[2]:.6f} {yolo_bbox[3]:.6f}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return len(lines)


def draw_preview(image_path, objects, output_path):
    """Draw bounding boxes on image for visual verification."""
    img = cv2.imread(image_path)
    if img is None:
        return

    for obj in objects:
        cls_name = obj["class"]
        bbox = validate_bbox(obj["bbox"], cls_name)
        if bbox is None:
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox]
        color = CLASS_COLORS.get(cls_name, (255, 255, 255))

        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = cls_name
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, img)


def get_category_from_filename(filename):
    """Infer category from filename prefix."""
    name = os.path.basename(filename).lower()
    for cat in CATEGORY_CLASSES:
        if name.startswith(cat):
            return cat
    return "general"


def process_image(image_path, category=None, preview=True):
    """Process a single image: send to Claude, save annotations and preview."""
    if category is None:
        category = get_category_from_filename(image_path)

    filename = os.path.basename(image_path)
    label_name = Path(filename).stem + ".txt"

    print(f"  Processing: {filename} (category: {category})")

    # Call Claude API
    result = call_claude_api(image_path, category)
    if result is None:
        print(f"    FAILED — no result from API")
        return 0

    objects = result.get("objects", [])
    print(f"    Found {len(objects)} objects: {[o['class'] for o in objects]}")

    # Save YOLO annotations
    ann_path = os.path.join(ANNOTATIONS_DIR, category, label_name)
    count = save_yolo_annotations(objects, ann_path, SCREEN_W, SCREEN_H)
    print(f"    Saved {count} valid annotations to {ann_path}")

    # Draw preview
    if preview and objects:
        preview_path = os.path.join(PREVIEW_DIR, category, filename)
        draw_preview(image_path, objects, preview_path)
        print(f"    Preview saved to {preview_path}")

    return count


def test_mode():
    """Test on a few images from each category to verify accuracy."""
    print("=" * 60)
    print("  AUTO-ANNOTATOR TEST MODE")
    print("  Processing 2 images per category")
    print("=" * 60)
    print()

    total = 0
    for category in sorted(os.listdir(IMAGES_DIR)):
        cat_dir = os.path.join(IMAGES_DIR, category)
        if not os.path.isdir(cat_dir):
            continue

        images = sorted([f for f in os.listdir(cat_dir) if f.endswith(".png")])
        if not images:
            continue

        # Take first 2 images
        test_images = images[:2]
        print(f"\n[{category.upper()}] Testing {len(test_images)} images:")

        for img_name in test_images:
            img_path = os.path.join(cat_dir, img_name)
            count = process_image(img_path, category, preview=True)
            total += count
            time.sleep(2)  # Rate limiting

    print(f"\n{'=' * 60}")
    print(f"  TEST COMPLETE — {total} total annotations")
    print(f"  Check previews in: {os.path.abspath(PREVIEW_DIR)}")
    print(f"{'=' * 60}")


def annotate_category(category):
    """Annotate all images in a category."""
    cat_dir = os.path.join(IMAGES_DIR, category)
    if not os.path.isdir(cat_dir):
        print(f"Category directory not found: {cat_dir}")
        return

    images = sorted([f for f in os.listdir(cat_dir) if f.endswith(".png")])
    print(f"\n[{category.upper()}] Annotating {len(images)} images...")

    total = 0
    for i, img_name in enumerate(images):
        img_path = os.path.join(cat_dir, img_name)
        print(f"\n  [{i+1}/{len(images)}]")
        count = process_image(img_path, category, preview=True)
        total += count
        time.sleep(1.5)  # Rate limiting

    print(f"\n  Done — {total} annotations from {len(images)} images")


def annotate_all():
    """Annotate all categories."""
    for category in sorted(os.listdir(IMAGES_DIR)):
        cat_dir = os.path.join(IMAGES_DIR, category)
        if os.path.isdir(cat_dir):
            annotate_category(category)


def main():
    parser = argparse.ArgumentParser(description="Auto-annotate ESO screenshots with Claude Vision")
    parser.add_argument("--test", action="store_true", help="Test mode: 2 images per category")
    parser.add_argument("--category", type=str, help="Annotate a specific category")
    parser.add_argument("--all", action="store_true", help="Annotate all categories")
    parser.add_argument("--image", type=str, help="Annotate a single image")
    args = parser.parse_args()

    if not POLZA_API_KEY:
        print("ERROR: POLZA_API_KEY not found in .env")
        sys.exit(1)

    print(f"API: {POLZA_BASE_URL}")
    print(f"Images: {os.path.abspath(IMAGES_DIR)}")
    print(f"Annotations: {os.path.abspath(ANNOTATIONS_DIR)}")
    print(f"Previews: {os.path.abspath(PREVIEW_DIR)}")
    print()

    if args.test:
        test_mode()
    elif args.category:
        annotate_category(args.category)
    elif args.all:
        annotate_all()
    elif args.image:
        process_image(args.image, preview=True)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
