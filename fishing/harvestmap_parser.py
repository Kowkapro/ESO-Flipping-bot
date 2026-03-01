"""
HarvestMap SavedVariables parser for fishing hole positions.

Parses HarvestDC_SavedVars.lua (personal data) and HarvestDC_Data.lua (community data)
to extract fishing hole coordinates for bot navigation.

HarvestMap data format:
  - Personal (CSV): "worldX,worldY,worldZ,timestamp,version,0.0,0.0,flags"
  - Community (binary): 8 bytes per node (2B x, 2B y, 2B z, 2B day), coords * 0.2
  - Fishing pinTypeId = 8
  - Glenumbra zoneId = 3
"""

import os
import re
import struct

# HarvestMap constants
FISHING_PIN_TYPE = 8
DELETE_FLAG = 2

# Zone IDs from HarvestMap Serialization.lua
ZONE_IDS = {
    "glenumbra": 3,
    "stormhaven": 19,
    "rivenspire": 20,
    "alikr": 104,
    "bangkorai": 92,
}

SAVED_VARS_DIR = os.path.join(
    "d:", os.sep, "Documents", "Elder Scrolls Online", "live", "SavedVariables"
)


def parse_personal_node(csv_string):
    """Parse a single CSV node string from SavedVariables.

    Format: "worldX,worldY,worldZ,timestamp,version,0.0,0.0,flags"
    """
    parts = re.findall(r"-?\d*\.?\d+", csv_string)
    if len(parts) < 3:
        return None

    world_x = float(parts[0])
    world_y = float(parts[1])
    world_z = float(parts[2])
    flags = int(float(parts[7])) if len(parts) > 7 else 0

    if flags & DELETE_FLAG:
        return None

    return {"x": world_x, "y": world_y, "z": world_z}


def parse_community_data(binary_data):
    """Parse binary community data string (8 bytes per node).

    Each node: 2B worldX, 2B worldY, 2B worldZ, 2B discoveryDay
    Coordinates are stored as uint16, multiply by 0.2 for world units.
    """
    nodes = []
    if len(binary_data) % 8 != 0:
        return nodes

    for i in range(0, len(binary_data), 8):
        x1, x2, y1, y2, z1, z2, d1, d2 = struct.unpack(
            "8B", binary_data[i : i + 8]
        )
        world_x = (x1 * 256 + x2) * 0.2
        world_y = (y1 * 256 + y2) * 0.2
        world_z = (z1 * 256 + z2) * 0.2
        nodes.append({"x": world_x, "y": world_y, "z": world_z})

    return nodes


def parse_savedvars_file(filepath, zone_name="glenumbra"):
    """Parse a HarvestMap SavedVariables Lua file for fishing nodes.

    Looks for entries under [zoneId][map][8] (fishing pin type).
    Returns list of {x, y, z} dicts.
    """
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return []

    zone_id = ZONE_IDS.get(zone_name)
    if zone_id is None:
        print(f"Unknown zone: {zone_name}")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    nodes = []

    # Match fishing node entries: strings inside [8] = { ... } blocks
    # under the correct zone ID
    # Pattern: find zone block -> find map blocks -> find pinType 8 -> extract strings
    zone_pattern = rf"\[{zone_id}\]\s*=\s*\{{(.*?)\n\s*\}},"
    zone_match = re.search(zone_pattern, content, re.DOTALL)
    if not zone_match:
        print(f"No data for zone {zone_name} (id={zone_id})")
        return []

    zone_content = zone_match.group(1)

    # Find fishing pin type block [8] = { ... }
    fishing_pattern = r"\[8\]\s*=\s*\{(.*?)\},"
    fishing_match = re.search(fishing_pattern, zone_content, re.DOTALL)
    if not fishing_match:
        print(f"No fishing data for zone {zone_name}")
        return []

    fishing_content = fishing_match.group(1)

    # Extract all quoted strings (CSV node data)
    node_strings = re.findall(r'"([^"]+)"', fishing_content)
    for s in node_strings:
        node = parse_personal_node(s)
        if node:
            nodes.append(node)

    return nodes


