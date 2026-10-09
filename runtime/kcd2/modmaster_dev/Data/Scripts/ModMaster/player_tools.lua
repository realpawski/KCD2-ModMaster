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
        self:StopGodTick()
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
    self:FillHealth(p)
    pcall(soul.AddBuff,soul,ModMasterRemoveInjuriesGuid)
    self:GodTick(p)
    self:Log("ModMaster God Mode active: invulnerable, health kept full, injuries cleared")
end

ModMasterMaxHealth=100

function ModMasterDev:FillHealth(p)
    local soul=p and p.soul;if not soul then return false end
    if soul.SetState and pcall(soul.SetState,soul,"health",ModMasterMaxHealth) then return true end
    return soul.SetHealth~=nil and pcall(soul.SetHealth,soul,ModMasterMaxHealth)
end

-- The vanilla immortality buff stops death but not damage, so health is topped up while it is active.
function ModMasterDev:GodTick(p)
    if self.godOwner~=p then return end
    local soul=p.soul
    local okHp,hp=pcall(function() return soul.GetState and soul:GetState("health") end)
    hp=okHp and tonumber(hp) or nil
    if not hp or hp<ModMasterMaxHealth then self:FillHealth(p) end
    if Script and Script.SetTimer then self.godTimer=Script.SetTimer(200,function() self:GodTick(p) end,nil,true) end
end

function ModMasterDev:StopGodTick()
    if self.godTimer and Script.KillTimer then pcall(Script.KillTimer,self.godTimer) end
    self.godTimer=nil
end

function ModMasterDev:RestoreHealth()
    local p=self:PlayerEntity()
    if not p or not p.soul then return self:Log("Player soul unavailable") end
    if not self:FillHealth(p) then return self:Log("Health could not be set") end
    if p.soul.AddBuff then pcall(p.soul.AddBuff,p.soul,ModMasterRemoveInjuriesGuid) end
    self:Log("Health restored to maximum, injuries cleared")
end

-- Noclip and Freecam fly Henry with collision off (collider mode 5). Game input stays on so the
-- mouse keeps steering the view. Vanilla movement never reaches Lua, so flying uses its own
-- action map whose actions arrive in Player.OnAction.
ModMasterFlightMap="modmaster_flight"
ModMasterFlyActions={modmaster_fly_forward="forward",modmaster_fly_back="back",modmaster_fly_left="left",
    modmaster_fly_right="right",modmaster_fly_up="up",modmaster_fly_down="down",modmaster_fly_fast="fast",
    modmaster_fly_precise="precise",modmaster_fly_speed_up="speed_up",modmaster_fly_speed_down="speed_down",
    moveforward="forward",moveback="back",moveleft="left",moveright="right",
    jump="up",toggle_crouch="down",crouch="down",sprint="fast"}

function ModMasterDev:FlightMap(p,on)
    local amm=rawget(_G,"ActionMapManager")
    if type(amm)~="table" then return false end
    if not self.flightMapLoaded and type(amm.LoadFromXML)=="function" then
        local ok,err=pcall(amm.LoadFromXML,"Libs/Config/ModMasterActionMaps.xml")
        self.flightMapLoaded=ok
        if not ok then self:Log("Flight keys unavailable: " .. tostring(err)) end
    end
    if on and p and type(amm.SetActionListener)=="function" then pcall(amm.SetActionListener,ModMasterFlightMap,p.id) end
    if type(amm.EnableActionMap)=="function" then pcall(amm.EnableActionMap,ModMasterFlightMap,on==true) end
    return self.flightMapLoaded
end

function ModMasterDev:HookPlayerActions()
    if self.actionHookOriginal then return true end
    local cls=rawget(_G,"Player")
    if type(cls)~="table" or type(cls.OnAction)~="function" then return false end
    local original=cls.OnAction
    self.actionHookOriginal=original
    cls.OnAction=function(entity,action,activation,value)
        local dev=ModMasterDev
        if dev.noclip and not dev.opened and dev:FlightAction(action,activation) then return end
        return original(entity,action,activation,value)
    end
    return true
end

function ModMasterDev:FlightAction(action,activation)
    local role=ModMasterFlyActions[action]
    if not role then return false end
    local keys=self.flyKeys
    if role=="precise" then
        if activation=="press" then keys.precise=not keys.precise end
    elseif role=="speed_up" or role=="speed_down" then
        if activation=="press" then self:ChangeFlightSpeed(role=="speed_up" and 1.25 or 0.8) end
    else
        keys[role]=activation~="release"
    end
    return true
end

-- Modifier keys never reach an action map, so the mouse wheel sets the flight speed.
function ModMasterDev:ChangeFlightSpeed(factor)
    local s=self.settings
    s.freecamSpeed=math.max(0.5,math.min(200,math.floor(s.freecamSpeed*factor*100+0.5)/100))
    self:Guard(function()
        self:UI("Settings",s.hotkey,s.keyCode,s.hudEnabled,tostring(s.freecamSpeed),tostring(s.fastMult),
            tostring(s.slowMult),s.noclipHotkey)
    end)
end

