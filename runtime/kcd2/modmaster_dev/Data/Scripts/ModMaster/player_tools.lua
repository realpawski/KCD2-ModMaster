function ModMasterDev:PlayerEntity()
    if player and g_localActor and player.id==g_localActor.id then return player end
    return g_localActor
end

-- Vanilla player_immortality_nonpersistent; never written to saves.
ModMasterGodGuid="44e1ccc9-9252-48a9-922d-2ae4523c69a3"
-- Vanilla remove_injuries buff from Libs/Tables/rpg/buff.xml.
ModMasterRemoveInjuriesGuid="46683e3b-e261-412f-b402-99ee17dda62a"
ModMasterColliderNormal=0
ModMasterColliderNoclip=5

function ModMasterDev:Rules() return g_gameRules and g_gameRules.game end

function ModMasterDev:PlayerOptions()
    local p=self:PlayerEntity();local god="unavailable"
    if p and p.soul and p.soul.AddBuff and p.soul.RemoveAllBuffsByGuid then
        god=(self.godOwner==p) and "ON" or "OFF"
    end
    return god, self.noclip and "ON" or "OFF", self.freecam and "ON" or "OFF"
end

function ModMasterDev:ToggleGod()
    local p=self:PlayerEntity();local soul=p and p.soul
    if not soul or not soul.AddBuff or not soul.RemoveAllBuffsByGuid then return self:Log("RPG buff API unavailable") end
    if self.godOwner==p then
        if soul.RemoveBuff and self.godInstance then pcall(soul.RemoveBuff,soul,self.godInstance) end
        pcall(soul.RemoveAllBuffsByGuid,soul,ModMasterGodGuid)
        self.godOwner=nil;self.godInstance=nil
        self:Log("ModMaster God Mode disabled")
        return
    end
    local ok,instance=pcall(soul.AddBuff,soul,ModMasterGodGuid)
    if not ok or instance==nil or instance==false then
        return self:Log("God Mode buff rejected; check buff database loading: " .. tostring(instance))
    end
    self.godOwner=p;self.godInstance=instance
    if soul.SetState then pcall(soul.SetState,soul,"health",100) end
    pcall(soul.AddBuff,soul,ModMasterRemoveInjuriesGuid)
    self:Log("ModMaster God Mode active: invulnerable, full health, injuries cleared")
end

-- Collider mode 5 turns collision off; the position is written directly every tick.
function ModMasterDev:ToggleNoclip()
    if self.freecam then return self:Log("Exit Freecam before enabling Noclip") end
    if self.noclip then self:StopNoclip();return end
    local p=self:PlayerEntity()
    if not p or not p.SetWorldPos or not p.GetWorldPos or not p.SetColliderMode then
        return self:Log("Player transform API unavailable")
    end
    self.noclip={entity=p,lastTime=self:Now()}
    local started,startErr=pcall(function() p:SetColliderMode(ModMasterColliderNoclip) end)
    if not started then self.noclip=nil;return self:Log("Noclip start failed: " .. tostring(startErr)) end
    self:Log("Noclip active: collision disabled, WASD/QE/Shift/Ctrl move Henry directly")
    self:NoclipTick(self.noclip)
end

function ModMasterDev:StopNoclip()
    local f=self.noclip;if not f then return end;self.noclip=nil
    if self.noclipTimer and Script.KillTimer then pcall(Script.KillTimer,self.noclipTimer) end;self.noclipTimer=nil
    if f.entity==self:PlayerEntity() then self:Guard(function() f.entity:SetColliderMode(ModMasterColliderNormal) end) end
    if self.cameraRules then pcall(function() self.cameraRules:FreezeInput(false) end);self.cameraRules=nil end
    pcall(ActionMapManager.EnableActionMapManager,true,true)
    self:Guard(function() self:UI("Noclip",false) end)
    if self.opened then self:Guard(function() self:ApplyMenuInput() end) else pcall(UIAction.HideElement,"ModMasterMenu",0) end
    self:Log("Noclip disabled; normal collision restored")
end

-- Uses the camera's up vector so steep pitch still moves along the view.
local function mmNormalize(v)
    local lenSq=v.x*v.x+v.y*v.y+v.z*v.z
    if lenSq<=0.000001 then return {x=0,y=0,z=0} end
    local inv=1/math.sqrt(lenSq)
    return {x=v.x*inv,y=v.y*inv,z=v.z*inv}
end
local function mmCross(a,b)
    return {x=a.y*b.z-a.z*b.y, y=a.z*b.x-a.x*b.z, z=a.x*b.y-a.y*b.x}
end

function ModMasterDev:NoclipTick(f)
    if self.noclip~=f then return end
    if f.entity~=self:PlayerEntity() then return self:StopNoclip() end
    local ok,err=pcall(function()
        -- Camera-HUD exit/reopen commands only exist while the main menu list is hidden.
        if not self.opened then
            local seq=tonumber(UIAction.GetVariable("ModMasterMenu",0,"Sequence"))
            if seq and seq~=self.uiSequence then
                local action=UIAction.GetVariable("ModMasterMenu",0,"Action");self.uiSequence=seq;UIAction.SetVariable("ModMasterMenu",0,"Ack",seq)
                if action=="camera_exit" then self:StopNoclip();return elseif action=="camera_menu" then self:Toggle();return end
            end
        end
        -- The menu SWF samples movement keys every frame, open or closed.
        local now=self:Now();local dt=math.max(0,math.min(0.1,now-(f.lastTime or now)));f.lastTime=now
        local function axis(name) return math.max(-1,math.min(1,tonumber(UIAction.GetVariable("ModMasterMenu",0,name)) or 0)) end
        local forward=mmNormalize(System.GetViewCameraDir())
        local camUp={x=0,y=0,z=1}
        if System.GetViewCameraUpDir then
            local okUp,up=pcall(System.GetViewCameraUpDir)
            if okUp and type(up)=="table" then camUp=mmNormalize(up) end
        end
        local right=mmNormalize(mmCross(forward,camUp))
        local fast=axis("CamFast")>0;local slow=axis("CamSlow")>0
        local speed=self.settings.freecamSpeed*(fast and self.settings.fastMult or (slow and self.settings.slowMult or 1))
        local fwdIn=axis("CamForward");local sideIn=axis("CamRight");local upIn=axis("CamUp")
        local pos=f.entity:GetWorldPos()
        pos.x=pos.x+(forward.x*fwdIn+right.x*sideIn)*speed*dt
        pos.y=pos.y+(forward.y*fwdIn+right.y*sideIn)*speed*dt
        pos.z=pos.z+(forward.z*fwdIn+upIn)*speed*dt
        f.entity:SetWorldPos(pos)
    end)
    if not ok then self:StopNoclip();self:Log("Noclip error; restored: " .. tostring(err));return end
    if self.noclip==f then self.noclipTimer=Script.SetTimer(33,function() self:NoclipTick(f) end,nil,true) end
end

function ModMasterDev:RestorePlayerOptions()
    if self.freecam then self:StopFreecam("Freecam restored") end
    if self.noclip then self:StopNoclip() end
    local p=self:PlayerEntity()
    if self.godOwner==p and p and p.soul then
        self:Guard(function()
            if p.soul.RemoveBuff and self.godInstance then pcall(p.soul.RemoveBuff,p.soul,self.godInstance) end
            p.soul:RemoveAllBuffsByGuid(ModMasterGodGuid)
        end)
    end
    self.godOwner=nil;self.godInstance=nil;self:Log("ModMaster player overrides restored")
end
