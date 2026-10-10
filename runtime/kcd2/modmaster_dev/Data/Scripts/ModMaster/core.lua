ModMasterDev = {version="0.7.0", registryVersion=1, opened=false, assets={},
    spawns={}, selected=1, spawnSelected=1, tab="ASSETS", search="", category="", modFilter="",
    serial=0, walkers={}, timer=nil, message="Runtime loaded; in-game acceptance pending", locations={},
    settings={hotkey="f5",keyCode=116,noclipHotkey="f4",hudEnabled=true,freecamSpeed=5.0,fastMult=4.0,slowMult=0.25}}

function ModMasterDev:Log(text)
    self.message = tostring(text)
    if System and System.LogAlways then System.LogAlways("[ModMaster] " .. self.message) end
end

-- Monotonic seconds for frame-rate independent movement.
function ModMasterDev:Now()
    if System and System.GetCurrAsyncTime then
        local ok,t=pcall(System.GetCurrAsyncTime)
        if ok and type(t)=="number" then return t end
    end
    if System and System.GetCurrTime then
        local ok,t=pcall(System.GetCurrTime)
        if ok and type(t)=="number" then return t end
    end
    return os.clock()
end

function ModMasterDev:Guard(fn)
    local ok, result = pcall(fn)
    if not ok then self:Log("Operation failed: " .. tostring(result)); return nil end
    return result
end

