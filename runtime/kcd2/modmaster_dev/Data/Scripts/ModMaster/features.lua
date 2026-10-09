local MM_HOTKEYS={f2=113,f3=114,f4=115,f5=116,f6=117,f7=118,f8=119,f9=120,f10=121,f11=122}

function ModMasterDev:BindMenuKey(key)
    if not MM_HOTKEYS[key] or not System.ExecuteCommand then return self:Log("Unsupported menu hotkey") end
    if key==self.settings.noclipHotkey then return self:Log("Menu hotkey must differ from the Noclip hotkey") end
    local old=self.boundMenuKey
    if old and old~=key then System.ExecuteCommand("bind '" .. old .. "' ''") end
    System.ExecuteCommand("bind '" .. key .. "' 'mm_toggle'")
    self.boundMenuKey=key;self.settings.hotkey=key;self.settings.keyCode=MM_HOTKEYS[key]
    self:Log("Menu hotkey " .. key:upper() .. " (current session)")
end

ModMasterEspDefaultRange=100

-- Keeps the menu element on screen without the menu, so ESP labels can be drawn.
function ModMasterDev:Overlay(on)
    if self.opened or self.noclip or not UIAction then return end
    if not on then pcall(UIAction.HideElement,"ModMasterMenu",0);return end
    pcall(UIAction.ShowElement,"ModMasterMenu",0)
    if Script and Script.SetTimer then
        Script.SetTimer(150,function()
            if self.esp and not self.opened and not self.noclip then self:Guard(function() self:UI("Overlay",true) end) end
        end)
    end
end

function ModMasterDev:ToggleEsp()
    self.esp=not self.esp
    self.espRange=self.espRange or ModMasterEspDefaultRange
    self.espGeneration=(self.espGeneration or 0)+1
    self.espTargets=nil;self.espText=nil;self.espFrame=0
    if self.esp then
        self:EspTick(self.espGeneration)
    else
        self:Guard(function() self:UI("Esp","") end)
        self:Overlay(false)
    end
    self:Log("Entity ESP " .. (self.esp and "on" or "off") .. " (" .. self.espRange .. " m)")
end

function ModMasterDev:SetEspRange(value)
    local range=tonumber(value)
    if not range or range<5 or range>2000 then return self:Log("ESP range must be between 5 and 2000 m") end
    self.espRange=math.floor(range+0.5);self.espTargets=nil
    self:Log("ESP range " .. self.espRange .. " m")
end

function ModMasterDev:EspName(entity)
    local name=entity.GetName and entity:GetName() or "?"
    return (tostring(name):gsub("[|\n]"," "))
end

-- ProjectToScreen is unreliable outside the renderer, so project with the view camera first.
function ModMasterDev:EspCamera()
    local pos=System.GetViewCameraPos();local f=System.GetViewCameraDir()
    local fov=System.GetViewCameraFov and tonumber(System.GetViewCameraFov())
    local u=System.GetViewCameraUpDir and System.GetViewCameraUpDir() or {x=0,y=0,z=1}
    local r={x=f.y*u.z-f.z*u.y,y=f.z*u.x-f.x*u.z,z=f.x*u.y-f.y*u.x}
    local len=math.sqrt(r.x*r.x+r.y*r.y+r.z*r.z)
    if len<0.0001 then return {pos=pos,dir=f} end
    r={x=r.x/len,y=r.y/len,z=r.z/len}
    local up={x=r.y*f.z-r.z*f.y,y=r.z*f.x-r.x*f.z,z=r.x*f.y-r.y*f.x}
    return {pos=pos,dir=f,right=r,up=up,tan=fov and fov>0.1 and fov<3 and math.tan(fov/2) or nil}
end

