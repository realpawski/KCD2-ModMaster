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
    local entity
    if asset.model_path:lower():sub(-4)==".cdf" then
        -- Characters need AnimObject to play an animation; BasicEntity would show the rest pose.
        local animation=type(asset.animation)=="string" and asset.animation:match("^[%w_]+$") and asset.animation or ""
        entity=System.SpawnEntity({class="AnimObject",name=name,position=pos,scale=1,
            properties={object_Model=asset.model_path,bSaved_by_game=false,
                Animation={Animation=animation,Speed=1,bLoop=true,bPlaying=animation~="",bAlwaysUpdate=true,
                    playerAnimationState="",bPhysicalizeAfterAnimation=false,bResetOnUnslaved=false,BlendTime=0},
                Physics={bArticulated=false,bRigidBody=false,bPushableByPlayers=false,bBulletCollisionEnabled=true},
                MultiplayerOptions={bNetworked=false}}})
    else
        entity=System.SpawnEntity({class="BasicEntity",name=name,position=pos,scale=1,
            properties={object_Model=asset.model_path,bCanTriggerAreas=false,bSaved_by_game=false,
                Physics={bPhysicalize=true,bRigidBody=false,bPushableByPlayers=false,Mass=0,Density=0},
                MultiplayerOptions={bNetworked=false}}})
    end
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

-- NPCs and animals come to life through the AI module: a soul gives them brain, schedule and animations.
function ModMasterDev:FindSpawned(ai,result,name)
    if type(result)=="table" and result.id then return result end
    if result~=nil and System.GetEntity then
        local ok,entity=pcall(System.GetEntity,result)
        if ok and type(entity)=="table" and entity.id then return entity end
    end
    if result~=nil and ai and ai.GetEntityByWUID then
        local ok,entity=pcall(ai.GetEntityByWUID,result)
        if ok and type(entity)=="table" and entity.id then return entity end
    end
    if System.GetEntityByName then
        local ok,entity=pcall(System.GetEntityByName,name)
        if ok and type(entity)=="table" and entity.id then return entity end
    end
end

function ModMasterDev:TrackSoul(entity,name,asset,pos,yaw)
    table.insert(self.spawns,{id=entity.id,entity=entity,name=name,asset=asset,
        original={position=self:CopyVector(pos),rotation={x=0,y=0,z=yaw},scale=1}})
    self.spawnSelected=#self.spawns
    self:Log("Spawned " .. asset.name .. " as " .. name)
    return entity
end

-- The engine only spawns a concrete soul, so "Random" entries draw one of that archetype.
function ModMasterDev:RandomSoul(archetype)
    self.soulPools=self.soulPools or {}
    local pool=self.soulPools[archetype]
    if not pool then
        pool={}
        for _,a in ipairs(self.assets) do
            if a.spawn_type=="soul" and a.soul_guid and a.archetype==archetype and a.source~="compiled_custom" then
                table.insert(pool,a.soul_guid)
            end
        end
        self.soulPools[archetype]=pool
    end
    if #pool>0 then return pool[math.random(#pool)] end
end

function ModMasterDev:CopyTable(source,depth)
    local copy={}
    for k,v in pairs(source) do
        if type(v)=="table" and depth<6 then copy[k]=self:CopyTable(v,depth+1)
        elseif type(v)~="function" then copy[k]=v end
    end
    return copy
end

-- Entity classes read their soul from Properties; the class defaults keep model, navigation and AI setup intact.
function ModMasterDev:SoulProperties(class,guid,model,clothing,calm)
    local script=rawget(_G,class)
    if type(script)~="table" or type(script.Properties)~="table" then return nil end
    local props=self:CopyTable(script.Properties,0)
    props.guidSharedSoulId=guid;props.sharedSoulGuid=guid;props.bSaved_by_game=false
    if model then props.fileModel=model end
    -- Animals are dressed by their clothing config; a mod creature brings its own with its skin.
    if clothing then props.esClothingConfig=clothing end
    -- Wild bodies startle from what they perceive and bolt; a tame or friendly creature must not.
    if calm then props.bCanHoldInformation=false end
    return props
end

-- Health is capped at 100 in KCD2, so more health means taking a matching share of every hit back.
function ModMasterDev:ToughnessTick(entity,factor,last)
    local alive=System.GetEntity and System.GetEntity(entity.id)==entity
    local soul=entity.soul
    if not alive or not soul then return end
    local ok,now=pcall(soul.GetState,soul,"health")
    if not ok or type(now)~="number" or now<=0 then return end
    if last and now<last then
        now=last-(last-now)/factor
        pcall(soul.SetState,soul,"health",now)
    end
    if Script and Script.SetTimer then Script.SetTimer(100,function() self:ToughnessTick(entity,factor,now) end) end
end

