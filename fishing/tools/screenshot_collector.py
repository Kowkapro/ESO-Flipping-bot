"""
Screenshot Collector v3 — collect training data for YOLO11 model.

Run this while playing ESO. Press hotkeys to save screenshots
into categorized folders for later annotation in CVAT.

Categories aligned with model v3 classes (numpad keys to avoid ESO conflicts):
  Num1 — MAP: map open with blue hooks, player icon, waypoint pin
  Num2 — COMPASS: compass bar with waypoint marker AND/OR quest markers
  Num3 — FISHING: near fishing hole (bubbles, fishing prompt visible)
  Num4 — NPC: near NPC/wayshrine/chest (non-fishing interaction prompts)
  Num5 — COMBAT: enemies, HP bars, combat situations
  Num6 — RUNNING: sprinting to waypoint (compass + world view)
  Num7 — GENERAL: anything else useful for training
  Num0 — STOP

Screenshots are saved to: fishing/training/screenshots/{category}/
"""

import os
import time
import queue
import mss
import keyboard
from PIL import Image
from datetime import datetime


# ── Settings ─────────────────────────────────────────────────────────
MONITOR_INDEX = 1
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "training", "screenshots")
CATEGORIES = [
    "map",          # F1: Map with blue hooks + player icon + waypoint pin
    "compass",      # F2: Compass bar (waypoint marker, quest markers, or both)
    "fishing",      # F3: Near fishing hole (bubbles, "[E] Место рыбалки...")
    "npc",          # F4: Near NPC/wayshrine/chest ("[E] Поговорить" etc.)
    "combat",       # F5: Enemies, HP bars, combat
    "running",      # F6: Running to waypoint (compass + world)
    "general",      # F7: Anything else
]

HOTKEYS = {
    "num 1": "map",
    "num 2": "compass",
    "num 3": "fishing",
    "num 4": "npc",
    "num 5": "combat",
    "num 6": "running",
    "num 7": "general",
}

# ── State ────────────────────────────────────────────────────────────
running = True
counts = {cat: 0 for cat in CATEGORIES}
capture_queue = queue.Queue()


def ensure_dirs():
    """Create directories if they don't exist."""
    for cat in CATEGORIES:
        path = os.path.join(BASE_DIR, cat)
        os.makedirs(path, exist_ok=True)
        counts[cat] = len([f for f in os.listdir(path) if f.endswith(".png")])


def make_handler(category):
    def handler(event):
        capture_queue.put(category)
    return handler


def on_stop(event):
    global running
    running = False
    capture_queue.put(None)
    print("\n[Num0] Stopping...")


def main():
    global running

    ensure_dirs()

    print("=" * 60)
    print("  ESO Screenshot Collector v3 — Model v3 Training Data")
    print("=" * 60)
    print(f"Save directory: {os.path.abspath(BASE_DIR)}")
    print()
    print("Existing screenshots:")
    total_existing = 0
    for cat in CATEGORIES:
        print(f"  {cat}: {counts[cat]} images")
        total_existing += counts[cat]
    print(f"  TOTAL: {total_existing} images")
    print()
    print("Controls (numpad, press while ESO is focused):")
    print("  Num1 — MAP       (map open: blue hooks, player icon, waypoint pin)")
    print("  Num2 — COMPASS   (compass: waypoint marker, quest markers, both)")
    print('  Num3 — FISHING   (near hole: bubbles, "[E] Место рыбалки...")')
    print('  Num4 — NPC       (near NPC/shrine: "[E] Поговорить", "[E] Путешествовать")')
    print("  Num5 — COMBAT    (enemies, HP bars, fighting)")
    print("  Num6 — RUNNING   (sprinting with compass visible)")
    print("  Num7 — GENERAL   (anything else)")
    print("  Num0 — STOP")
    print()
    print("Tips for v3 training data:")
    print("  MAP:     Zoom in different spots, vary player position")
    print("           Need 80+ screenshots to cover all hook positions")
    print("  COMPASS: Capture waypoint + quest markers separately AND together")
    print("           Vary distance to waypoint (close/medium/far)")
    print("  FISHING: Different water types, angles, time of day")
    print("  NPC:     Different NPCs, wayshrines, crafting stations")
    print()

    sct = mss.mss()
    monitor = sct.monitors[MONITOR_INDEX]
    print(f"Monitor: {monitor['width']}x{monitor['height']}")
    print("Waiting for hotkeys...\n")

    for key, category in HOTKEYS.items():
        keyboard.on_press_key(key, make_handler(category), suppress=False)
    keyboard.on_press_key("num 0", on_stop, suppress=False)

    try:
        while running:
            try:
                category = capture_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if category is None:
                break

            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{category}_{timestamp}.png"
            filepath = os.path.join(BASE_DIR, category, filename)

            img.save(filepath)
            counts[category] += 1
            print(f"  [{category.upper()}] Saved #{counts[category]}: {filename}")

    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        print()
        print("Final counts:")
        for cat in CATEGORIES:
            print(f"  {cat}: {counts[cat]} images")
        total = sum(counts.values())
        print(f"  TOTAL: {total} images")
        print("Done.")


if __name__ == "__main__":
    main()
