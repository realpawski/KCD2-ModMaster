"""Lua 5.1 checks with simulated engine boundaries; not a live-game substitute."""
from pathlib import Path
import pytest
LuaRuntime=pytest.importorskip('lupa.lua51').LuaRuntime
SOURCE=Path(__file__).resolve().parents[1]/'runtime/kcd2/modmaster_dev/Data/Scripts'

def runtime():
 lua=LuaRuntime(unpack_returned_tuples=True)
 lua.execute('''
 mapsEnabled=true;uiVars={Ready=false,Sequence=0,Ack=0,Action="",Visible=true};frozen=false;visible=false;timers={};calls={};fakeTime=0;lastPose=nil;cameraReset=false
 Script={SetTimer=function(ms,fn) table.insert(timers,fn);return #timers end,KillTimer=function() end}
 System={LogAlways=function() end,ExecuteCommand=function() end,GetViewCameraDir=function() return {x=0,y=1,z=0} end,
  GetViewCameraPos=function() return {x=0,y=0,z=0} end,GetViewCameraAngles=function() return {x=0,y=0,z=0} end,
  GetCurrAsyncTime=function() return fakeTime end}
 CryAction={SetViewCameraByAngles=function(x,y,z,pitch,roll,yaw) lastPose={x=x,y=y,z=z,pitch=pitch,roll=roll,yaw=yaw};return true end,
  ResetToNormalCamera=function() cameraReset=true end}
 ActionMapManager={EnableActionMapManager=function(enable,reset) mapsEnabled=enable end}
 UIAction={GetVariable=function(el,id,name) return uiVars[name] end,SetVariable=function(el,id,name,value) uiVars[name]=value end,CallFunction=function(...) table.insert(calls,{...}) end,
  ShowElement=function() visible=true end,HideElement=function() visible=false end,
  RegisterElementListener=function() end,UnregisterElementListener=function() end}
 -- Verified against a working third-party cheat mod's extracted Lua source:
 -- soul:AddBuff()/RemoveBuff()/RemoveAllBuffsByGuid()/SetState() are the real API --
 -- soul:HasBuffDebug() is never called there and is unavailable in the live build, so
 -- it is deliberately NOT stubbed here (production code must not depend on it).
 -- Noclip uses actor:SetColliderMode(mode), not EnablePhysics.
 local soul={buffs={},health=0}
 function soul:AddBuff(guid) self.buffs[guid]=true;return "instance:"..guid end
 function soul:RemoveBuff(instance) removedInstances=removedInstances or {};table.insert(removedInstances,instance) end
 function soul:RemoveAllBuffsByGuid(guid) self.buffs[guid]=nil end
 function soul:SetState(name,value) if name=="health" then self.health=value end end
 function soul:GetState(name) if name=="health" then return self.health end end
 worldPos={x=0,y=0,z=0};colliderMode=0
 g_localActor={id=1,soul=soul,
  GetWorldPos=function(self) return worldPos end,
  SetWorldPos=function(self,p) worldPos=p end,
  SetColliderMode=function(self,m) colliderMode=m end}
 g_gameRules={game={FreezeInput=function(self,v) frozen=v end}}
 passedActions={}
 Player={OnAction=function(self,action,activation,value) table.insert(passedActions,action) end}
 Calendar={IsFakedTimeOfDay=function() return false end,SetFakeTimeOfDay=function(h) hour=h end,UnfakeTimeOfDay=function() hour=nil end}
 setmetatable(_G,{__index=function(_,k) if k=="Action" then error("undefined global Action") end end})
 ''')
 for rel in ['ModMaster/core.lua','ModMaster/spawner.lua','ModMaster/player_tools.lua','ModMaster/camera.lua','ModMaster/features.lua','ModMaster/menu.lua']:
  lua.execute((SOURCE/rel).read_text(encoding='utf8'))
 return lua

def event(lua,payload):
 lua.globals().payload=payload
 lua.execute('ModMasterDev:OnUIAction("ModMasterMenu",0,"Action",{payload})')