def parse_community_file(filepath, zone_name="glenumbra"):
    """Parse a HarvestMap community data file for fishing nodes.

    Community data uses binary strings stored as Lua string literals.
    Returns list of {x, y, z} dicts.
    """
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return []

    zone_id = ZONE_IDS.get(zone_name)
    if zone_id is None:
        print(f"Unknown zone: {zone_name}")
        return []

    with open(filepath, "rb") as f:
        content = f.read()

    # Community data files contain binary Lua strings
    # The structure is similar but values are binary-encoded
    # For now, try to parse as SavedVars format first (community data
    # downloaded via addon may be stored in SavedVars format too)
    try:
        text_content = content.decode("utf-8", errors="ignore")
    except Exception:
        return []

    nodes = []

    # Look for zone block
    zone_pattern = rf"\[{zone_id}\]\s*=\s*\{{(.*?)\n\s*\}},"
    zone_match = re.search(zone_pattern, text_content, re.DOTALL)
    if not zone_match:
        return []

    zone_content = zone_match.group(1)

    # Look for fishing block [8]
    fishing_pattern = r"\[8\]\s*=\s*\"(.*?)\""
    fishing_match = re.search(fishing_pattern, zone_content, re.DOTALL)
    if fishing_match:
        # Binary string — decode Lua escape sequences
        lua_string = fishing_match.group(1)
        binary_data = decode_lua_binary_string(lua_string)
        nodes = parse_community_data(binary_data)

    return nodes


def decode_lua_binary_string(lua_str):
    """Decode a Lua binary string with escape sequences like \\123."""
    result = bytearray()
    i = 0
    while i < len(lua_str):
        if lua_str[i] == "\\" and i + 1 < len(lua_str):
            # Check for numeric escape \DDD
            digits = ""
            j = i + 1
            while j < len(lua_str) and j < i + 4 and lua_str[j].isdigit():
                digits += lua_str[j]
                j += 1
            if digits:
                result.append(int(digits) % 256)
                i = j
            else:
                # Other escape sequences
                esc_char = lua_str[i + 1]
                escape_map = {"n": 10, "t": 9, "r": 13, "\\": 92, '"': 34}
                result.append(escape_map.get(esc_char, ord(esc_char)))
                i += 2
        else:
            result.append(ord(lua_str[i]))
            i += 1
    return bytes(result)


def get_fishing_holes(zone_name="glenumbra"):
    """Get all known fishing hole positions for a zone.

    Tries both personal SavedVars and community data files.
    Returns deduplicated list of {x, y, z} dicts.
    """
    all_nodes = []

    # Personal data
    personal_file = os.path.join(SAVED_VARS_DIR, "HarvestDC_SavedVars.lua")
    personal_nodes = parse_savedvars_file(personal_file, zone_name)
    all_nodes.extend(personal_nodes)
    if personal_nodes:
        print(f"Personal data: {len(personal_nodes)} fishing holes")

    # Community data
    community_file = os.path.join(SAVED_VARS_DIR, "HarvestDC_Data.lua")
    community_nodes = parse_community_file(community_file, zone_name)
    all_nodes.extend(community_nodes)
    if community_nodes:
        print(f"Community data: {len(community_nodes)} fishing holes")

    if not all_nodes:
        print(f"No fishing hole data found for {zone_name}.")
        print(f"Install HarvestMapDC addon and download community data.")
        return []

    # Deduplicate (nodes within 5 units are considered the same)
    unique = deduplicate_nodes(all_nodes, threshold=5.0)
    print(f"Total unique fishing holes: {len(unique)}")
    return unique


def deduplicate_nodes(nodes, threshold=5.0):
    """Remove duplicate nodes that are within threshold distance of each other."""
    unique = []
    for node in nodes:
        is_dup = False
        for existing in unique:
            dx = node["x"] - existing["x"]
            dy = node["y"] - existing["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(node)
    return unique


if __name__ == "__main__":
    print("=== HarvestMap Fishing Hole Parser ===\n")

    holes = get_fishing_holes("glenumbra")

    if holes:
        print(f"\nFirst 10 fishing holes in Glenumbra:")
        for i, hole in enumerate(holes[:10]):
            print(f"  #{i+1}: x={hole['x']:.1f}, y={hole['y']:.1f}, z={hole['z']:.1f}")
    else:
        print("\nNo data yet. Steps:")
        print("1. Install HarvestMapDC via Minion")
        print("2. Download HarvestMap community data from ESOUI")
        print("3. Place data files in SavedVariables folder")
        print("4. Run ESO, visit Glenumbra, then exit")
        print("5. Run this script again")