function ModMasterDev:FlightHud(kind,on)
    if not UIAction then return end
    if on and not self.opened and UIAction.ShowElement then
        pcall(UIAction.ShowElement,"ModMasterMenu",0)
        if Script and Script.SetTimer then
            Script.SetTimer(150,function() if self.noclip then self:Guard(function() self:UI(kind,true) end) end end)
        end
        return
    end
    self:Guard(function() self:UI(kind,on) end)
end

function ModMasterDev:StartFlight(kind)
    local p=self:PlayerEntity()
    if not p or not p.SetWorldPos or not p.GetWorldPos or not p.SetColliderMode then
        self:Log("Player transform API unavailable");return false
    end
    self.flyKeys={}
    local f={entity=p,kind=kind,lastTime=self:Now()}
    local pos=p:GetWorldPos();f.pos={x=pos.x,y=pos.y,z=pos.z}
    local started,err=pcall(function() p:SetColliderMode(ModMasterColliderNoclip) end)
    if not started then self:Log(kind .. " start failed: " .. tostring(err));return false end
    self.noclip=f
    if not self:HookPlayerActions() then self:Log("Player actions unavailable; flying uses the menu keys only") end
    self:FlightMap(p,true)
    if self.opened then self:CloseMenu(kind .. " started") else self:FlightHud(kind,true) end
    self:NoclipTick(f)
    return true
end

function ModMasterDev:ToggleNoclip()
    if self.freecam then return self:StopFreecam("Freecam disabled") end
    if self.noclip then self:StopNoclip();return end
    if self:StartFlight("Noclip") then
        self:Log("Noclip active: WASD fly, Space/C up/down, Shift fast, Caps Lock precise")
    end
end

function ModMasterDev:StopNoclip(quiet)
    local f=self.noclip;if not f then return end;self.noclip=nil;self.flyKeys={}
    self:FlightMap(f.entity,false)
    if self.noclipTimer and Script.KillTimer then pcall(Script.KillTimer,self.noclipTimer) end;self.noclipTimer=nil
    if f.entity==self:PlayerEntity() then self:Guard(function() f.entity:SetColliderMode(ModMasterColliderNormal) end) end
    self:Guard(function() self:UI(f.kind,false) end)
    if self.opened then self:Guard(function() self:ApplyMenuInput() end) else self:Overlay(self.esp) end
    if not quiet then self:Log("Noclip disabled; normal collision restored") end
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

function ModMasterDev:FlightInput()
    local k=self.flyKeys or {}
    local function ui(name) return math.max(-1,math.min(1,tonumber(UIAction.GetVariable("ModMasterMenu",0,name)) or 0)) end
    local function pick(hook,menu) return math.abs(menu)>math.abs(hook) and menu or hook end
    local fwd=pick((k.forward and 1 or 0)-(k.back and 1 or 0),ui("CamForward"))
    local side=pick((k.right and 1 or 0)-(k.left and 1 or 0),ui("CamRight"))
    local up=pick((k.up and 1 or 0)-(k.down and 1 or 0),ui("CamUp"))
    return fwd,side,up,k.fast or ui("CamFast")>0,k.precise or ui("CamSlow")>0
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
                if action=="camera_exit" then
                    if self.freecam then self:StopFreecam() else self:StopNoclip() end
                    return
                elseif action=="camera_menu" then self:Toggle();return end
            end
        end
        local now=self:Now();local dt=math.max(0,math.min(0.1,now-(f.lastTime or now)));f.lastTime=now
        local forward=mmNormalize(System.GetViewCameraDir())
        local camUp={x=0,y=0,z=1}
        if System.GetViewCameraUpDir then
            local okUp,up=pcall(System.GetViewCameraUpDir)
            if okUp and type(up)=="table" then camUp=mmNormalize(up) end
        end
        local right=mmNormalize(mmCross(forward,camUp))
        local fwdIn,sideIn,upIn,fast,slow=self:FlightInput()
        local speed=self.settings.freecamSpeed*(fast and self.settings.fastMult or (slow and self.settings.slowMult or 1))
        -- The stored position wins over any walking the game applied since the last tick.
        local pos=f.pos
        pos.x=pos.x+(forward.x*fwdIn+right.x*sideIn)*speed*dt
        pos.y=pos.y+(forward.y*fwdIn+right.y*sideIn)*speed*dt
        pos.z=pos.z+(forward.z*fwdIn+upIn)*speed*dt
        f.entity:SetWorldPos({x=pos.x,y=pos.y,z=pos.z})
    end)
    if not ok then
        if self.freecam then self.freecam=nil end
        self:StopNoclip();self:Log("Flight error; restored: " .. tostring(err));return
    end
    if self.noclip==f then self.noclipTimer=Script.SetTimer(16,function() self:NoclipTick(f) end,nil,true) end
end

function ModMasterDev:RestorePlayerOptions()
    if self.freecam then self:StopFreecam("Freecam restored") end
    if self.noclip then self:StopNoclip() end
    self:StopGodTick()
    local p=self:PlayerEntity()
    if self.godOwner==p and p and p.soul then
        self:Guard(function()
            if p.soul.RemoveBuff and self.godInstance then pcall(p.soul.RemoveBuff,p.soul,self.godInstance) end
            p.soul:RemoveAllBuffsByGuid(ModMasterGodGuid)
        end)
    end
    self.godOwner=nil;self.godInstance=nil;self:Log("ModMaster player overrides restored")
end
