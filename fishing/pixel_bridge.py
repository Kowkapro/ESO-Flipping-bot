# pixel_bridge.py — reads FishingNav v2 pixel blocks from screen
# 5 blocks (8x8px each) at top-left corner encode player state as RGB colors

import math
import time
from dataclasses import dataclass

import mss


@dataclass
class PlayerState:
    x: float           # world X coordinate
    y: float           # world Y coordinate
    heading: float     # radians, 0=North, CW
    in_combat: bool
    has_interaction: bool
    is_fishing: bool
    reticle_hidden: bool


# Center pixel of each 8x8 block: (x, y) offsets from top-left
BLOCK_CENTERS = [(i * 8 + 4, 4) for i in range(5)]
SYNC_MARKER = (0xAA, 0x55, 0xCC)
SYNC_TOLERANCE = 2


def read_player_state(sct: mss.mss, monitor: dict) -> PlayerState | None:
    """Read pixel bar from top-left corner, decode and validate."""
    region = {
        "left": monitor["left"],
        "top": monitor["top"],
        "width": 40,
        "height": 8,
    }
    img = sct.grab(region)

    # Sample center pixel of each 8x8 block
    blocks = []
    for bx, by in BLOCK_CENTERS:
        # mss pixel() returns (R, G, B)
        pixel = img.pixel(bx, by)
        blocks.append(pixel)

    # Validate sync marker (block 0) with tolerance
    for i in range(3):
        if abs(blocks[0][i] - SYNC_MARKER[i]) > SYNC_TOLERANCE:
            return None

    # Extract data bytes from blocks 1-3
    r1, g1, b1 = blocks[1]  # worldX
    r2, g2, b2 = blocks[2]  # worldY
    r3, g3, b3 = blocks[3]  # heading + flags

    # Validate checksum (block 4)
    data_bytes = [r1, g1, b1, r2, g2, b2, r3, g3, b3]
    checksum = 0
    for b in data_bytes:
        checksum ^= b
    if checksum != blocks[4][0]:
        return None

    # Decode values
    world_x = r1 * 65536 + g1 * 256 + b1
    world_y = r2 * 65536 + g2 * 256 + b2
    heading_int = r3 * 256 + g3
    heading = heading_int / 65535.0 * 2 * math.pi
    flags = b3

    return PlayerState(
        x=float(world_x),
        y=float(world_y),
        heading=heading,
        in_combat=bool(flags & 1),
        has_interaction=bool(flags & 2),
        is_fishing=bool(flags & 4),
        reticle_hidden=bool(flags & 8),
    )


if __name__ == "__main__":
    print("Pixel Bridge reader — press Ctrl+C to stop", flush=True)
    print("Waiting for FishingNav v2 pixel bar...", flush=True)
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        print(f"Monitor: {monitor}", flush=True)
        detected = 0
        missed = 0
        while True:
            state = read_player_state(sct, monitor)
            if state:
                detected += 1
                print(
                    f"X={state.x:.0f} Y={state.y:.0f} "
                    f"H={math.degrees(state.heading):.1f}\u00b0 "
                    f"combat={state.in_combat} interact={state.has_interaction} "
                    f"fish={state.is_fishing} reticle={state.reticle_hidden} "
                    f"[ok:{detected} miss:{missed}]",
                    flush=True,
                )
            else:
                missed += 1
                if missed % 10 == 0:
                    print(f"-- pixel bar not detected (miss:{missed}) --", flush=True)
            time.sleep(0.1)