-- Creatures from a mod carry their own health and stats; the soul exists a moment after the spawn.
function ModMasterDev:ApplyCreature(entity,asset)
    if not asset.health and type(asset.stats)~="table" then return end
    local function apply()
        local soul=entity.soul
        if not soul then return self:Log(asset.name .. ": no soul, stats not applied") end
        local done={}
        for stat,level in pairs(asset.stats or {}) do
            if pcall(soul.SetStatLevel,soul,stat,level) then table.insert(done,stat .. " " .. level) end
        end
        if asset.health and asset.health<100 then
            pcall(soul.SetState,soul,"health",asset.health)
            table.insert(done,"health " .. asset.health)
        elseif asset.health and asset.health>100 then
            self:ToughnessTick(entity,asset.health/100,nil)
            table.insert(done,string.format("takes %d%% damage",math.floor(10000/asset.health+0.5)))
        end
        self:Log(asset.name .. " stats: " .. table.concat(done,", "))
    end
    if Script and Script.SetTimer then Script.SetTimer(300,function() self:Guard(apply) end) else self:Guard(apply) end
end

-- The clothing system dresses animals after they spawn; loading the model into the character slot on top
-- keeps the game skeleton, so the creature's own animations still drive it.
function ModMasterDev:ApplyLook(entity,asset,model,attempt)
    if System.GetEntity and System.GetEntity(entity.id)~=entity then return end
    local ok,err=pcall(entity.LoadCharacter,entity,0,model)
    if attempt==1 then
        self:Log(asset.name .. " look " .. model .. ": " .. (ok and "loaded" or ("failed: " .. tostring(err))))
    end
    if ok and attempt<3 and Script and Script.SetTimer then
        Script.SetTimer(attempt*1500,function() self:Guard(function() self:ApplyLook(entity,asset,model,attempt+1) end) end)
    end
end

-- Spawned animals stand where their brain leaves them, and animal brains follow nobody. So every spawned
-- animal gets the same life: its brain leads (grazing, fleeing, fighting), and while the brain keeps it
-- still the script walks it with the body's own gaits, after Henry for a friend, around its spawn for the rest.
function ModMasterDev:OutOfView(pos)
    local cam=System.GetViewCameraPos and System.GetViewCameraPos()
    local dir=System.GetViewCameraDir and System.GetViewCameraDir()
    if not cam or not dir then return true end
    local vx,vy,vz=pos.x-cam.x,pos.y-cam.y,pos.z-cam.z
    local len=math.sqrt(vx*vx+vy*vy+vz*vz)
    return len<0.01 or (vx*dir.x+vy*dir.y+vz*dir.z)/len<0.5
end

-- Last resort for a friend that is truly lost: set it down behind Henry where nobody sees it appear.
function ModMasterDev:FollowTick(entity,asset,tick)
    if System.GetEntity and System.GetEntity(entity.id)~=entity then return end
    if self:IsDead(entity) then return end
    local p=self:PlayerEntity()
    if p then
        local a,b=p:GetWorldPos(),entity:GetWorldPos()
        local dx,dy=b.x-a.x,b.y-a.y
        if math.sqrt(dx*dx+dy*dy)>60 and self:OutOfView(b) then
            local dir=System.GetViewCameraDir and System.GetViewCameraDir() or {x=0,y=1,z=0}
            local len=math.sqrt(dir.x*dir.x+dir.y*dir.y)
            if len>0.01 then
                pcall(entity.SetWorldPos,entity,{x=a.x-dir.x/len*4,y=a.y-dir.y/len*4,z=a.z+0.3})
                local state=self.walkers[entity.id]
                if state then state.expect=nil end
                if not self.leashLogged then self.leashLogged=true;self:Log(asset.name .. " was lost: set down behind Henry") end
            end
        end
    end
    if Script and Script.SetTimer then
        Script.SetTimer(1000,function() self:Guard(function() self:FollowTick(entity,asset,tick+1) end) end)
    end
end

function ModMasterDev:IsDead(entity)
    local soul=entity.soul
    if not soul or not soul.GetState then return false end
    local ok,hp=pcall(soul.GetState,soul,"health")
    return ok and type(hp)=="number" and hp<=0
end

function ModMasterDev:GroundZ(x,y,fromZ,skip)
    local phys=rawget(_G,"Physics")
    if type(phys)=="table" and phys.RayWorldIntersection then
        local ok,hits=pcall(phys.RayWorldIntersection,{x=x,y=y,z=fromZ+1.5},{x=0,y=0,z=-6},1,ent_all or 287,skip)
        local hit=ok and type(hits)=="table" and hits[1]
        if hit and hit.pos then return hit.pos.z end
    end
    if System.GetTerrainElevation then
        local ok,z=pcall(System.GetTerrainElevation,{x=x,y=y,z=fromZ})
        if ok and type(z)=="number" then return z end
    end
    return fromZ
