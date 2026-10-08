function ModMasterDev:Vector(x,y,z)
    x=tonumber(x);y=tonumber(y);z=tonumber(z)
    for _,v in ipairs({x or false,y or false,z or false}) do
        if type(v)~="number" or v~=v or math.abs(v)>1000000 then return nil end
    end
    return {x=x,y=y,z=z}
end

function ModMasterDev:CopyVector(v) return {x=v.x,y=v.y,z=v.z} end

function ModMasterDev:Placement(mode)
    local p=g_localActor
    if not p then return nil,"Load a playable world first" end
    local pos=System.GetViewCameraPos(); local dir=System.GetViewCameraDir()
    if mode=="crosshair" then
        if not Physics or not Physics.RayWorldIntersection or not ent_all then
            return nil,"Crosshair raycast not exposed; use Spawn in Front"
        end
        local hits={}
        local n=Physics.RayWorldIntersection(pos,{x=dir.x*50,y=dir.y*50,z=dir.z*50},1,ent_all,p.id,nil,hits)
        if not n or n<1 or not hits[1] or not hits[1].pos then
            return nil,"No surface hit within 50m; use Spawn in Front"
        end
        local at=self:CopyVector(hits[1].pos);at.z=at.z+0.05
        return at
    end
    local at=p:GetWorldPos(); local len=math.sqrt(dir.x*dir.x+dir.y*dir.y)
    if len<0.001 then return nil,"Camera direction is vertical; cannot place in front" end
    return {x=at.x+dir.x*3/len,y=at.y+dir.y*3/len,z=at.z+0.15}
end

function ModMasterDev:SpawnAsset(asset, pos)
    if not System.SpawnEntity or not System.GetEntity or not System.RemoveEntity then
        return self:Log("Entity lifecycle API unavailable in this build")
    end
    self.serial=self.serial+1
    local name="ModMasterDev_" .. self.serial
    local entity=System.SpawnEntity({class="BasicEntity",name=name,position=pos,scale=1,
        properties={object_Model=asset.model_path,bCanTriggerAreas=false,bSaved_by_game=false,
            Physics={bPhysicalize=true,bRigidBody=false,bPushableByPlayers=false,Mass=0,Density=0},
            MultiplayerOptions={bNetworked=false}}})
    if not entity or not entity.id then return self:Log("Engine rejected spawn: " .. asset.model_path) end
    -- Store both ID and object identity/name; ID reuse must never delete unrelated entities.
    local entry={id=entity.id,entity=entity,name=name,asset=asset,
        original={position=self:CopyVector(pos),rotation={x=0,y=0,z=0},scale=1}}
    table.insert(self.spawns,entry); self.spawnSelected=#self.spawns
    if entity.GetWorldAngles then entry.original.rotation=self:CopyVector(entity:GetWorldAngles()) end
    if entity.GetScale then entry.original.scale=entity:GetScale() end
    self:Log("Entity created: " .. name .. "; verify visible model/collision in game")
    return entity
end

function ModMasterDev:SpawnSelected(mode)
    if not self.opened then return end
    local asset=self:FilteredAssets()[self.selected]
    if not asset then return self:Log("No compatible selected asset") end
    if asset.spawn_type~="static_prop" then return self:Log("Weapons and armor use Give to Inventory") end
    local pos,err=self:Placement(mode)
    if not pos then return self:Log(err) end
    return self:SpawnAsset(asset,pos)
end

function ModMasterDev:IsOwned(entry)
    if not entry or not System.GetEntity then return false end
    local entity=System.GetEntity(entry.id)
    return entity and entity==entry.entity and entity:GetName()==entry.name
end

function ModMasterDev:ActiveSpawns()
    local live={}
    for _,entry in ipairs(self.spawns) do if self:IsOwned(entry) then table.insert(live,entry) end end
    self.spawns=live;return live
end

function ModMasterDev:TransformSelected(x,y,z,rx,ry,rz,scale)
    local entry=self:FilteredSpawns()[self.spawnSelected]
    if not self:IsOwned(entry) then return self:Log("No owned spawn selected") end
    local p=self:Vector(x,y,z); local r=self:Vector(rx,ry,rz); scale=tonumber(scale)
    if not p or not r or not scale or scale~=scale or scale<0.01 or scale>100 then
        return self:Log("Invalid transform (rotation radians; uniform scale 0.01..100)")
    end
    entry.entity:SetWorldPos(p);entry.entity:SetWorldAngles(r);entry.entity:SetScale(scale)
    self:Log("Transform applied to " .. entry.name)
end

function ModMasterDev:ResetSelected()
    local e=self:FilteredSpawns()[self.spawnSelected]
    if not e then return end
    local t=e.original
    self:TransformSelected(t.position.x,t.position.y,t.position.z,t.rotation.x,t.rotation.y,t.rotation.z,t.scale)
end

function ModMasterDev:DuplicateSelected()
    local e=self:FilteredSpawns()[self.spawnSelected]
    if not e then return end
    local p=e.entity:GetWorldPos();p={x=p.x+0.5,y=p.y,z=p.z}
    local rotation=self:CopyVector(e.entity:GetWorldAngles());local scale=e.entity:GetScale()
    local copy=self:SpawnAsset(e.asset,p)
    if copy then copy:SetWorldAngles(rotation);copy:SetScale(scale) end
end

function ModMasterDev:DespawnSelected()
    local e=self:FilteredSpawns()[self.spawnSelected]
    if not self:IsOwned(e) then return self:Log("No owned spawn selected") end
    System.RemoveEntity(e.id)
    if not self:IsOwned(e) then
        self:Log("Entity removed: " .. e.name);self:ActiveSpawns();self.spawnSelected=1
    else self:Log("Engine did not remove entity") end
end

function ModMasterDev:Clear()
    for _,e in ipairs(self.spawns) do if self:IsOwned(e) then System.RemoveEntity(e.id) end end
    self:ActiveSpawns();self.spawnSelected=1;self:Log("Owned spawn clear completed; remaining " .. #self.spawns)
end

function ModMasterDev:FilteredSpawns()
    local result={};local query=string.lower(self.spawnSearch or "")
    for _,entry in ipairs(self:ActiveSpawns()) do
        local text=string.lower(entry.asset.name .. " " .. entry.asset.id .. " " .. tostring(entry.id))
        if query=="" or string.find(text,query,1,true) then table.insert(result,entry) end
    end
    return result
end
