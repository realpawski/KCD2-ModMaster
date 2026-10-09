-- The retail game ignores scripted camera poses, so Freecam flies Henry like Noclip and puts him
-- back where he started when it ends.
function ModMasterDev:ToggleFreecam()
    if self.freecam then return self:StopFreecam("Freecam disabled") end
    if self.noclip then return self:Log("Exit Noclip before enabling Freecam") end
    local p=self:PlayerEntity()
    if not p or not p.GetWorldPos then return self:Log("Player transform API unavailable") end
    local pos=p:GetWorldPos()
    local c={entity=p,start={x=pos.x,y=pos.y,z=pos.z}}
    if p.GetWorldAngles then
        local ok,ang=pcall(function() return p:GetWorldAngles() end)
        if ok and type(ang)=="table" then c.angles={x=ang.x,y=ang.y,z=ang.z} end
    end
    self.freecam=c
    if not self:StartFlight("Freecam") then self.freecam=nil;return end
    self:Log("Freecam active: WASD fly, Space/C up/down, mouse wheel speed; Henry returns when it ends")
end

function ModMasterDev:StopFreecam(reason)
    local c=self.freecam;if not c then return end
    self.freecam=nil
    self:StopNoclip(true)
    if c.entity==self:PlayerEntity() then
        self:Guard(function()
            c.entity:SetWorldPos(c.start)
            if c.angles and c.entity.SetWorldAngles then c.entity:SetWorldAngles(c.angles) end
        end)
    end
    self:Log(reason or "Freecam ended; Henry is back at his position")
end
