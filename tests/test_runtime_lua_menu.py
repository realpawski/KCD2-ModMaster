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
 flightMap={};ActionMapManager={EnableActionMapManager=function(enable,reset) mapsEnabled=enable end,
  LoadFromXML=function(path) flightMap.loaded=path end,SetActionListener=function(map,id) flightMap.listener=id end,
  EnableActionMap=function(map,on) flightMap[map]=on end}
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
 assert lua.eval('flightMap.loaded')=='Libs/Config/ModMasterActionMaps.xml'
 assert lua.eval('flightMap.modmaster_flight==true and flightMap.listener==1')
 act(lua,'modmaster_fly_forward')
 assert lua.eval('#passedActions')==0
 lua.execute('fakeTime=0.1;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.5)<1e-9  # base speed 5.0 * dt 0.1s
 act(lua,'modmaster_fly_precise')
 lua.execute('fakeTime=0.2;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.625)<1e-9  # precise: 5*0.25*0.1
 act(lua,'modmaster_fly_precise');act(lua,'modmaster_fly_fast')
 lua.execute('fakeTime=0.3;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-2.625)<1e-9  # fast: 5*4*0.1
 act(lua,'modmaster_fly_fast','release');act(lua,'modmaster_fly_forward','release');act(lua,'modmaster_fly_up')
 lua.execute('fakeTime=0.4;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.z')-0.5)<1e-9  # Space flies up
 act(lua,'rotateyaw')
 assert lua.eval('passedActions[1]')=='rotateyaw'  # mouse look still reaches the game
 assert lua.eval('colliderMode')==5
 lua.execute('ModMasterDev:ToggleNoclip()')
 assert lua.eval('flightMap.modmaster_flight==false')

def test_freecam_flies_and_returns_henry_to_the_start():
 lua=runtime();open_menu(lua);event(lua,'tab:PLAYER');event(lua,'freecam')
 assert lua.eval('ModMasterDev.freecam~=nil and not ModMasterDev.opened and mapsEnabled')
 act(lua,'modmaster_fly_forward')
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


def test_rigged_models_spawn_as_animated_objects():
 lua=runtime()
 lua.execute('''
  spawned={}
  System.SpawnEntity=function(spec) table.insert(spawned,spec);return {id=#spawned,GetWorldAngles=function() return {x=0,y=0,z=0} end,GetScale=function() return 1 end} end
  System.GetEntity=function() end;System.RemoveEntity=function() end
  ModMasterDev:SpawnAsset({id="pig",name="Pig",model_path="Objects/modmaster/pig/pig.cdf",animation="relaxed_idle_new"},{x=0,y=0,z=0})
  ModMasterDev:SpawnAsset({id="crate",name="Crate",model_path="Objects/modmaster/crate/crate.cgf"},{x=0,y=0,z=0})
 ''')
 assert lua.eval('spawned[1].class')=='AnimObject'
 assert lua.eval('spawned[1].properties.Animation.Animation')=='relaxed_idle_new'
 assert lua.eval('spawned[1].properties.Animation.bPlaying and spawned[1].properties.Animation.bLoop')
 assert lua.eval('spawned[2].class')=='BasicEntity'


def test_photo_mode_range_is_widened_and_restored():
 lua=runtime()
 lua.execute('''cvars={wh_photomode_MaxDistance=20}
  System.GetCVar=function(name) return cvars[name] end
  System.SetCVar=function(name,value) cvars[name]=value end''')
 open_menu(lua);event(lua,'photomode:unlimited')
 assert lua.eval('cvars.wh_photomode_MaxDistance')==100000
 event(lua,'photomode:default')
 assert lua.eval('cvars.wh_photomode_MaxDistance')==20


def test_souls_spawn_as_their_class_with_the_chosen_soul_and_are_tracked():
 lua=runtime()
 lua.execute('''
  specs={};entities={}
  System.SpawnEntity=function(spec) table.insert(specs,spec);local id=100+#specs
   local e={id=id,soul={},GetName=function() return spec.name end,GetWorldPos=function() return spec.position end,
    GetWorldAngles=function() return {x=0,y=0,z=0} end,GetScale=function() return 1 end};entities[id]=e;return e end
  System.GetEntity=function(id) return entities[id] end;System.RemoveEntity=function(id) entities[id]=nil end
  NPC={Properties={fileModel="male.cdf",NPC={aianchorHome=""}},OnReset=function() end}
  Boar={Properties={fileModel="boar.cdf"}}
  ModMasterDev.assets={{id="soul:b1",spawn_type="soul",archetype="Boar",soul_guid="0a1b2c3d-0000-0000-0000-0000000000b1"}}
  ModMasterDev:SpawnSoul({id="soul:x",name="Hans",soul_guid="0a1b2c3d-0000-0000-0000-000000000001",archetype="NPC",entity_class="NPC",category="npcs"},{x=0,y=3,z=0})
  ModMasterDev:SpawnSoul({id="soul:Boar",name="Random Boar",archetype="Boar",entity_class="Boar",category="animals"},{x=0,y=3,z=0})
  ModMasterDev:SpawnSoul({id="soul:Wolf",name="Random Wolf",archetype="Wolf",entity_class="Wolf",category="animals"},{x=0,y=3,z=0})
 ''')
 assert lua.eval('specs[1].class=="NPC" and specs[2].class=="Boar"')
 assert lua.eval('specs[1].properties.guidSharedSoulId')=='0a1b2c3d-0000-0000-0000-000000000001'
 assert lua.eval('specs[1].properties.fileModel=="male.cdf" and specs[1].properties.NPC~=NPC.Properties.NPC')
 assert lua.eval('specs[2].properties.guidSharedSoulId')=='0a1b2c3d-0000-0000-0000-0000000000b1'
 assert lua.eval('NPC.Properties.guidSharedSoulId==nil')  # class defaults stay untouched
 assert lua.eval('#specs')==2  # no Wolf soul known, nothing requested
 assert lua.eval('#ModMasterDev:ActiveSpawns()')==2
 lua.execute('ModMasterDev:Clear()')
 assert lua.eval('#ModMasterDev.spawns')==0


def test_mod_creatures_get_their_model_stats_and_health():
 lua=runtime()
 lua.execute('''
  specs={};removed={};levels={};health=100;soulReady=true;spawned={}
  System.SpawnEntity=function(spec) table.insert(specs,spec)
   local soul=soulReady and {SetStatLevel=function(s,n,v) levels[n]=v end,SetState=function(s,n,v) health=v end,
    GetState=function(s,n) return health end} or nil
   local e={id=#specs,soul=soul,GetName=function() return spec.name end,
    LoadCharacter=function(self,slot,model) loaded={slot=slot,model=model} end};spawned[e.id]=e;return e end
  System.RemoveEntity=function(id) table.insert(removed,id) end
  System.GetEntity=function(id) return spawned[id] end
  Boar={Properties={fileModel="boar.cdf"}}
  ModMasterDev.assets={{id="soul:b1",spawn_type="soul",archetype="Boar",soul_guid="0a1b2c3d-0000-0000-0000-0000000000b1"},
   {id="creature:other",spawn_type="soul",archetype="Boar",soul_guid="0a1b2c3d-0000-0000-0000-00000000beef",source="compiled_custom"}}
  creature={id="creature:wizard",name="Wizard Boar",spawn_type="soul",archetype="Boar",entity_class="Boar",category="animals",
   soul_guid="0a1b2c3d-0000-0000-0000-00000000c0de",model_path="Objects/modmaster/wizard/wizard.cdf",health=250,
   stats={strength=12},source="compiled_custom"}
  ModMasterDev:SpawnSoul(creature,{x=0,y=3,z=0})
  local apply,look=timers[#timers-1],timers[#timers]
  look()
  apply()
  health=60;timers[#timers]()
 ''')
 assert lua.eval('loaded.slot==0 and loaded.model')=='Objects/modmaster/wizard/wizard.cdf'
 # 250 health: a hit of 40 only costs 16, so the creature lasts 2.5 times as long.
 assert abs(lua.eval('health')-84)<1e-9
 assert lua.eval('specs[1].properties.fileModel')=='Objects/modmaster/wizard/wizard.cdf'
 assert lua.eval('specs[1].properties.guidSharedSoulId')=='0a1b2c3d-0000-0000-0000-00000000c0de'
 assert lua.eval('levels.strength==12')
 lua.execute('specs={};soulReady=false;ModMasterDev:SpawnSoul(creature,{x=0,y=3,z=0})')
 # Without the mod's soul in the game the creature borrows a game soul and keeps its model.
 assert lua.eval('#removed==1 and specs[2].properties.guidSharedSoulId')=='0a1b2c3d-0000-0000-0000-0000000000b1'
 assert lua.eval('specs[2].properties.fileModel')=='Objects/modmaster/wizard/wizard.cdf'


def test_registry_rejects_unsafe_creature_values():
 lua=runtime()
 lua.execute('''
  local reg={format_version=1,runtime_version=ModMasterDev.version,mods={{id="m",name="m",assets={
   {id="ok",name="Ok",spawn_type="soul",archetype="Boar",soul_guid="0a1b2c3d-0000-0000-0000-00000000c0de",health=200,stats={strength=10},model_path="Objects/a/b.cdf"},
   {id="bad_model",name="B",spawn_type="soul",archetype="Boar",model_path="../evil.cdf"},
   {id="bad_stats",name="C",spawn_type="soul",archetype="Boar",stats={speech=5}},
   {id="bad_health",name="D",spawn_type="soul",archetype="Boar",health=-1}}}}}
  Script.ReloadScript=function() ModMasterRegistry=reg end
  ModMasterDev:LoadRegistry()
 ''')
 assert lua.eval('#ModMasterDev.assets')==1


def test_unloaded_classes_spawn_with_their_default_soul():
 lua=runtime()
 lua.execute('''
  specs={}
  System.SpawnEntity=function(spec) table.insert(specs,spec);return {id=7,GetName=function() return spec.name end} end
  System.GetEntity=function(id) end
  ModMasterDev:SpawnSoul({id="soul:h",name="Horse2",soul_guid="0a1b2c3d-0000-0000-0000-0000000000a1",archetype="Horse",entity_class="Horse",category="animals"},{x=0,y=3,z=0})
 ''')
 assert lua.eval('#specs==1 and specs[1].class=="Horse" and specs[1].properties==nil')
 assert lua.eval('ModMasterDev.spawns[1].id')==7


def test_mouse_wheel_changes_flight_speed_without_touching_movement():
 lua=runtime();open_menu(lua);event(lua,'tab:PLAYER');event(lua,'noclip')
 act(lua,'modmaster_fly_speed_up')
 assert abs(lua.eval('ModMasterDev.settings.freecamSpeed')-6.25)<1e-9
 act(lua,'modmaster_fly_speed_down');act(lua,'modmaster_fly_speed_down')
 assert abs(lua.eval('ModMasterDev.settings.freecamSpeed')-4.0)<1e-9
 act(lua,'modmaster_fly_forward')
 lua.execute('fakeTime=0.1;ModMasterDev:NoclipTick(ModMasterDev.noclip)')
 assert abs(lua.eval('worldPos.y')-0.4)<1e-9
 assert lua.eval('#passedActions')==0
 for _ in range(40): act(lua,'modmaster_fly_speed_down')
 assert lua.eval('ModMasterDev.settings.freecamSpeed')==0.5


def test_esp_labels_nearby_creatures_with_distance_and_keeps_an_overlay():
 lua=runtime()
 lua.execute('''
  System.GetViewCameraFov=function() return math.rad(60) end
  local function npc(name,x,y) return {id=name,soul={},GetName=function() return name end,GetWorldPos=function() return {x=x,y=y,z=0} end} end
  System.GetEntitiesInSphere=function(c,r) sphere=r;return {g_localActor,npc("Hans",0,10),npc("Behind",0,-10),{id="rock",GetWorldPos=function() return {x=0,y=5,z=0} end}} end
  ModMasterDev:ToggleEsp()
 ''')
 assert lua.eval('ModMasterDev.esp==true and visible and sphere==100')
 labels=[c for c in lua.eval('calls').values() if c[3]=='Esp']
 text=labels[-1][4]
 assert text.startswith('50.0|') and 'Hans  10m' in text and 'Behind' not in text and 'rock' not in text
 lua.execute('sphere=nil;System.GetViewCameraDir=function() return {x=0.1,y=1,z=0} end;timers[#timers]()')
 labels=[c for c in lua.eval('calls').values() if c[3]=='Esp']
 assert lua.eval('sphere')is None and not labels[-1][4].startswith('50.0|')  # moved with the camera, no new query
 open_menu(lua)
 event(lua,'esp_range:250');assert lua.eval('ModMasterDev.espRange')==250
 event(lua,'esp_range:abc');event(lua,'esp_range:99999');assert lua.eval('ModMasterDev.espRange')==250
 event(lua,'close');assert lua.eval('visible')  # overlay stays for the labels
 lua.execute('ModMasterDev:ToggleEsp()');assert lua.eval('not visible')
