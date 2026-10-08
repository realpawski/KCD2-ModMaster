local ok, err = pcall(function()
    if ModMasterDev and ModMasterDev.Shutdown then ModMasterDev:Shutdown() end
    Script.ReloadScript("Scripts/ModMaster/core.lua")
    Script.ReloadScript("Scripts/ModMaster/spawner.lua")
    Script.ReloadScript("Scripts/ModMaster/player_tools.lua")
    Script.ReloadScript("Scripts/ModMaster/features.lua")
    Script.ReloadScript("Scripts/ModMaster/camera.lua")
    Script.ReloadScript("Scripts/ModMaster/menu.lua")
    ModMasterDev:Init()
end)
if not ok and System and System.LogAlways then
    System.LogAlways("[ModMaster] initialization failed; companion disabled: " .. tostring(err))
end