end

function ModMasterDev:GaitsFor(asset,class)
    if type(asset.gaits)=="table" then return asset.gaits end
    local all=rawget(_G,"ModMasterGaits")
    return type(all)=="table" and type(all[class])=="table" and all[class] or nil
end

function ModMasterDev:Gait(gaits,dist,follow)
    if follow and dist>16 and gaits.run then return gaits.run,6.0 end
    if follow and dist>8 and gaits.trot then return gaits.trot,3.0 end
    return gaits.walk or gaits.trot or gaits.run,1.5
end

-- The brain's animation system keeps replacing loops played on the base layer, so the gait plays on a
-- layer of its own that overrides the body while walking and is cleared again when the creature stops.
ModMasterGaitLayer=8

function ModMasterDev:PlayLoop(entity,asset,anim)
    if not anim or not entity.StartAnimation then return end
    local ok,result=pcall(entity.StartAnimation,entity,0,anim,ModMasterGaitLayer,0.25,1.0,true)
    if not self.gaitLogged then
        self.gaitLogged=true
        self:Log(string.format("%s walks with %s: %s",asset.name,anim,ok and tostring(result) or ("failed: " .. tostring(result))))
    end
end

function ModMasterDev:Halt(entity,state)
    if state.anim and entity.StopAnimation then pcall(entity.StopAnimation,entity,0,ModMasterGaitLayer) end
    state.anim=nil;state.moving=false;state.goal=nil
end

function ModMasterDev:StartLife(entity,asset,class,pos)
    local gaits=self:GaitsFor(asset,class)
    if not gaits or not (gaits.walk or gaits.trot or gaits.run) or self.walkers[entity.id] then return end
    local now=self:Now()
    self.walkers[entity.id]={gaits=gaits,follow=asset.follow==true,home={x=pos.x,y=pos.y,z=pos.z},
        last=now,drift=0,pauseUntil=0,restUntil=now+3+math.random()*5}
    self:WalkTick(entity,asset)
end

function ModMasterDev:Wander(state,b,now)
    if state.goal or now<state.restUntil then return state.goal end
    local angle,radius=math.random()*math.pi*2,4+math.random()*8
    state.goal={x=state.home.x+math.cos(angle)*radius,y=state.home.y+math.sin(angle)*radius}
    return state.goal
end

-- A friend starts at 5 m and stops 2.5 m from Henry, so it does not twitch between walking and standing.
function ModMasterDev:WalkTick(entity,asset)
    local state=self.walkers[entity.id]
    if not state then return end
    if (System.GetEntity and System.GetEntity(entity.id)~=entity) or self:IsDead(entity) then
        self.walkers[entity.id]=nil;return
    end
    local now=self:Now()
    local dt=math.max(0,math.min(0.2,now-state.last))
    state.last=now
    local b=entity:GetWorldPos()
    -- Movement the script did not make is the brain at work: fleeing, charging or fighting. It leads then.
    local ref=state.expect or state.seen
    if ref then
        local ex,ey=b.x-ref.x,b.y-ref.y
        state.drift=state.drift*0.9+math.sqrt(ex*ex+ey*ey)
    end
    state.expect=nil;state.seen={x=b.x,y=b.y}
    if state.drift>(state.moving and 0.9 or 0.25) then
        if state.moving then self:Halt(entity,state) end
        state.pauseUntil=now+8;state.restUntil=now+8;state.home={x=b.x,y=b.y,z=b.z}
    end
    local target,startAt,stopAt
    if now>=state.pauseUntil then
        if state.follow then
            local p=self:PlayerEntity()
            if p then target=p:GetWorldPos() end
            startAt,stopAt=5,2.5
        else
            target=self:Wander(state,b,now)
            startAt,stopAt=0.5,0.5
        end
    end
    if target then
        local dx,dy=target.x-b.x,target.y-b.y
        local dist=math.sqrt(dx*dx+dy*dy)
        if dist>60 then
            if state.moving then self:Halt(entity,state) end
        elseif state.moving or dist>startAt then
            if dist<=stopAt then
                self:Halt(entity,state)
                state.restUntil=now+5+math.random()*10
            else
                state.moving=true
                local anim,speed=self:Gait(state.gaits,dist,state.follow)
                if anim~=state.anim then state.anim=anim;self:PlayLoop(entity,asset,anim) end
                local step=math.min(speed*dt,dist-stopAt)
                local x,y=b.x+dx/dist*step,b.y+dy/dist*step
                pcall(entity.SetWorldPos,entity,{x=x,y=y,z=self:GroundZ(x,y,b.z,entity.id)})
                pcall(entity.SetWorldAngles,entity,{x=0,y=0,z=math.atan2(-dx,dy)})
                state.expect={x=x,y=y}
            end
        end
    end
    if Script and Script.SetTimer then
        Script.SetTimer(30,function() self:Guard(function() self:WalkTick(entity,asset) end) end)
    end