function ModMasterDev:EspProject(cam,point)
    local v={x=point.x-cam.pos.x,y=point.y-cam.pos.y,z=point.z-cam.pos.z}
    local depth=v.x*cam.dir.x+v.y*cam.dir.y+v.z*cam.dir.z
    if depth<=0.2 then return nil end
    if cam.tan and cam.right then
        local x=(v.x*cam.right.x+v.y*cam.right.y+v.z*cam.right.z)/(depth*cam.tan*16/9)
        local y=(v.x*cam.up.x+v.y*cam.up.y+v.z*cam.up.z)/(depth*cam.tan)
        return 50+50*x,50-50*y
    end
    local ok,s=pcall(System.ProjectToScreen,point)
    if ok and type(s)=="table" and tonumber(s.x) and tonumber(s.y) and (s.x~=0 or s.y~=0) then return s.x,s.y end
end

function ModMasterDev:EspTargets()
    local p=self:PlayerEntity()
    if not p or not System.GetEntitiesInSphere then return {} end
    local targets={}
    for _,e in pairs(System.GetEntitiesInSphere(p:GetWorldPos(),self.espRange or ModMasterEspDefaultRange) or {}) do
        if type(e)=="table" and e.id~=p.id and (e.soul or e.actor or e.horse) and e.GetWorldPos then
            table.insert(targets,{entity=e,name=self:EspName(e),height=e.horse and 2.3 or 2.0})
        end
    end
    return targets
end

