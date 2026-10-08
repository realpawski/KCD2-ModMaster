function ModMasterDev:UI(name, ...)
    return UIAction.CallFunction("ModMasterMenu",0,name,...)
end

function ModMasterDev:ReleaseMenuInput()
    if self.actionMapOwned then
        self.actionMapOwned=false
        local ok,err=pcall(ActionMapManager.EnableActionMapManager,true,true)
        if not ok then self:Log("ActionMap restoration error: " .. tostring(err)) end
    end
    if self.inputOwner then
        local rules=self.inputOwner
        self.inputOwner=nil
        local ok,err=pcall(function() rules:FreezeInput(false) end)
        if not ok then self:Log("Input restoration error: " .. tostring(err)) end
    end
end

function ModMasterDev:CloseMenu(reason)
    local wasOpen=self.opened
    self.opened=false;self.uiReady=false;self.toggleLock=true
    self.tickGeneration=(self.tickGeneration or 0)+1
    if self.timer and Script.KillTimer then pcall(Script.KillTimer,self.timer) end
    self.timer=nil
    -- Release input even when HideElement fails or recursively fires Hidden.
    self:ReleaseMenuInput()
    if self.noclip then
        local kind=self.noclip.kind
        self:Guard(function() self:UI(kind,true) end)
    elseif UIAction and UIAction.HideElement and not self.hiding then
        self.hiding=true;pcall(UIAction.HideElement,"ModMasterMenu",0);self.hiding=false
    end
    self:RestoreWorld()
    if Script and Script.SetTimer then Script.SetTimer(200,function() self.toggleLock=false end) end
    if wasOpen then self:Log(reason or "Menu closed; game input restored") end
end

