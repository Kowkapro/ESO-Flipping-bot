-- FishingNav v2: exports player data via SavedVariables + pixel bridge
-- Pixel bridge: 5 colored 8x8px blocks at top-left corner, read by Python bot
-- SavedVariables kept for backward compatibility and debugging

local ADDON_NAME = "FishingNav"
local UPDATE_INTERVAL_MS = 500

FishingNav_Data = {}

----------------------------------------------------------------------
-- Pixel Bridge: 5 blocks encoding player state as RGB colors
----------------------------------------------------------------------
local pixels = {}
local pixelBridgeReady = false

-- State flags (updated by events + polling)
local flags = {
    inCombat = false,
    hasInteraction = false,
    isFishing = false,
    reticleHidden = false,
    isSwimming = false,
    isHidden = false,
}

local function CreatePixelBlocks()
    -- Top-level window as container (ensures visibility above HUD)
    local tlw = WINDOW_MANAGER:CreateTopLevelWindow("FN_TopLevel")
    tlw:SetAnchor(TOPLEFT, GuiRoot, TOPLEFT, 0, 0)
    tlw:SetDimensions(40, 8)
    tlw:SetHidden(false)

    for i = 0, 4 do
        local px = WINDOW_MANAGER:CreateControl("FN_Px" .. i, tlw, CT_BACKDROP)
        px:SetDimensions(8, 8)
        px:SetAnchor(TOPLEFT, tlw, TOPLEFT, i * 8, 0)
        px:SetCenterColor(1, 0, 0, 1)  -- DEBUG: start red
        px:SetEdgeColor(0, 0, 0, 0)    -- no border
        px:SetHidden(false)
        pixels[i] = px
    end
    pixelBridgeReady = true
    d("FishingNav: pixel blocks created (" .. #pixels + 1 .. " blocks)")
end

local function SetBlockColor(index, r, g, b)
    pixels[index]:SetCenterColor(r / 255, g / 255, b / 255, 1)
end

local function PixelUpdate()
    if not pixelBridgeReady then return end

    local _, worldX, _, worldY = GetUnitRawWorldPosition("player")
    local _, _, heading = GetMapPlayerPosition("player")

    -- Poll interaction state every frame
    local _, interactableName = GetGameCameraInteractableActionInfo()
    flags.hasInteraction = (interactableName ~= nil and interactableName ~= "")
    flags.isFishing = (interactableName ~= nil and string.find(interactableName, "рыбалк") ~= nil)
    flags.reticleHidden = IsReticleHidden()
    flags.isSwimming = IsUnitSwimming("player")
    flags.isHidden = (GetUnitStealthState("player") == STEALTH_STATE_HIDDEN or
                      GetUnitStealthState("player") == STEALTH_STATE_HIDDEN_ALMOST_DETECTED)

    -- Encode worldX as 3 bytes (0 — 16,777,215)
    local xInt = math.floor(worldX)
    local xH = math.floor(xInt / 65536) % 256
    local xM = math.floor(xInt / 256) % 256
    local xL = xInt % 256

    -- Encode worldY as 3 bytes
    local yInt = math.floor(worldY)
    local yH = math.floor(yInt / 65536) % 256
    local yM = math.floor(yInt / 256) % 256
    local yL = yInt % 256

    -- Encode heading (2 bytes) + flags (1 byte)
    local hInt = math.floor((heading or 0) / (2 * math.pi) * 65535)
    hInt = math.min(math.max(hInt, 0), 65535)
    local hH = math.floor(hInt / 256)
    local hL = hInt % 256

    local flagByte = (flags.inCombat and 1 or 0)
                   + (flags.hasInteraction and 2 or 0)
                   + (flags.isFishing and 4 or 0)
                   + (flags.reticleHidden and 8 or 0)
                   + (flags.isSwimming and 16 or 0)
                   + (flags.isHidden and 32 or 0)

    -- Checksum: XOR of all 9 data bytes (blocks 1-3)
    local checksum = BitXor(xH, BitXor(xM, BitXor(xL,
                    BitXor(yH, BitXor(yM, BitXor(yL,
                    BitXor(hH, BitXor(hL, flagByte))))))))

    -- Block 0: sync marker 0xAA, 0x55, 0xCC
    SetBlockColor(0, 0xAA, 0x55, 0xCC)
    -- Block 1: worldX
    SetBlockColor(1, xH, xM, xL)
    -- Block 2: worldY
    SetBlockColor(2, yH, yM, yL)
    -- Block 3: heading + flags
    SetBlockColor(3, hH, hL, flagByte)
    -- Block 4: checksum
    SetBlockColor(4, checksum, 0, 0)
end

----------------------------------------------------------------------
-- SavedVariables export (kept from v1 for debugging)
----------------------------------------------------------------------
local function UpdatePlayerData()
    local _, worldX, worldZ, worldY = GetUnitRawWorldPosition("player")
    local mapX, mapY, heading = GetMapPlayerPosition("player")
    local zoneIndex = GetUnitZoneIndex("player")
    local zoneId = GetZoneId(zoneIndex)
    local zoneName = GetZoneNameById(zoneId)
    local mapName = GetMapName()

    FishingNav_Data = {
        worldX = worldX, worldY = worldY, worldZ = worldZ,
        mapX = mapX, mapY = mapY, heading = heading,
        zoneId = zoneId, zoneName = zoneName, mapName = mapName,
        inCombat = flags.inCombat, timestamp = GetTimeStamp(),
    }

    local mgr = GetAddOnManager()
    if mgr and mgr.RequestAddOnSavedVariablesPrioritySave then
        mgr:RequestAddOnSavedVariablesPrioritySave(ADDON_NAME)
    end
end

----------------------------------------------------------------------
-- Event handlers
----------------------------------------------------------------------
local function OnCombatState(_, inCombat)
    flags.inCombat = inCombat
end

local function OnPlayerActivated()
    -- Pixel bridge (only create once — OnPlayerActivated fires on /reloadui too)
    if not pixelBridgeReady then
        CreatePixelBlocks()
    end
    EVENT_MANAGER:RegisterForUpdate(ADDON_NAME .. "_Pixels", 0, PixelUpdate)

    -- SavedVariables (legacy, every 500ms)
    EVENT_MANAGER:UnregisterForUpdate(ADDON_NAME)
    EVENT_MANAGER:RegisterForUpdate(ADDON_NAME, UPDATE_INTERVAL_MS, UpdatePlayerData)
    UpdatePlayerData()

    d("FishingNav v2: pixel bridge + tracking started")
end

local function OnAddOnLoaded(_, addonName)
    if addonName ~= ADDON_NAME then return end
    EVENT_MANAGER:UnregisterForEvent(ADDON_NAME, EVENT_ADD_ON_LOADED)
    EVENT_MANAGER:RegisterForEvent(ADDON_NAME, EVENT_PLAYER_ACTIVATED, OnPlayerActivated)
    EVENT_MANAGER:RegisterForEvent(ADDON_NAME, EVENT_PLAYER_COMBAT_STATE, OnCombatState)
end

EVENT_MANAGER:RegisterForEvent(ADDON_NAME, EVENT_ADD_ON_LOADED, OnAddOnLoaded)