end

function ModMasterDev:SpawnBody(class,name,pos,yaw,guid,model,clothing,calm)
    local function spec(props)
        return {class=class,name=name,position=pos,orientation={x=-math.sin(yaw),y=math.cos(yaw),z=0},properties=props}
    end
    local props=self:SoulProperties(class,guid,model,clothing,calm)
    if props then
        local ok,value=pcall(System.SpawnEntity,spec(props))
        if ok and type(value)=="table" and value.id then return value,"soul " .. guid end
        if not ok then return nil,nil,value end
    end
    -- Animals and horses bring a default soul archetype, so the plain class spawn still gives a living creature.
    local ok,value=pcall(System.SpawnEntity,spec(nil))
    if ok and type(value)=="table" and value.id then return value,"default soul" end
    return nil,nil,not ok and value or nil
end

function ModMasterDev:SpawnSoul(asset,pos)
    local guid=asset.soul_guid or self:RandomSoul(asset.archetype)
    if not guid then return self:Log("No " .. tostring(asset.archetype) .. " souls in the registry") end
    local class=asset.entity_class or (asset.category=="npcs" and "NPC" or asset.archetype)
    local model=type(asset.model_path)=="string" and asset.model_path~="" and asset.model_path or nil
    -- A person's entity must start from the game skeleton file; the model is loaded over it afterwards.
    local bodyModel=asset.category~="npcs" and model or nil
    local clothing=type(asset.clothing_config)=="string" and asset.clothing_config:match("^[%w_]+$") and asset.clothing_config or nil
    self.serial=self.serial+1
    local name="ModMasterSoul_" .. self.serial
    local yaw=0
    local okDir,dir=pcall(System.GetViewCameraDir)
    if okDir and type(dir)=="table" then yaw=math.atan2(-dir.x,dir.y)+math.pi end
    local entity,how,err
    local calm=asset.calm==true
    if System.SpawnEntity then entity,how,err=self:SpawnBody(class,name,pos,yaw,guid,bodyModel,clothing,calm) end
    -- A mod's own soul only exists once the game loaded the mod's soul table; borrow a game soul otherwise.
    if entity and asset.source=="compiled_custom" and not entity.soul then
        local fallback=self:RandomSoul(asset.archetype)
        if fallback and fallback~=guid then
            pcall(System.RemoveEntity,entity.id)
            entity,how,err=self:SpawnBody(class,name,pos,yaw,fallback,bodyModel,clothing,calm)
            how=(how or "") .. " (mod soul not loaded)"
        end
    end
    local ai=rawget(_G,"XGenAIModule")
    if not entity and type(ai)=="table" and type(ai.SpawnEntity)=="function" then
        local ok,value=pcall(ai.SpawnEntity,{Name=name,ClassName=class,SharedSoulGuid=guid,Pos=pos,Rot={x=0,y=0,z=yaw}})
        if ok then entity=self:FindSpawned(ai,value,name);how="AI module" else err=value end
    end
    if entity then
        self:Log(string.format("%s spawned via %s (class %s, has soul: %s, look: %s)",asset.name,how,class,
            tostring(entity.soul~=nil),clothing or model or "game"))
        self:ApplyCreature(entity,asset)
        if model and entity.LoadCharacter and Script and Script.SetTimer then
            -- Loading the look earlier, or hiding the creature meanwhile, crashes the game; 500 ms is safe.
            Script.SetTimer(500,function() self:Guard(function() self:ApplyLook(entity,asset,model,1) end) end)
        end
        if asset.category~="npcs" then self:StartLife(entity,asset,class,pos) end
        if asset.follow then self:FollowTick(entity,asset,1) end
        return self:TrackSoul(entity,name,asset,pos,yaw)
    end
    self:Log("Spawn of " .. asset.name .. " failed (class " .. class .. ", soul " .. guid .. ")" .. (err and (": " .. tostring(err)) or ""))
end

function ModMasterDev:SpawnSelected(mode)
    if not self.opened then return end
    local asset=self:FilteredAssets()[self.selected]
    if not asset then return self:Log("No compatible selected asset") end
    local pos,err=self:Placement(mode)
    if asset.spawn_type=="soul" then
        if not pos then return self:Log(err) end
        return self:SpawnSoul(asset,pos)
    end
    if asset.spawn_type~="static_prop" then return self:Log("Weapons and armor use Give to Inventory") end
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
    local copy=e.asset.spawn_type=="soul" and self:SpawnSoul(e.asset,p) or self:SpawnAsset(e.asset,p)
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