function ModMasterDev:RefreshMenu()
    if not self.opened or not self.uiReady then return end
    local list={};local selected=1
    if self.tab=="ASSETS" then list=self:FilteredAssets();selected=self.selected
    elseif self.tab=="SPAWNS" then list=self:FilteredSpawns();selected=self.spawnSelected end
    selected=math.max(1,math.min(#list,selected))
    if self.tab=="ASSETS" then self.selected=selected else self.spawnSelected=selected end
    local start=math.floor((selected-1)/6)*6+1
    self:UI("Reset",self.tab,math.min(6,#list-start+1),#list>0 and selected or 0,#list)
    for i=start,math.min(#list,start+5) do
        local entry=list[i];local a=self.tab=="ASSETS" and entry or entry.asset
        self:UI("Row",i,a.name,a.mod .. " / " .. a.category .. (self.tab=="SPAWNS" and " / Entity " .. tostring(entry.id) or ""),i==selected)
    end
    local entry=list[selected]
    if entry then
        local a=self.tab=="ASSETS" and entry or entry.asset
        local pos={x=0,y=0,z=0};local rot={x=0,y=0,z=0};local scale=1
        if self.tab=="SPAWNS" then
            pos=entry.entity:GetWorldPos();rot=entry.entity:GetWorldAngles();scale=entry.entity:GetScale()
        end
        local typeDesc=a.spawn_type=="inventory_item" and "GAME ITEM (Equippable)" or "STATIC PROP"
        local idDesc=a.item_guid and ("GUID: " .. a.item_guid) or ("ID: " .. a.id)
        self:UI("Details",a.name .. "\n" .. idDesc .. "\nType: " .. typeDesc .. "\nStatus: " .. a.status,
            tostring(pos.x),tostring(pos.y),tostring(pos.z),tostring(rot.x),tostring(rot.y),tostring(rot.z),tostring(scale))
    end
    if self.tab=="PLAYER" then local god,noclip,freecam=self:PlayerOptions();self:UI("Player",god,noclip,freecam) end
    self:UI("Settings",self.settings.hotkey,self.settings.keyCode,self.settings.hudEnabled,
        tostring(self.settings.freecamSpeed),tostring(self.settings.fastMult),tostring(self.settings.slowMult),
        self.settings.noclipHotkey)
    self:UI("Status",self.message,"Runtime " .. self.version .. " | Assets " .. #self.assets .. " | Owned spawns " .. #self.spawns .. " | Freecam speed " .. self.settings.freecamSpeed)
end

function ModMasterDev:OnUIAction(element,instance,event,args)
    if element~="ModMasterMenu" or instance~=0 or event~="Action" then return end
    local payload=type(args)=="table" and args[1] or nil
    if type(payload)~="string" or #payload>2048 then return end
    if payload=="hidden" then
        if self.opened then self:CloseMenu("Menu hidden; input restored") end
        return
    end
    if payload=="ready" then
        if self.opened then self.uiReady=true;self:Log("Native menu ready; input captured");self:Guard(function() self:RefreshMenu() end) end
        return
    end
    if not self.opened then return end
    if payload=="close" then self:CloseMenu();return end
    local fields={}
    for value in (payload .. ";"):gmatch("(.-);") do table.insert(fields,value) end
    local action=fields[1]
    local function decode(value)
        -- AS2 escape(): ASCII filters only, never interpret strings as Lua/commands.
        return (tostring(value or ""):gsub("%%(%x%x)",function(h) return string.char(tonumber(h,16)) end))
    end
    local ok,err=pcall(function()
        if action:sub(1,4)=="tab:" then
            local tab=action:sub(5)
            if tab=="ASSETS" or tab=="SPAWNS" or tab=="PLAYER" or tab=="WORLD" or tab=="SETTINGS" then self.tab=tab end
        elseif action:sub(1,7)=="select:" then
            local index=tonumber(action:sub(8))
            local list=self.tab=="ASSETS" and self:FilteredAssets() or self:FilteredSpawns()
            if index and index%1==0 and index>=1 and index<=#list then
                if self.tab=="ASSETS" then self.selected=index else self.spawnSelected=index end
            end
        elseif action=="next" then self:Next(1)
        elseif action=="previous" then self:Next(-1)
        elseif action=="next_page" then self:Next(6)
        elseif action=="previous_page" then self:Next(-6)
        elseif action=="filter" and #fields==4 then self:SetFilter(decode(fields[2]),decode(fields[3]),decode(fields[4]))
        elseif action=="spawn" or action=="spawn_front" then self:SpawnSelected(action=="spawn" and "crosshair" or "front")
        elseif action=="despawn" then self:DespawnSelected()
        elseif action=="duplicate" then self:DuplicateSelected()
        elseif action=="reset" then self:ResetSelected()
        elseif action=="clear" then self:Clear()
        elseif action=="transform" and #fields==8 then self:TransformSelected(unpack(fields,2,8))
        elseif action:sub(1,7)=="search:" then
            if self.tab=="SPAWNS" then self.spawnSearch=decode(action:sub(8));self.spawnSelected=1 else self:SetFilter(decode(action:sub(8)),self.category,self.modFilter) end
        elseif action=="give" then self:GiveSelectedItem()
        elseif action=="equip" then self:EquipSelectedItem()
        elseif action=="freecam" then self:ToggleFreecam()
        elseif action=="noclip" then self:ToggleNoclip()
        elseif action=="hud_toggle" then self.settings.hudEnabled=not self.settings.hudEnabled
        elseif action=="settingvalue" and #fields==4 then
            local speed,fast,slow=tonumber(fields[2]),tonumber(fields[3]),tonumber(fields[4])
            if speed and speed>0 then self.settings.freecamSpeed=math.max(0.1,math.min(100,speed)) end
            if fast and fast>0 then self.settings.fastMult=math.max(0.1,math.min(20,fast)) end
            if slow and slow>0 then self.settings.slowMult=math.max(0.01,math.min(5,slow)) end
        elseif action:sub(1,7)=="hotkey:" then self:BindMenuKey(action:sub(8))
        elseif action:sub(1,14)=="noclip_hotkey:" then self:BindNoclipKey(action:sub(15))
        elseif action=="god" then self:ToggleGod()
        elseif action=="heal" then self:RestoreHealth()
        elseif action=="restore_player" then self:RestorePlayerOptions()
        elseif action:sub(1,5)=="time:" then self:TimeOfDay(action:sub(6))
        elseif action=="restore_world" then self:RestoreWorld();self:Log("Game lighting restored")
        else self:Log("Unsupported UI action") end
    end)
    if not ok then self:Log("UI operation failed: " .. tostring(err)) end
    local drawn,drawErr=pcall(function() self:RefreshMenu() end)
    if not drawn then self:CloseMenu("UI refresh failed; input restored: " .. tostring(drawErr)) end
end

function ModMasterDev:WatchMenu(generation,attempt)
    if not self.opened or generation~=self.tickGeneration then return end
    if not g_localActor or g_localActor~=self.menuActor then
        self:CloseMenu("World/player changed; menu closed")
        self:RestorePlayerOptions();return
    end
    local ok,err=pcall(function()
        local ready=UIAction.GetVariable("ModMasterMenu",0,"Ready")
        if ready==true or ready==1 or ready=="true" then
            if not self.uiReady then
                self.uiReady=true;self:Log("Native menu ready")
                self:RefreshMenu()
                self:Log("Menu text font: " .. tostring(UIAction.GetVariable("ModMasterMenu",0,"Font")))
            end
            local visible=UIAction.GetVariable("ModMasterMenu",0,"Visible")
            if visible==false or visible==0 or visible=="false" then self:CloseMenu("Menu hidden; input restored");return end
            local sequence=tonumber(UIAction.GetVariable("ModMasterMenu",0,"Sequence"))
            if sequence and sequence~=self.uiSequence then
                local payload=UIAction.GetVariable("ModMasterMenu",0,"Action")
                if type(payload)=="string" and #payload<=2048 then
                    self.uiSequence=sequence
                    self:OnUIAction("ModMasterMenu",0,"Action",{payload})
                    UIAction.SetVariable("ModMasterMenu",0,"Ack",sequence)
                end
            end
        end
    end)
    if not ok then self:CloseMenu("Native UI transport error; input restored: " .. tostring(err));return end
    if not self.opened then return end
    if attempt>=40 and not self.uiReady then
        self:CloseMenu("Native UI ready variable unavailable; input restored. Check FlashUI log.");return
    end
    self.timer=Script.SetTimer(50,function() self:WatchMenu(generation,attempt+1) end,nil,true)
end

function ModMasterDev:Toggle()
    if self.toggleLock then return end
    if self.opened then self:CloseMenu();return end
    if not g_localActor then return self:Log("Load a playable world before opening the menu") end
    local rules=self:Rules()
    if not UIAction or not UIAction.ShowElement or not UIAction.CallFunction or not UIAction.GetVariable or not UIAction.SetVariable or
        not rules or not rules.FreezeInput or not Script.SetTimer or
        not ActionMapManager or not ActionMapManager.EnableActionMapManager then
        return self:Log("Native UI/input API unavailable; menu stays closed to preserve control")
    end
    self.opened=true;self.uiReady=false;self.menuActor=g_localActor;self.uiSequence=self.uiSequence or 0
    self.toggleLock=true;Script.SetTimer(200,function() self.toggleLock=false end)
    self.tickGeneration=(self.tickGeneration or 0)+1
    local ok,err=pcall(function()
        self:ApplyMenuInput()
        UIAction.ShowElement("ModMasterMenu",0)
        self:WatchMenu(self.tickGeneration,0)
    end)
    if not ok then self:CloseMenu("Menu open failed; input restored: " .. tostring(err)) end
end
