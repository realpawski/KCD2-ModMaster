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
