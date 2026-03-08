"""Debug: print raw pixel values of all 5 pixel bridge blocks."""
import mss
import time
from PIL import ImageGrab

BLOCK_CENTERS = [(i * 8 + 4, 4) for i in range(5)]

with mss.mss() as sct:
    monitor = sct.monitors[1]
    region = {
        "left": monitor["left"],
        "top": monitor["top"],
        "width": 40,
        "height": 8,
    }

    print("Reading pixel bridge blocks (mss vs ImageGrab)...")
    print("Switch to ESO! Reading in 3 seconds...")
    time.sleep(3)

    for attempt in range(10):
        # mss read
        img_mss = sct.grab(region)
        mss_blocks = [img_mss.pixel(bx, by) for bx, by in BLOCK_CENTERS]

        # ImageGrab read
        img_pil = ImageGrab.grab(bbox=(0, 0, 40, 8))
        pil_blocks = [img_pil.getpixel((bx, by)) for bx, by in BLOCK_CENTERS]

        print(f"\n--- Read {attempt + 1} ---")
        for i in range(5):
            mr, mg, mb = mss_blocks[i][:3]
            pr, pg, pb = pil_blocks[i][:3]
            match = "OK" if (mr, mg, mb) == (pr, pg, pb) else "MISMATCH!"
            print(f"  Block {i}: mss=({mr:3d},{mg:3d},{mb:3d})  PIL=({pr:3d},{pg:3d},{pb:3d})  {match}")

        # Specifically highlight block 4 green (free_slots)
        print(f"  >> free_slots: mss={mss_blocks[4][1]}, PIL={pil_blocks[4][1]}")

        time.sleep(0.5)