function ModMasterDev:LoadRegistry()
    ModMasterRegistry = nil
    local ok, err = pcall(Script.ReloadScript, "Scripts/ModMaster/registry.lua")
    local data = ModMasterRegistry
    if not ok or type(data) ~= "table" or data.format_version ~= self.registryVersion or
        data.runtime_version ~= self.version or type(data.mods) ~= "table" then
        self.assets = {}; self:Log("Registry invalid/incompatible; spawning disabled: " .. tostring(err)); return false
    end
    if #data.mods > 256 then self:Log("Registry mod limit exceeded"); return false end
    for _, mod in ipairs(data.mods) do
        if type(mod) ~= "table" or type(mod.id) ~= "string" or type(mod.assets) ~= "table" then
            self.assets={}; self:Log("Malformed mod registry"); return false
        end
    end
    -- Skip bad entries instead of discarding the whole registry.
    local assets, keys = {}, {}
    local counts = {static_prop=0, inventory_item=0, soul=0, unsupported=0, vanilla=0, custom=0}
    local categories = {}
    for _, mod in ipairs(data.mods) do
        for _, asset in ipairs(mod.assets) do
            local function reject(reason)
                counts.unsupported = counts.unsupported + 1
                -- Cap per-entry logging; the summary carries the total.
                if counts.unsupported <= 20 then self:Log(reason) end
            end
            if type(asset) ~= "table" or type(asset.id) ~= "string" or type(asset.name) ~= "string" then
                reject("Registry entry skipped (" .. mod.id .. "): missing id/name")
            elseif asset.spawn_type == "soul" and not ((type(asset.soul_guid) == "string" and
                asset.soul_guid:match("^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$")) or
                (type(asset.archetype) == "string" and asset.archetype:match("^[%w_]+$"))) then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): soul needs a GUID or archetype")
            elseif asset.spawn_type == "soul" and asset.model_path ~= nil and not (type(asset.model_path) == "string" and
                asset.model_path:lower():sub(-4) == ".cdf" and not asset.model_path:find("..", 1, true) and
                not asset.model_path:find(":", 1, true) and asset.model_path:sub(1,1) ~= "/") then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): creature model must be a .cdf")
            elseif asset.spawn_type == "soul" and not self:ValidCreatureValues(asset) then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): invalid health or stats")
            elseif asset.spawn_type == "soul" and asset.entity_class ~= nil and
                not (type(asset.entity_class) == "string" and asset.entity_class:match("^[%w_]+$")) then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): invalid entity_class")
            elseif asset.spawn_type ~= "static_prop" and asset.spawn_type ~= "inventory_item" and asset.spawn_type ~= "soul" then
                reject("Registry entry skipped (" .. mod.id .. ":" .. tostring(asset.id) .. "): unsupported spawn_type")
            elseif asset.spawn_type == "static_prop" and (type(asset.model_path) ~= "string" or
                asset.model_path:find("..", 1, true) or asset.model_path:find(":", 1, true) or
                asset.model_path:sub(1,1) == "/" or
                (asset.model_path:lower():sub(-4) ~= ".cgf" and asset.model_path:lower():sub(-4) ~= ".cdf")) then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): unsafe/invalid model_path")
            elseif asset.spawn_type == "inventory_item" and (type(asset.item_guid) ~= "string" or
                not asset.item_guid:match("^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$")) then
                reject("Registry entry skipped (" .. mod.id .. ":" .. asset.id .. "): invalid item_guid")
            else
                local key = mod.id .. ":" .. asset.id
                if keys[key] then
                    reject("Registry entry skipped (" .. key .. "): duplicate id")
                elseif #assets >= 65536 then
                    reject("Registry entry skipped (" .. key .. "): 65536 asset cap reached")
                else
                    keys[key] = true; asset.mod = mod.id; asset.modName = mod.name or mod.id
                    table.insert(assets, asset)
                    counts[asset.spawn_type] = counts[asset.spawn_type] + 1
                    if asset.source == "base_game" or mod.id == "base_game" then counts.vanilla = counts.vanilla + 1
                    else counts.custom = counts.custom + 1 end
                    categories[asset.category or "uncategorized"] = (categories[asset.category or "uncategorized"] or 0) + 1
                end
            end
        end
    end
    self.assets = assets; self.registry = data; self.selected = 1
    local catList = {}
    for name, n in pairs(categories) do table.insert(catList, name .. "=" .. n) end
    self:Log(string.format(
        "[RUNTIME REGISTRY] Total Entries: %d | Spawnable: %d | Vanilla: %d | Custom: %d | Unsupported: %d | Categories: %s",
        #assets + counts.unsupported, #assets, counts.vanilla, counts.custom, counts.unsupported, table.concat(catList, ", ")))
    return true
end

function ModMasterDev:ValidCreatureValues(asset)
    if asset.health ~= nil and (type(asset.health) ~= "number" or asset.health < 1 or asset.health > 10000) then return false end
    if asset.follow ~= nil and type(asset.follow) ~= "boolean" then return false end
    if asset.calm ~= nil and type(asset.calm) ~= "boolean" then return false end
    if asset.gaits ~= nil then
        if type(asset.gaits) ~= "table" then return false end
        for gait, anim in pairs(asset.gaits) do
            if (gait ~= "idle" and gait ~= "walk" and gait ~= "trot" and gait ~= "run") or type(anim) ~= "string"
                or not anim:match("^[%w_]+$") then
                return false
            end
        end
    end
    if asset.stats == nil then return true end
    if type(asset.stats) ~= "table" then return false end
    for name, level in pairs(asset.stats) do
        if (name ~= "strength" and name ~= "agility" and name ~= "vitality") or type(level) ~= "number" or level < 1 or level > 100 then
            return false
        end
    end
    return true
end

function ModMasterDev:FilteredAssets()
    local result={}
    for _,a in ipairs(self.assets) do
        local match=self.search=="" or (a.name .. " " .. a.id):lower():find(self.search:lower(),1,true)
        if match and (self.category=="" or self.category==a.category) and
            (self.modFilter=="" or self.modFilter==a.mod) then table.insert(result,a) end
    end
    return result
end

function ModMasterDev:SetFilter(search, category, mod)
    self.search=tostring(search or ""):sub(1,128)
    self.category=tostring(category or ""):sub(1,64)
    self.modFilter=tostring(mod or ""):sub(1,64); self.selected=1
    local matches=#self:FilteredAssets()
    self:Log(string.format(
        "[SEARCH] Query: %s | Registry Entries Searched: %d | Matches: %d | Returned: %d",
        self.search=="" and "(none)" or self.search, #self.assets, matches, math.min(6,matches)))
end

function ModMasterDev:Next(delta)
    if not self.opened then return end
    local list=self.tab=="ASSETS" and self:FilteredAssets() or self:FilteredSpawns()
    local key=self.tab=="ASSETS" and "selected" or "spawnSelected"
    self[key]=math.max(1,math.min(#list,self[key]+delta))
end

function ModMasterDev:Command(name, body, help)
    if System and type(System.AddCCommand)=="function" then
        System.AddCCommand(name, body, help)
    end
end

function ModMasterDev:Init()
    self.settings={hotkey="f5",keyCode=116,noclipHotkey="f4",hudEnabled=true,freecamSpeed=5.0,fastMult=4.0,slowMult=0.25}
    self:LoadRegistry()
    self:Command("mm_toggle", "ModMasterDev:Toggle()", "Toggle ModMaster development menu")
    self:Command("mm_assets", "ModMasterDev.tab='ASSETS'", "Open asset tab")
    self:Command("mm_spawns", "ModMasterDev.tab='SPAWNS'", "Open owned spawn tab")
    self:Command("mm_next", "ModMasterDev:Next(1)", "Select next menu row")
    self:Command("mm_previous", "ModMasterDev:Next(-1)", "Select previous menu row")
    self:Command("mm_spawn", "ModMasterDev:Guard(function() ModMasterDev:SpawnSelected('crosshair') end)", "Spawn selected static prop at camera ray hit")
    self:Command("mm_spawn_front", "ModMasterDev:Guard(function() ModMasterDev:SpawnSelected('front') end)", "Spawn selected static prop in front of player")
    self:Command("mm_despawn", "ModMasterDev:Guard(function() ModMasterDev:DespawnSelected() end)", "Remove only the selected ModMaster-created entity")
    self:Command("mm_clear", "ModMasterDev:Guard(function() ModMasterDev:Clear() end)", "Remove only tracked ModMaster-created entities")
    self:Command("mm_duplicate", "ModMasterDev:Guard(function() ModMasterDev:DuplicateSelected() end)", "Duplicate selected owned spawn")
    self:Command("mm_reset", "ModMasterDev:Guard(function() ModMasterDev:ResetSelected() end)", "Reset selected owned spawn transform")
    self:Command("mm_restore_world", "ModMasterDev:RestoreWorld()", "Restore this companion's time preview override")
    self:Command("mm_release_input", "ModMasterDev:CloseMenu()", "Emergency close and restore gameplay input")
    self:Command("mm_god", "ModMasterDev:Guard(function() ModMasterDev:ToggleGod() end)", "Toggle ModMaster God Mode (RPG buff)")
    self:Command("mm_freecam", "ModMasterDev:Guard(function() ModMasterDev:ToggleFreecam() end)", "Toggle ModMaster Freecam (fly, then return to the start position)")
    self:Command("mm_noclip", "ModMasterDev:Guard(function() ModMasterDev:ToggleNoclip() end)", "Toggle ModMaster Noclip (player moves through collision)")
    self:Command("mm_give", "ModMasterDev:Guard(function() ModMasterDev:GiveSelectedItem() end)", "Add selected game item to player inventory")
    self:Command("mm_equip", "ModMasterDev:Guard(function() ModMasterDev:EquipSelectedItem() end)", "Equip selected game item in player hands")
    self:Command("mm_controls", "ModMasterDev:BindControls()", "Opt in to Ctrl+navigation keybinds for this session")
    self:BindMenuKey("f5")
    self:BindNoclipKey("f4")
    self:Log("Runtime initialized v" .. self.version .. "; F5/F4 bindings requested; validation pending")
end

function ModMasterDev:BindControls()
    if not System.ExecuteCommand then return end
    for key,cmd in pairs({ctrl_pgdn="mm_next",ctrl_pgup="mm_previous",ctrl_enter="mm_spawn",ctrl_delete="mm_despawn"}) do
        System.ExecuteCommand("bind '" .. key .. "' '" .. cmd .. "'")
    end
    self:Log("Session controls requested: Ctrl+PgDn/PgUp/Enter/Delete")
end

function ModMasterDev:TimeOfDay(hour)
    hour=tonumber(hour)
    if not hour or hour<0 or hour>=24 then return self:Log("Hour must be in [0,24)") end
    if not Calendar or not Calendar.SetFakeTimeOfDay or not Calendar.IsFakedTimeOfDay or not Calendar.UnfakeTimeOfDay then
        return self:Log("Time preview API not exposed in this build")
    end
    if not self.timeOwned and Calendar.IsFakedTimeOfDay() then
        return self:Log("Another system already owns a time override; unchanged")
    end
    Calendar.SetFakeTimeOfDay(hour); self.timeOwned=true
    self:Log("Lighting-only time preview " .. hour .. "; RPG time unchanged")
end

function ModMasterDev:RestoreWorld()
    if self.timeOwned and Calendar and Calendar.UnfakeTimeOfDay then
        self:Guard(function() Calendar.UnfakeTimeOfDay() end); self.timeOwned=false
    end
end

function ModMasterDev:Shutdown()
    if self.CloseMenu then self:CloseMenu() end
    if self.RestorePlayerOptions then self:RestorePlayerOptions() end
    if self.uiRegistered and UIAction and UIAction.UnregisterElementListener then
        pcall(UIAction.UnregisterElementListener,self,"ModMasterMenu")
    end
    self.opened=false;self.tickGeneration=(self.tickGeneration or 0)+1
    if self.timer and Script.KillTimer then pcall(Script.KillTimer,self.timer) end
    self.timer=nil;self:RestoreWorld()
    self:Guard(function() self:Clear() end)
end

function ModMasterDev:Teleport(x,y,z)
    local p=g_localActor
    if not p or not p.SetWorldPos then return self:Log("Player transform API unavailable") end
    local pos=self:Vector(x,y,z)
    if not pos then return self:Log("Invalid finite XYZ") end
    p:SetWorldPos(pos); self:Log("Player teleported; normal game physics remain active")
end

function ModMasterDev:SaveLocation(name)
    local p=g_localActor
    if not p then return end
    name=tostring(name or ""):sub(1,64)
    if name=="" then return end
    self.locations[name]=self:CopyVector(p:GetWorldPos())
    self:Log("Location stored for this session: " .. name .. "; disk persistence not available")
end