function ModMasterDev:EspLabels(targets)
    local p=self:PlayerEntity()
    if not p then return "" end
    local origin=p:GetWorldPos();local range=self.espRange or ModMasterEspDefaultRange
    local cam=self:EspCamera()
    local rows={}
    for _,t in ipairs(targets) do
        local okPos,pos=pcall(t.entity.GetWorldPos,t.entity)
        if okPos and type(pos)=="table" then
            local dx,dy,dz=pos.x-origin.x,pos.y-origin.y,pos.z-origin.z
            local dist=math.sqrt(dx*dx+dy*dy+dz*dz)
            if dist<=range then
                local x,y=self:EspProject(cam,{x=pos.x,y=pos.y,z=pos.z+t.height})
                if x and y and x>=0 and x<=100 and y>=0 and y<=100 then
                    table.insert(rows,{d=dist,line=string.format("%.1f|%.1f|%s  %dm",x,y,t.name,math.floor(dist+0.5))})
                end
            end
        end
    end
    table.sort(rows,function(a,b) return a.d<b.d end)
    local lines={}
    for i=1,math.min(#rows,60) do lines[i]=rows[i].line end
    return table.concat(lines,"\n")
end

-- Labels follow the camera every frame; the costly sphere query only runs a few times per second.
function ModMasterDev:EspTick(generation)
    if not self.esp or generation~=self.espGeneration then return end
    if not self.opened and not self.noclip then self:Overlay(true) end
    local ok,text=pcall(function()
        if self.opened then return "" end
        self.espFrame=(self.espFrame or 0)+1
        if not self.espTargets or self.espFrame%20==1 then self.espTargets=self:EspTargets() end
        return self:EspLabels(self.espTargets)
    end)
    if not ok then
        self.esp=false;self:Overlay(false)
        return self:Log("ESP stopped: " .. tostring(text))
    end
    if text~=self.espText then
        self.espText=text
        self:Guard(function() self:UI("Esp",text) end)
    end
    if Script and Script.SetTimer then Script.SetTimer(16,function() self:EspTick(generation) end) end
end

ModMasterPhotoRangeCVar="wh_photomode_MaxDistance"

-- F1 photo mode keeps its camera inside a small box around Henry; this widens that box.
function ModMasterDev:PhotoModeRange(unlimited)
    local get,set=System.GetCVar,System.SetCVar
    local function read()
        if type(get)~="function" then return nil end
        local ok,value=pcall(get,ModMasterPhotoRangeCVar)
        return ok and tonumber(value) or nil
    end
    if self.photoRangeDefault==nil then self.photoRangeDefault=read() end
    local wanted=unlimited and 100000 or (self.photoRangeDefault or 0)
    if wanted<=0 then return self:Log("Photo mode range: default unknown, nothing changed") end
    if type(set)=="function" then pcall(set,ModMasterPhotoRangeCVar,wanted) end
    if read()~=wanted and System.ExecuteCommand then
        pcall(System.ExecuteCommand,ModMasterPhotoRangeCVar .. " " .. tostring(wanted))
    end
    local now=read()
    if now==wanted then
        self:Log("Photo mode range " .. (unlimited and "unlimited" or "back to default") .. " (" .. tostring(now) .. " m). Press F1.")
    else
        self:Log("The game did not accept the photo mode range (" .. tostring(now) .. ")")
    end
end

-- Console binds bypass ActionMapManager, so they still fire while the menu has frozen input.
function ModMasterDev:BindNoclipKey(key)
    if not MM_HOTKEYS[key] or not System.ExecuteCommand then return self:Log("Unsupported Noclip hotkey") end
    if key==self.settings.hotkey then return self:Log("Noclip hotkey must differ from the menu hotkey") end
    local old=self.boundNoclipKey
    if old and old~=key then System.ExecuteCommand("bind '" .. old .. "' ''") end
    System.ExecuteCommand("bind '" .. key .. "' 'mm_noclip'")
    self.boundNoclipKey=key;self.settings.noclipHotkey=key
    self:Log("Noclip hotkey " .. key:upper() .. " (current session, works even with the menu closed)")
end

-- The open menu always owns gameplay input. Toggling FreezeInput while a modal
-- FlashUI element is visible makes the engine close it.
function ModMasterDev:ApplyMenuInput()
    self:ReleaseMenuInput()
    if not self.opened then return end
    local rules=self:Rules()
    self.actionMapOwned=true;ActionMapManager.EnableActionMapManager(false,true)
    self.inputOwner=rules;rules:FreezeInput(true)
end

function ModMasterDev:GiveSelectedItem()
    local item=self:FilteredAssets()[self.selected]
    local p=self:PlayerEntity();local inv=p and p.inventory
    if not item or item.spawn_type~="inventory_item" then return self:Log("Select an inventory item first") end
    if not inv or not inv.CreateItem or not inv.GetCountOfClass then return self:Log("Native item inventory API unavailable") end
    local before=inv:GetCountOfClass(item.item_guid)
    if type(before)~="number" then return self:Log("Cannot verify item count; unchanged") end
    -- ItemUtils.CreateInvItem(guid, health, amount)
    inv:CreateItem(item.item_guid,1,1)
    if Game and type(Game.ShowItemsTransfer)=="function" then
        pcall(Game.ShowItemsTransfer,item.item_guid,1)
    end
    local after=inv:GetCountOfClass(item.item_guid)
    if type(after)=="number" and after==before+1 then
        self:Log("Added to inventory: " .. item.name)
    else self:Log("Inventory did not confirm item creation; check the installed item database") end
end

function ModMasterDev:EquipSelectedItem()
    local item=self:FilteredAssets()[self.selected]
    local p=self:PlayerEntity();local inv=p and p.inventory
    if not item or item.spawn_type~="inventory_item" then return self:Log("Select an inventory item first") end
    if not inv or not p.actor or not p.actor.EquipInventoryItem then return self:Log("Native equip API unavailable") end
    local count=inv.GetCountOfClass and inv:GetCountOfClass(item.item_guid) or 0
    if count==0 and inv.CreateItem then
        inv:CreateItem(item.item_guid,1,1)
        if Game and type(Game.ShowItemsTransfer)=="function" then
            pcall(Game.ShowItemsTransfer,item.item_guid,1)
        end
    end
    local itemId=inv.FindItem and inv:FindItem(item.item_guid)
    if not itemId and inv.GetItemTable then
        local items=inv:GetItemTable()
        if type(items)=="table" then
            for _,it in ipairs(items) do
                if type(it)=="table" and (it.classId==item.item_guid or it.class_id==item.item_guid) then
                    itemId=it.id or it.itemId
                    break
                end
            end
        end
    end
    if itemId then
        local ok,err=pcall(p.actor.EquipInventoryItem,p.actor,itemId)
        if ok then
            self:Log("Equipped: " .. item.name)
        else
            self:Log("Equip failed: " .. tostring(err))
        end
    else
        self:Log("Item not found in inventory: " .. item.name)
    end
end
