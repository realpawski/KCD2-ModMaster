class ModMasterMenu {
 static var app:ModMasterMenu;
 var root:MovieClip;var panel:MovieClip;var depth:Number;
 var shown:Boolean;var openedAt:Number;var closeKeyPressed:Boolean;var actionQueue:Array;
 var view:Number;var active:String;var entries:Array;var assets:Array;var focus:Number;var total:Number;
 var candidateKey:String;var candidateNoclipKey:String;var modalOpen:Boolean;var modal:MovieClip;var searchField:TextField;var queries:Object;var queryKey:String;
 var shiftHeld:Boolean;var ctrlHeld:Boolean;
 var espLayer:MovieClip;var espFields:Array;var espFormat:TextFormat;var overlayOnly:Boolean;var espOn:Boolean;var espRange:String;var inputMode:String;
 var cameraOnly:Boolean;var noclipHud:Boolean;var hotkey:String;var keyCode:Number;var hudEnabled:Boolean;var kind:String;
 var detail:String;var message:String;var god:String;var noclipStatus:String;var freecamStatus:String;var values:Array;var settingValues:Array;
 static function main(mc:MovieClip):Void {app=new ModMasterMenu(mc);}
 function ModMasterMenu(mc:MovieClip) {
  root=mc;depth=1;actionQueue=[];assets=[];entries=[];values=[0,0,0,0,0,0,1];settingValues=[5,4,0.25];
  overlayOnly=false;espOn=false;espRange="100";inputMode="";
  modalOpen=false;queries={};queryKey="HOME";cameraOnly=false;noclipHud=false;hotkey="f5";candidateKey="f5";keyCode=116;candidateNoclipKey="f4";hudEnabled=true;kind="static_prop";view=0;focus=0;active="ASSETS";total=0;detail="";message="Runtime connected";god="unavailable";noclipStatus="OFF";freecamStatus="OFF";
  Stage.scaleMode="showAll";Stage.align="";root.stop();
  mc["mmReady"]=false;mc["mmSequence"]=0;mc["mmAck"]=0;mc["mmAction"]="";
  var self:ModMasterMenu=this;
  mc["fc_reset"]=function(tab:String,count:Number,sel:Number,all:Number) {self.active=tab;self.assets=[];self.total=all;self.draw();};
  mc["fc_row"]=function(index:Number,title:String,sub:String,sel:Boolean) {self.assets.push({title:title,action:"select:"+index,description:sub});self.draw();};
  mc["fc_details"]=function(text:String,x:String,y:String,z:String,rx:String,ry:String,rz:String,scale:String) {self.detail=text;self.kind=text.indexOf("inventory_item")>=0?"inventory_item":"static_prop";self.values=[Number(x),Number(y),Number(z),Number(rx),Number(ry),Number(rz),Number(scale)];self.draw();};
  mc["fc_status"]=function(text:String,summary:String) {self.message=text;self.draw();};
  mc["fc_freecam"]=function(enabled:Boolean) {self.noclipHud=false;self.cameraOnly=enabled;self.shown=!enabled;mc["mmVisible"]=!enabled;self.openedAt=getTimer();self.closeKeyPressed=false;self.draw();};
  mc["fc_noclip"]=function(enabled:Boolean) {self.noclipHud=true;self.cameraOnly=enabled;self.shown=!enabled;mc["mmVisible"]=!enabled;self.openedAt=getTimer();self.closeKeyPressed=false;self.draw();};
  mc["fc_settings"]=function(key:String,code:Number,hud:Boolean,speed:String,fast:String,slow:String,noclipKey:String) {self.hotkey=key;self.candidateKey=key;self.keyCode=code;self.hudEnabled=hud;self.settingValues=[Number(speed),Number(fast),Number(slow)];self.candidateNoclipKey=noclipKey;self.draw();};
  mc["fc_overlay"]=function(enabled:Boolean) {self.overlayOnly=enabled;self.cameraOnly=false;self.shown=!enabled;mc["mmVisible"]=!enabled;self.openedAt=getTimer();self.closeKeyPressed=false;self.draw();};
  mc["fc_esp"]=function(data:String) {self.drawEsp(data);};
  mc["fc_esp_state"]=function(enabled:Boolean,range:String) {self.espOn=enabled;self.espRange=range;self.draw();};
  mc["fc_player"]=function(g:String,nc:String,fc:String) {self.god=g;self.noclipStatus=nc;self.freecamStatus=fc;self.draw();};
  mc["cry_onShow"]=function() {self.shown=true;self.cameraOnly=false;self.openedAt=getTimer();self.closeKeyPressed=false;mc["mmVisible"]=true;self.draw();};
  mc["cry_onHide"]=function() {self.shown=false;mc["mmVisible"]=false;};
  mc["cry_onBack"]=function() {self.back();};
  var keyboard:Object={};keyboard.onKeyDown=function() {var k:Number=Key.getCode();if(k==16)self.shiftHeld=true;if(k==17)self.ctrlHeld=true;self.keyDown();};
  keyboard.onKeyUp=function() {var k:Number=Key.getCode();if(k==16)self.shiftHeld=false;if(k==17)self.ctrlHeld=false;if(k==self.keyCode) {if(self.closeKeyPressed)self.emit(self.cameraOnly?"camera_menu":"close");self.closeKeyPressed=false;}};Key.addListener(keyboard);
  root.onEnterFrame=function() {
   // Arrows also navigate the list, so look keys only apply in the camera HUD.
   // Game input stays on while flying; these readings are a fallback for the Lua action hook.
   var flyKeys:Boolean=!self.modalOpen;
   mc["camForward"]=flyKeys?(Key.isDown(87)?1:0)-(Key.isDown(83)?1:0):0;
   mc["camRight"]=flyKeys?(Key.isDown(68)?1:0)-(Key.isDown(65)?1:0):0;
   mc["camUp"]=flyKeys?(Key.isDown(32)?1:0)-(Key.isDown(67)?1:0):0;
   mc["camFast"]=flyKeys && (Key.isDown(16) || self.shiftHeld)?1:0;
   mc["camSlow"]=flyKeys && (Key.isDown(17) || self.ctrlHeld)?1:0;
   mc["camPitch"]=self.cameraOnly?(Key.isDown(38)?1:0)-(Key.isDown(40)?1:0):0;
   mc["camYaw"]=self.cameraOnly?(Key.isDown(39)?1:0)-(Key.isDown(37)?1:0):0;
  if(self.actionQueue.length>0 && mc["mmAck"]==mc["mmSequence"]) {mc["mmAction"]=self.actionQueue.shift();mc["mmSequence"]++;}};
  shown=true;openedAt=getTimer();closeKeyPressed=false;mc["mmVisible"]=true;mc["mmReady"]=true;draw();
 }
 function box(x:Number,y:Number,w:Number,h:Number,color:Number,alpha:Number):Void {
  panel.beginFill(color,alpha);panel.moveTo(x,y);panel.lineTo(x+w,y);panel.lineTo(x+w,y+h);panel.lineTo(x,y+h);panel.lineTo(x,y);panel.endFill();
 }
 function label(text:String,x:Number,y:Number,w:Number,h:Number,size:Number,color:Number):Void {
  var name:String="text"+(depth++);panel.createTextField(name,depth++,x,y,w,h);var tf:TextField=panel[name];
  var fmt:TextFormat=new TextFormat();fmt.font="ModMaster Sans";fmt.size=size;fmt.color=color;fmt.bold=false;fmt.italic=false;
  tf.embedFonts=true;tf.multiline=true;tf.wordWrap=true;tf.selectable=false;tf.text=text;tf.setTextFormat(fmt);tf.setNewTextFormat(fmt);tf.textColor=color;root["mmFont"]=tf.getTextFormat().font;
 }
 function statusColor(status:String):Number {
  if(status=="on")return 0xBD9A5F;
  if(status=="off")return 0x8B8578;
  if(status=="unavailable")return 0x55504A;
  if(status=="dev")return 0xC9A227;
  if(status=="error")return 0xA85B4A;
  return 0xEDE3CC;
 }
 function breadcrumb():String {
  if(view==0) return "MODMASTER";
  var path:String="MODMASTER";
  if(active!=undefined) path+=" / "+active;
  if(view==1 && active=="ASSETS" && queryKey!=undefined && queryKey!="HOME" && queryKey!="all") path+=" / "+queryKey.toUpperCase();
  return path;
 }
 function add(title:String,action:String,description:String,status:String):Void {entries.push({title:title,action:action,description:description,status:status});}
 function build():Void {
  entries=[];
  if(view==0) {
   add("Asset Browser  >","tab:ASSETS","Browse installed spawnable assets.",undefined);
   add("NPCs  >","category:npcs","Spawn people with their own AI, schedule and animations. 'Random NPC' picks a new one each time.",undefined);
   add("Animals  >","category:animals","Spawn living animals that move and react. 'Random Boar', 'Random Wolf' and so on pick a new one each time.",undefined);
   add("Weapons  >","category:weapons","Give real mod weapon items to inventory.",undefined);
   add("Armor  >","category:armor","Give real mod armor items to inventory.",undefined);
   add("Props  >","category:props","Place compiled mod props into the world.",undefined);
   add("Other Items  >","category:items","Inventory items from the installed game database.",undefined);
   add("Active Spawns  >","tab:SPAWNS","Edit or remove entities created by ModMaster.",undefined);
   add("Player Tools  >","tab:PLAYER","Freecam, Noclip, God Mode and restoration.",undefined);
   add("World / Lighting  >","tab:WORLD","Preview lighting without advancing quest time.",undefined);
   add("Settings  >","tab:SETTINGS","HUD overlay, menu hotkey and Freecam/Noclip speed.",undefined);
   add("Close Menu","close","Return control to the game.",undefined);
  } else if(active=="PLAYER") {
   add("God Mode  ["+god.toUpperCase()+"]","god",
    "Henry cannot die and his health is kept full. Stays active while the menu is closed and is never saved.\n\nStatus\n"+god.toUpperCase()+"\n\nBackend\nVanilla immortality buff + health refill",
    god=="ON"?"on":(god=="unavailable"?"unavailable":"off"));
   add("Restore Health","heal","Fill health to maximum and clear injuries.",undefined);
   add("Entity ESP  ["+(espOn?"ON":"OFF")+"]","esp_toggle","Shows the name and distance above NPCs and animals within the ESP view range ("+espRange+" m). Stays on while the menu is closed. Change the range under Settings.",espOn?"on":"off");
   add("Freecam  ["+freecamStatus+"]","freecam",
    "Fly freely through walls and terrain while the mouse steers the view. When Freecam ends, Henry is back where he started.\n\nControls\nWASD  Fly\nSpace / C  Up / Down\nMouse wheel  Faster / slower\nF4  Stop\n\nSpeed\n"+(Math.round(settingValues[0]*100)/100)+"\n\nStatus\n"+freecamStatus+"\n\nBackend\nCollision off, position restored on exit",
    freecamStatus=="ON"?"on":"off");
   add("Noclip  ["+noclipStatus+"]","noclip",
    "Henry flies through walls, doors, terrain, props and NPCs while the mouse steers the view. He stays where Noclip ends.\n\nControls\nWASD  Fly\nSpace / C  Up / Down\nMouse wheel  Faster / slower\nF4  Stop\n\nSpeed\n"+(Math.round(settingValues[0]*100)/100)+"\n\nStatus\n"+noclipStatus+"\n\nBackend\nModMaster Noclip (direct position write, physics off)",
    noclipStatus=="ON"?"on":"off");
   add("Restore Player Options","restore_player","Turn off God Mode / Freecam / Noclip and restore the values they changed.",undefined);
  } else if(active=="SETTINGS") {
   add("HUD Overlay  ["+(hudEnabled?"ON":"OFF")+"]","hud_toggle",
    "Show a small Freecam/Noclip status overlay when the menu is closed.\n\nThis setting never touches gameplay input -- only whether the small overlay is drawn.",
    hudEnabled?"on":"off");
   add("Menu Hotkey  ["+candidateKey.toUpperCase()+"]","hotkey_next","Left / Right: choose F2 to F11. Enter: apply. Avoid keys used by your game. Current session setting.",undefined);
   add("Noclip Hotkey  ["+candidateNoclipKey.toUpperCase()+"]","noclip_hotkey_next","Left / Right: choose F2 to F11 (must differ from the Menu Hotkey). Enter: apply. Works even with the menu closed -- Noclip does not need the menu at all.",undefined);
   add("ESP View Range  ["+espRange+" m]","esp_range_edit","Enter: type a range in metres (5 to 2000). Default 100.",undefined);
   add("Freecam Speed  < "+(Math.round(settingValues[0]*100)/100)+" >","setting:0","Left / Right: adjust the base Freecam/Noclip speed. Enter: apply.",undefined);
   add("Fast Multiplier  < "+(Math.round(settingValues[1]*100)/100)+"x >","setting:1","Left / Right: adjust the Shift speed multiplier. Enter: apply.",undefined);
   add("Precision Multiplier  < "+(Math.round(settingValues[2]*100)/100)+"x >","setting:2","Left / Right: adjust the Ctrl speed multiplier. Enter: apply.",undefined);
  } else if(active=="WORLD") {
   add("Photo Mode Range: Unlimited","photomode:unlimited","Lets the F1 photo mode camera travel as far as you like instead of staying in a small box around Henry. Current session.",undefined);
   add("Photo Mode Range: Default","photomode:default","Restores the game's own photo mode range.",undefined);
   add("Morning","time:7","Preview 07:00 lighting.",undefined);add("Noon","time:12","Preview 12:00 lighting.",undefined);add("Sunset","time:19","Preview 19:00 lighting.",undefined);add("Night","time:0","Preview midnight lighting.",undefined);add("Restore Lighting","restore_world","Restore normal lighting.",undefined);
  } else if(view==1) {
   for(var i:Number=0;i<assets.length;i++)entries.push(assets[i]);
   if(assets.length==0)add("NO RESULTS","none","No assets match. Try a different search term or category.",undefined);
   if(total>6) {add("Previous Page","previous_page","Show earlier entries.",undefined);add("Next Page","next_page","Show later entries.",undefined);}
  } else if(active=="ASSETS") {
   if(kind=="inventory_item")add("Give To Inventory","give",detail,undefined);else {add("Spawn In Front","spawn_front",detail,undefined);add("Spawn At Crosshair","spawn",detail,undefined);}
  } else {
   add("Duplicate Entity","duplicate",detail,undefined);add("Reset Transform","reset",detail,undefined);
   var names:Array=["Position X","Position Y","Position Z","Rotation X","Rotation Y","Rotation Z","Scale"];
   for(var j:Number=0;j<names.length;j++)add(names[j]+"  < "+Math.round(values[j]*100)/100+" >","value:"+j,"Left / Right: adjust. Enter: apply. Rotation in radians; position step 0.25; rotation / scale step 0.05.",undefined);
   add("Remove Entity","despawn","Remove only this ModMaster entity.",undefined);add("Remove All Owned Entities","clear","Remove all ModMaster entities.",undefined);
  }
  var query:String=queries[queryKey]==undefined?"":String(queries[queryKey]);
  if(active!="ASSETS" || view==0) {
   if(query.length>0) {var filtered:Array=[];for(var q:Number=0;q<entries.length;q++)if(entries[q].title.toLowerCase().indexOf(query.toLowerCase())>=0)filtered.push(entries[q]);entries=filtered;}
  }
  if(entries.length==0)add("NO RESULTS","none","Change the search text.",undefined);
  entries.unshift({title:"Search: "+(query.length>0?query:"[Enter]"),action:"open_search",description:"Enter: edit search. Ctrl+A selects all; Delete clears; Ctrl+C / Ctrl+V copy and paste."});
  focus=Math.max(0,Math.min(entries.length-1,focus));
 }
 function espField(index:Number):TextField {
  if(espFields[index]!=undefined)return espFields[index];
  espLayer.createTextField("esp"+index,index+1,0,0,260,22);var tf:TextField=espLayer["esp"+index];
  tf.embedFonts=true;tf.selectable=false;
  // Black outline keeps the labels readable on bright sky and snow.
  var Glow=_global["flash"]["filters"]["GlowFilter"];
  if(Glow!=undefined)tf.filters=[new Glow(0x000000,1,3,3,6,1)];
  else {_global.gfxExtensions=true;tf["shadowStyle"]="s{1,0}{-1,0}{0,1}{0,-1}";tf["shadowColor"]=0x000000;}
  espFields[index]=tf;return tf;
 }
 function drawEsp(data:String):Void {
  if(espLayer==undefined) {
   espLayer=root.createEmptyMovieClip("espLayer",90000);espFields=[];
   espFormat=new TextFormat();espFormat.font="ModMaster Sans";espFormat.size=13;espFormat.color=0xF2D58A;espFormat.align="center";
  }
  var rows:Array=(data==undefined || data=="")?[]:data.split("\n");
  var used:Number=0;
  for(var r:Number=0;r<rows.length;r++) {
   var parts:Array=rows[r].split("|");if(parts.length<3)continue;
   var tf:TextField=espField(used++);
   tf._x=Number(parts[0])*12.8-130;tf._y=Number(parts[1])*7.2-20;
   var text:String=parts.slice(2).join("|");
   if(tf.text!=text) {tf.text=text;tf.setTextFormat(espFormat);}
   tf._visible=true;
  }
  for(var i:Number=used;i<espFields.length;i++)espFields[i]._visible=false;
 }
 function draw():Void {
  build();if(panel!=undefined)panel.removeMovieClip();depth=1;panel=root.createEmptyMovieClip("panel",depth++);
  if(overlayOnly && !shown && !cameraOnly)return;
  if(cameraOnly) {
   if(!hudEnabled)return;
   box(34,48,350,58,0x17130F,88);box(34,48,350,3,0xBD9A5F,100);
   label((noclipHud?"MODMASTER NOCLIP":"MODMASTER FREECAM")+"   Speed "+(Math.round(settingValues[0]*100)/100),44,55,330,20,12,0xEDE3CC);
   label("WASD fly | Space/C up/down | Wheel speed | "+candidateNoclipKey.toUpperCase()+" stop | "+hotkey.toUpperCase()+" menu",44,76,330,26,10,0xA89C86);
   return;
  }
  var start:Number=Math.floor(focus/9)*9;var count:Number=Math.min(9,entries.length-start);
  box(34,48,292,62,0xE4D6B8,100);
  label("KCD2 MODMASTER",46,59,266,28,21,0x241C12);
  label("RUNTIME 0.6.0",48,87,266,16,10,0x6B5A3A);
  box(34,110,292,3,0xBD9A5F,100);
  box(34,113,292,25,0x100D0A,94);
  var crumb:String=breadcrumb();
  if(view==1 && active=="ASSETS") crumb+="   ("+total+(total==1?" result)":" results)");
  label(crumb,46,116,266,20,12,0xEDE3CC);
  for(var i:Number=0;i<count;i++) {
   var index:Number=start+i;var y:Number=140+i*31;var hi:Boolean=index==focus;var e:Object=entries[index];
   box(34,y,292,31,hi?0xE4D6B8:0x17130F,hi?100:88);
   var tcol:Number=hi?0x241C12:(e.status!=undefined?statusColor(e.status):0xEDE3CC);
   label(e.title,46,y+6,267,25,14,tcol);
  }
  var footer:Number=140+count*31;
  box(34,footer,292,3,0x3A2C1D,100);box(34,footer+3,292,64,0x100D0A,94);
  label((focus+1)+" / "+entries.length+"    Up/Down select",46,footer+9,268,20,11,0xEDE3CC);
  label("Enter / Right confirm   Delete / Esc back\n"+hotkey.toUpperCase()+" close",46,footer+29,268,34,10,0xA89C86);
  box(342,48,278,34,0xE4D6B8,100);label("INFORMATION",354,56,254,24,13,0x241C12);
  box(342,82,278,218,0x17130F,88);
  label(entries[focus].description,354,94,254,170,13,0xEDE3CC);
  label(message,354,270,254,28,11,0xA89C86);
 }
 function openSearch():Void {
  inputMode="";
  modalOpen=true;modal=root.createEmptyMovieClip("searchDialog",100000);
  modal.beginFill(0x17130F,98);modal.lineStyle(1,0xBD9A5F,100);modal.moveTo(390,250);modal.lineTo(890,250);modal.lineTo(890,430);modal.lineTo(390,430);modal.lineTo(390,250);modal.endFill();
  modal.createTextField("heading",1,410,270,460,30);var heading:TextField=modal["heading"];
  var fmt:TextFormat=new TextFormat();fmt.font="ModMaster Sans";fmt.size=20;fmt.color=0xEDE3CC;heading.embedFonts=true;heading.text="SEARCH";heading.setTextFormat(fmt);
  modal.createTextField("input",2,410,315,460,38);searchField=modal["input"];searchField.embedFonts=true;searchField.type="input";searchField.selectable=true;searchField.multiline=false;searchField.maxChars=128;searchField.background=true;searchField.backgroundColor=0x241C12;searchField.border=true;searchField.borderColor=0xBD9A5F;
  searchField.text=queries[queryKey]==undefined?"":String(queries[queryKey]);searchField.setTextFormat(fmt);searchField.setNewTextFormat(fmt);searchField.textColor=0xEDE3CC;
  modal.createTextField("help",3,410,375,460,35);var help:TextField=modal["help"];fmt.size=12;help.embedFonts=true;help.text="Enter: search | Esc: cancel | Ctrl+A / C / V";help.setTextFormat(fmt);
  Selection.setFocus(searchField);Selection.setSelection(searchField.text.length,searchField.text.length);
 }
 function openRangeInput():Void {
  openSearch();inputMode="esp_range";
  var heading:TextField=modal["heading"];var fmt:TextFormat=heading.getTextFormat();heading.text="ESP VIEW RANGE (METRES)";heading.setTextFormat(fmt);
  searchField.restrict="0-9";searchField.maxChars=4;searchField.text=espRange;searchField.setTextFormat(searchField.getNewTextFormat());
  var help:TextField=modal["help"];var hfmt:TextFormat=help.getTextFormat();help.text="Enter: apply | Esc: cancel | 5 to 2000";help.setTextFormat(hfmt);
  Selection.setFocus(searchField);Selection.setSelection(0,searchField.text.length);
 }
 function closeSearch():Void {modalOpen=false;Selection.setFocus(null);modal.removeMovieClip();searchField=null;}
 function emit(value:String):Void {if(actionQueue.length<32)actionQueue.push(value);}
 function back():Void {if(!shown)return;if(view>0) {view--;if(view==0)queryKey="HOME";focus=0;draw();}else emit("close");}
 function activate():Void {
  var action:String=entries[focus].action;if(action=="none")return;
  if(action=="open_search") {openSearch();return;}
  if(action=="esp_range_edit") {openRangeInput();return;}
  if(action=="hotkey_next") {emit("hotkey:"+candidateKey);return;}
  if(action=="noclip_hotkey_next") {emit("noclip_hotkey:"+candidateNoclipKey);return;}
  if(action.substr(0,9)=="category:") {active="ASSETS";queryKey=action.substr(9);view=1;focus=0;assets=[];detail="";emit("filter;"+escape(queries[queryKey]==undefined?"":queries[queryKey])+";"+action.substr(9)+";");emit("tab:ASSETS");draw();}
  else if(action.substr(0,4)=="tab:") {active=action.substr(4);queryKey=active=="ASSETS"?"all":active; if(active=="ASSETS")emit("filter;"+escape(queries[queryKey]==undefined?"":queries[queryKey])+";;");view=1;focus=0;assets=[];detail="";emit(action);draw();}
  else if(action.substr(0,7)=="select:") {view=2;focus=0;emit(action);draw();}
  else if(action.substr(0,6)=="value:")emit("transform;"+values.join(";"));
  else if(action.substr(0,8)=="setting:")emit("settingvalue;"+settingValues.join(";"));
  else {emit(action);if(action=="despawn" || action=="clear") {view=1;focus=0;draw();}}
 }
 function keyDown():Void {
  var code:Number=Key.getCode();
  if(modalOpen) {
   if(code==13 && inputMode=="esp_range") {var range:String=searchField.text;closeSearch();inputMode="";if(range.length>0) {espRange=range;emit("esp_range:"+range);}draw();return;}
   if(code==13) {var query:String=searchField.text;closeSearch();focus=0;if(view==0 && query.length>0) {queries["HOME"]="";queryKey="all";queries["all"]=query;active="ASSETS";view=1;assets=[];detail="";emit("filter;"+escape(query)+";;");emit("tab:ASSETS");draw();return;}queries[queryKey]=query;if((active=="ASSETS" || active=="SPAWNS") && view>0)emit("search:"+escape(query));draw();}
   else if(code==27)closeSearch();
   else if(code==65 && Key.isDown(17))Selection.setSelection(0,searchField.text.length);
   return;
  }
  if(cameraOnly) {if(code==keyCode && getTimer()-openedAt>=500)closeKeyPressed=true;return;}
  if(!shown)return;
  if(code==keyCode) {if(getTimer()-openedAt>=500)closeKeyPressed=true;return;}
  if(code==27 || code==8 || code==46) {back();return;}
  if(code==38 || code==40) {focus=(focus+entries.length+(code==38?-1:1))%entries.length;draw();return;}
  if(code==13) {activate();return;}
  if(code==37 || code==39) {
   var action:String=entries[focus].action;
   if(action=="hotkey_next") {var number:Number=Number(candidateKey.substr(1));number=2+(number-2+(code==37?9:1))%10;candidateKey="f"+number;draw();}
   else if(action=="noclip_hotkey_next") {var nn:Number=Number(candidateNoclipKey.substr(1));nn=2+(nn-2+(code==37?9:1))%10;candidateNoclipKey="f"+nn;draw();}
   else if(action.substr(0,6)=="value:") {var index:Number=Number(action.substr(6));var step:Number=index<3?0.25:0.05;values[index]+=code==37?-step:step;if(index==6)values[index]=Math.max(0.05,Math.min(100,values[index]));draw();}
   else if(action.substr(0,8)=="setting:") {var si:Number=Number(action.substr(8));var sstep:Number=si==0?0.5:0.25;settingValues[si]=Math.max(0.1,settingValues[si]+(code==37?-sstep:sstep));draw();}
   else if(code==39)activate();
  }
 }
}