def open_menu(lua):
 lua.execute('ModMasterDev:Toggle()');event(lua,'ready')

def test_open_close_always_releases_input():
 lua=runtime();open_menu(lua)
 assert lua.eval('frozen and visible and ModMasterDev.uiReady and not mapsEnabled')
 event(lua,'close');assert lua.eval('not frozen and not visible and not ModMasterDev.opened and mapsEnabled')

def test_show_failure_releases_input():
 lua=runtime();lua.execute('UIAction.ShowElement=function() error("load failed") end;ModMasterDev:Toggle()')
 assert lua.eval('not frozen and not ModMasterDev.opened')

def test_hide_failure_still_releases_input():
 lua=runtime();open_menu(lua);lua.execute('UIAction.HideElement=function() error("hide failed") end');event(lua,'close')
 assert lua.eval('not frozen and not ModMasterDev.opened')

def test_missing_api_never_freezes_game():
 lua=runtime();lua.execute('g_gameRules.game.FreezeInput=nil;ModMasterDev:Toggle()')
 assert lua.eval('not frozen and not visible')

def test_missing_ready_handshake_restores_input():
 lua=runtime();lua.execute('ModMasterDev:Toggle();ModMasterDev:WatchMenu(ModMasterDev.tickGeneration,40)')
 assert lua.eval('not frozen and not ModMasterDev.opened')

def test_world_change_releases_input():
 lua=runtime();open_menu(lua);lua.execute('g_localActor={id=2};ModMasterDev:WatchMenu(ModMasterDev.tickGeneration,1)')
 assert lua.eval('not frozen and not visible')

def act(lua,action,activation='press'):
 lua.execute(f'Player.OnAction(g_localActor,"{action}","{activation}",1)')

