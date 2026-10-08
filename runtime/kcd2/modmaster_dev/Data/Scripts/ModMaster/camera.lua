function ModMasterDev:ToggleFreecam()
    if self.noclip then return self:Log("Exit Noclip before enabling Freecam") end
    if self.freecam then return self:StopFreecam("Freecam disabled") end
    if not Action or not Action.SetViewCameraByAngles or not Action.ResetToNormalCamera or
        not System.GetViewCameraPos or not System.GetViewCameraAngles or not Script.SetTimer then
        return self:Log("Freecam pose API unavailable")
    end
    -- Native camera getters can raise and return non-number fields.
    local readOK,pos,angles=pcall(function() return System.GetViewCameraPos(),System.GetViewCameraAngles() end)
    if not readOK then return self:Log("Freecam getters rejected: " .. tostring(pos)) end
    if type(pos)~="table" or type(angles)~="table" then return self:Log("Cannot read camera pose") end
    local px,py,pz=tonumber(pos.x),tonumber(pos.y),tonumber(pos.z)
    local pitch,yaw=tonumber(angles.x),tonumber(angles.z)
    if not px or not py or not pz or not pitch or not yaw then
        return self:Log("Camera pose fields missing or non-numeric; Freecam not started")
    end
    local c={pos={x=px,y=py,z=pz},pitch=pitch,yaw=yaw,lastTime=self:Now(),frames=0}
    self.freecam=c
    local ok,err=pcall(function() self:SetCameraPose(c) end)
    if not ok then self.freecam=nil;pcall(Action.ResetToNormalCamera);return self:Log("Freecam pose rejected: " .. tostring(err)) end
    self:Log("Freecam enabled: WASD move, Q/E vertical, Shift fast, Ctrl precise; arrows look when menu is closed")
    local tickOk,tickErr=pcall(function() self:FreecamTick(c) end)
    if not tickOk then self.freecam=nil;pcall(Action.ResetToNormalCamera);self:Log("Freecam first tick failed; disabled: " .. tostring(tickErr)) end
end

function ModMasterDev:SetCameraPose(c)
    -- Angles follow ed_goto degrees, while camera getters return radians.
    return Action.SetViewCameraByAngles(c.pos.x,c.pos.y,c.pos.z,c.pitch*180/math.pi,0,c.yaw*180/math.pi)
end

function ModMasterDev:CameraInputLock()
    self.cameraRules=self:Rules()
    ActionMapManager.EnableActionMapManager(false,true)
    self.cameraRules:FreezeInput(true)
end

function ModMasterDev:StopFreecam(reason)
    local c=self.freecam;if not c then return end
    self.freecam=nil
    if self.cameraTimer and Script.KillTimer then pcall(Script.KillTimer,self.cameraTimer) end
    self.cameraTimer=nil
    if self.cameraRules then pcall(function() self.cameraRules:FreezeInput(false) end);self.cameraRules=nil end
    pcall(ActionMapManager.EnableActionMapManager,true,true)
    pcall(Action.ResetToNormalCamera)
    self:Guard(function() self:UI("Freecam",false) end)
    if self.opened then self:Guard(function() self:ApplyMenuInput() end) else pcall(UIAction.HideElement,"ModMasterMenu",0) end
    self:Log(reason or "Freecam restored")
end

function ModMasterDev:FreecamTick(c)
    if self.freecam~=c then return end
    local ok,err=pcall(function()
        -- Camera-HUD exit/reopen commands only exist while the main menu list is hidden.
        if not self.opened then
            local seq=tonumber(UIAction.GetVariable("ModMasterMenu",0,"Sequence"))
            if seq and seq~=self.uiSequence then
                local action=UIAction.GetVariable("ModMasterMenu",0,"Action")
                self.uiSequence=seq;UIAction.SetVariable("ModMasterMenu",0,"Ack",seq)
                if action=="camera_exit" then self:StopFreecam();return
                elseif action=="camera_menu" then self:Toggle();return end
            end
        end
        local now=self:Now();local dt=math.max(0,math.min(0.1,now-(c.lastTime or now)));c.lastTime=now
        local function axis(name) return math.max(-1,math.min(1,tonumber(UIAction.GetVariable("ModMasterMenu",0,name)) or 0)) end
        local fwdIn=axis("CamForward");local sideIn=axis("CamRight");local vertIn=axis("CamUp")
        local fast=axis("CamFast")>0;local slow=axis("CamSlow")>0
        local speed=self.settings.freecamSpeed*(fast and self.settings.fastMult or (slow and self.settings.slowMult or 1))
        -- Arrow-key look; mouse deltas never reach the menu SWF.
        c.pitch=math.max(-1.5,math.min(1.5,c.pitch+axis("CamPitch")*1.2*dt));c.yaw=c.yaw+axis("CamYaw")*1.2*dt
        local cosPitch=math.cos(c.pitch)
        local forward={x=-math.sin(c.yaw)*cosPitch,y=math.cos(c.yaw)*cosPitch,z=math.sin(c.pitch)}
        local right={x=math.cos(c.yaw),y=math.sin(c.yaw),z=0}
        c.pos.x=c.pos.x+(forward.x*fwdIn+right.x*sideIn)*speed*dt
        c.pos.y=c.pos.y+(forward.y*fwdIn+right.y*sideIn)*speed*dt
        c.pos.z=c.pos.z+(forward.z*fwdIn+vertIn)*speed*dt
        self:SetCameraPose(c)
        c.frames=c.frames+1
        -- Judge movement over several frames, not by pcall success.
        if c.frames%20==0 then
            local actual=System.GetViewCameraPos()
            if not actual or math.abs(actual.x-c.pos.x)+math.abs(actual.y-c.pos.y)+math.abs(actual.z-c.pos.z)>2 then
                self:StopFreecam("Game did not apply Freecam pose; camera restored")
            end
        end
    end)
    if not ok then self:StopFreecam("Freecam error; restored: " .. tostring(err));return end
    if self.freecam==c then self.cameraTimer=Script.SetTimer(33,function() self:FreecamTick(c) end,nil,true) end
end