def test_noclip_closes_menu_keeps_game_input_and_flies_with_game_actions():
 lua=runtime();open_menu(lua);event(lua,'tab:PLAYER');event(lua,'noclip')
 assert lua.eval('ModMasterDev.noclip~=nil and not ModMasterDev.opened and mapsEnabled and not frozen and visible')
 act(lua,'moveforward')
 assert lua.eval('#passedActions')==0  # movement is taken over, Henry does not walk
 lua.execute('fakeTime=0.1;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.5)<1e-9  # base speed 5.0 * dt 0.1s
 act(lua,'toggle_run')
 lua.execute('fakeTime=0.2;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.625)<1e-9  # precise: 5*0.25*0.1
 act(lua,'toggle_run');act(lua,'sprint')
 lua.execute('fakeTime=0.3;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-2.625)<1e-9  # fast: 5*4*0.1
 act(lua,'sprint','release');act(lua,'moveforward','release');act(lua,'jump')
 lua.execute('fakeTime=0.4;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.z')-0.5)<1e-9  # Space flies up
 act(lua,'rotateyaw')
 assert lua.eval('passedActions[1]')=='rotateyaw'  # mouse look still reaches the game
 assert lua.eval('colliderMode')==5

def test_freecam_flies_and_returns_henry_to_the_start():
 lua=runtime();open_menu(lua);event(lua,'tab:PLAYER');event(lua,'freecam')
 assert lua.eval('ModMasterDev.freecam~=nil and not ModMasterDev.opened and mapsEnabled')
 act(lua,'moveforward')
 lua.execute('fakeTime=0.1;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.5)<1e-9
 lua.execute('ModMasterDev:ToggleFreecam()')
 assert lua.eval('ModMasterDev.freecam==nil and ModMasterDev.noclip==nil')
 assert lua.eval('worldPos.x==0 and worldPos.y==0 and worldPos.z==0 and colliderMode==0')

def test_freecam_and_noclip_are_mutually_exclusive():
 lua=runtime();lua.execute('ModMasterDev:ToggleNoclip()')
 lua.execute('ModMasterDev:ToggleFreecam()')
 assert lua.eval('ModMasterDev.freecam==nil and ModMasterDev.noclip~=nil')  # refused while Noclip runs
 lua.execute('ModMasterDev:ToggleNoclip();ModMasterDev:ToggleFreecam()')
 assert lua.eval('ModMasterDev.freecam~=nil')
 lua.execute('ModMasterDev:ToggleNoclip()')  # F4 ends Freecam
 assert lua.eval('ModMasterDev.freecam==nil and ModMasterDev.noclip==nil')

def test_noclip_hotkey_binds_independent_of_menu_and_rejects_collision():
 lua=runtime()
 lua.execute('ModMasterDev:BindNoclipKey("f4")')
 assert lua.eval('ModMasterDev.settings.noclipHotkey')=='f4'
 lua.execute('ModMasterDev:BindNoclipKey("f5")')  # collides with the default menu hotkey
 assert lua.eval('ModMasterDev.settings.noclipHotkey')=='f4'  # rejected, unchanged
 lua.execute('ModMasterDev:BindMenuKey("f4")')  # collides with the noclip hotkey
 assert lua.eval('ModMasterDev.settings.hotkey')=='f5'  # rejected, unchanged

def test_god_mode_applies_without_has_buff_debug_and_refills_health():
 lua=runtime();open_menu(lua);event(lua,'god')
 lua.execute('God=select(1,ModMasterDev:PlayerOptions())')
 assert lua.eval('God')=='ON'
 assert lua.eval('g_localActor.soul.health')==100
 assert lua.eval('g_localActor.soul.buffs[ModMasterRemoveInjuriesGuid]')==True
 event(lua,'god')
 lua.execute('God2=select(1,ModMasterDev:PlayerOptions())')
 assert lua.eval('God2')=='OFF'

def test_god_mode_keeps_health_full_until_disabled():
 lua=runtime();open_menu(lua);event(lua,'god')
 lua.execute('g_localActor.soul.health=12;timers[#timers]()')
 assert lua.eval('g_localActor.soul.health')==100
 event(lua,'god')
 lua.execute('g_localActor.soul.health=12;ModMasterDev:GodTick(g_localActor)')
 assert lua.eval('g_localActor.soul.health')==12

def test_restore_health_fills_health_and_clears_injuries():
 lua=runtime();open_menu(lua);lua.execute('g_localActor.soul.health=7');event(lua,'heal')
 assert lua.eval('g_localActor.soul.health')==100
 assert lua.eval('g_localActor.soul.buffs[ModMasterRemoveInjuriesGuid]')==True

def test_hotkey_noclip_shows_hud_and_hides_it_again():
 lua=runtime();lua.execute('ModMasterDev:ToggleNoclip()')
 assert lua.eval('visible and mapsEnabled and not frozen')
 lua.execute('ModMasterDev:ToggleNoclip()')
 assert lua.eval('not visible and colliderMode==0')

def test_god_mode_handles_add_buff_returning_nothing_or_erroring():
 lua=runtime();open_menu(lua)
 lua.execute('g_localActor.soul.AddBuff=function() end')  # exists, but returns no instance
 event(lua,'god')
 lua.execute('God1=select(1,ModMasterDev:PlayerOptions())')
 assert lua.eval('God1')=='OFF' and lua.eval('ModMasterDev.opened')  # rejected cleanly, not crashed
 lua.execute('g_localActor.soul.AddBuff=function() error("unavailable") end')
 event(lua,'god')
 assert lua.eval('ModMasterDev.opened and frozen and not mapsEnabled')  # still didn't crash the menu

def test_god_noclip_restore_original_state():
 lua=runtime();open_menu(lua);event(lua,'god');event(lua,'noclip')
 lua.execute('local g,n=ModMasterDev:PlayerOptions();God1,Noclip1=g,n')
 assert lua.eval('God1')=='ON' and lua.eval('Noclip1')=='ON'
 event(lua,'close')  # god/noclip must survive menu close: state belongs to the runtime, not the menu
 lua.execute('local g,n=ModMasterDev:PlayerOptions();God2,Noclip2=g,n')
 assert lua.eval('God2')=='ON' and lua.eval('Noclip2')=='ON'
 lua.execute('ModMasterDev:RestorePlayerOptions()')
 lua.execute('local g,n=ModMasterDev:PlayerOptions();God3,Noclip3=g,n')
 assert lua.eval('God3')=='OFF' and lua.eval('Noclip3')=='OFF'

def test_shutdown_releases_input_and_restores_overrides():
 lua=runtime();open_menu(lua);event(lua,'god');event(lua,'noclip');lua.execute('ModMasterDev:Shutdown()')
 lua.execute('local g,n=ModMasterDev:PlayerOptions();God,Noclip=g,n')
 assert lua.eval('not frozen and God=="OFF" and Noclip=="OFF" and not visible')

def test_settings_hud_toggle_never_closes_menu():
 lua=runtime();open_menu(lua);event(lua,'tab:SETTINGS')
 assert lua.eval('ModMasterDev.opened and frozen')
 before=lua.eval('ModMasterDev.settings.hudEnabled')
 event(lua,'hud_toggle')
 assert lua.eval('ModMasterDev.opened and frozen and visible')
 assert lua.eval('ModMasterDev.settings.hudEnabled')!=before
 event(lua,'hud_toggle')
 assert lua.eval('ModMasterDev.opened and frozen and visible')
 assert lua.eval('ModMasterDev.settings.hudEnabled')==before

def test_settings_speed_values_apply_and_clamp():
 lua=runtime();open_menu(lua);event(lua,'tab:SETTINGS')
 event(lua,'settingvalue;8;2;0.1')
 assert lua.eval('ModMasterDev.opened')
 assert lua.eval('ModMasterDev.settings.freecamSpeed')==8
 assert lua.eval('ModMasterDev.settings.fastMult')==2
 assert abs(lua.eval('ModMasterDev.settings.slowMult')-0.1)<1e-9
 event(lua,'settingvalue;999;999;999')
 assert lua.eval('ModMasterDev.settings.freecamSpeed')==100
 assert lua.eval('ModMasterDev.settings.fastMult')==20
 assert lua.eval('ModMasterDev.settings.slowMult')==5

def test_payload_is_data_never_executable():
 lua=runtime();open_menu(lua);event(lua,"os.execute('bad')")
 assert lua.eval('ModMasterDev.message=="Unsupported UI action" and frozen')
 event(lua,'filter;chair%3B%22;props;test_mod');assert lua.eval('ModMasterDev.search==\'chair;"\'')

def test_invalid_selection_is_rejected():
 lua=runtime();open_menu(lua);event(lua,'select:-4');assert lua.eval('ModMasterDev.selected==1')

def test_restore_does_not_touch_replacement_player():
 lua=runtime();lua.execute('ModMasterDev:ToggleGod()')
 assert lua.eval('ModMasterDev.godOwner==g_localActor')
 lua.execute('''
  local newSoul={buffs={}}
  function newSoul:AddBuff(guid) self.buffs[guid]=true;return "instance:"..guid end
  function newSoul:RemoveAllBuffsByGuid(guid) self.buffs[guid]=nil end
  g_localActor={id=42,soul=newSoul}
  ModMasterDev:RestorePlayerOptions()
 ''')
 assert lua.eval('not g_localActor.soul.buffs[ModMasterGodGuid]')

def test_duplicate_close_does_not_reopen():
 lua=runtime();open_menu(lua);event(lua,'close');lua.execute('ModMasterDev:Toggle()')
 assert lua.eval('not frozen and not visible')

def test_xml_and_swf_contract():
 import struct,zlib,xml.etree.ElementTree as ET
 root=SOURCE.parent/'Libs/UI'
 xml=ET.parse(root/'UIElements/ModMasterMenu.xml').find('UIElement')
 assert xml.attrib['cursor']==xml.attrib['mouseevents']=='0'
 assert xml.attrib['keyevents']=='1'
 assert xml.attrib['events_exclusive']=='0'
 raw=(root/'ModMasterMenu.swf').read_bytes();assert raw[:3] in (b'FWS',b'CWS') and raw[3]==8
 data=raw if raw[:3]==b'FWS' else raw[:8]+zlib.decompress(raw[8:])
 assert len(data)==struct.unpack('<I',raw[4:8])[0]
 for f in xml.findall('functions/function'):
  assert f.attrib['funcname'].encode() in data
 assert b'mmSequence' in data and b'mmReady' in data
 assert b'ModMaster Sans' in data and b'Arial' not in data


def test_variable_transport_acknowledges_action_exactly_once():
 lua=runtime();lua.execute('ModMasterDev:Toggle();uiVars.Ready=true;uiVars.Sequence=1;uiVars.Action="god";ModMasterDev:WatchMenu(ModMasterDev.tickGeneration,1)')
 lua.execute('God1=select(1,ModMasterDev:PlayerOptions())')
 assert lua.eval('God1')=='ON' and lua.eval('uiVars.Ack==1 and ModMasterDev.uiReady and not mapsEnabled')
 lua.execute('ModMasterDev:WatchMenu(ModMasterDev.tickGeneration,2)')
 lua.execute('God2=select(1,ModMasterDev:PlayerOptions())')
 assert lua.eval('God2')=='ON'


def test_ui_variables_can_close_without_event_callback():
 lua=runtime();lua.execute('ModMasterDev:Toggle();uiVars.Ready=true;uiVars.Sequence=1;uiVars.Action="close";ModMasterDev:WatchMenu(ModMasterDev.tickGeneration,1)')
 assert lua.eval('not frozen and mapsEnabled and not visible')


def test_actionmap_failure_releases_other_input_state():
 lua=runtime();lua.execute('ActionMapManager.EnableActionMapManager=function(enable) if not enable then error("no") else mapsEnabled=true end end;ModMasterDev:Toggle()')
 assert lua.eval('not frozen and mapsEnabled and not ModMasterDev.opened')


def test_font_glyphs_are_embedded_instead_of_runtime_font_alias():
 import struct,json
 root=SOURCE.parent/'Libs/UI'
 data=(root/'ModMasterMenu.swf').read_bytes()
 pos=8+(5+(data[8]>>3)*4+7)//8+4
 fonts=[]
 while pos<len(data):
  head=struct.unpack_from('<H',data,pos)[0];pos+=2;size=head&63;kind=head>>6
  if size==63:size=struct.unpack_from('<I',data,pos)[0];pos+=4
  body=data[pos:pos+size];pos+=size
  if kind==75:fonts.append(body)
 assert len(fonts)==1
 font=fonts[0];name_len=font[4];assert font[5:5+name_len]==b'ModMaster Sans'
 count=struct.unpack_from('<H',font,5+name_len)[0]
 assert count==192
 offsets=struct.unpack_from('<'+str(count+1)+'I',font,7+name_len)
 assert all(b>a for a,b in zip(offsets,offsets[1:]))


def test_player_tab_handles_missing_soul_api():
 lua=runtime();open_menu(lua)
 lua.execute('g_localActor.soul.AddBuff=nil')
 event(lua,'tab:PLAYER')
 assert lua.eval('ModMasterDev.tab=="PLAYER" and ModMasterDev.opened and frozen')
 assert lua.eval('select(1,ModMasterDev:PlayerOptions())=="unavailable"')
 event(lua,'god')
 assert lua.eval('select(1,ModMasterDev:PlayerOptions())=="unavailable" and ModMasterDev.opened')

def test_player_tab_handles_native_query_errors():
 lua=runtime();open_menu(lua)
 lua.execute('g_localActor.soul.AddBuff=function() error("unavailable") end')
 event(lua,'tab:PLAYER')
 event(lua,'god')
 assert lua.eval('ModMasterDev.opened and frozen and not mapsEnabled')
