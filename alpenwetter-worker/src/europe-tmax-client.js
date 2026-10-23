export const TMAX_JS = String.raw`
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const canvas=$("tmaxCanvas"),ctx=canvas.getContext("2d",{alpha:false});
const PREFIX="/wolkenlabor/data/europa-tmax/";
const GEO="/wolkenlabor/data/geo.json";
// Original DWD grid covers a broader area than the MAIN broadcast crop.
const MAIN={west:-24.8,east:62,south:33.5,north:71,x:220,y:108,w:1610,h:835};
const INSETS=[
 {city:"Azoren",name:"Azoren · Ponta Delgada",west:-29,east:-23.4,south:36.5,north:39.8,x:22,y:526,w:178,h:177},
 {city:"Kanaren",name:"Kanaren · Teneriffa",west:-18.7,east:-13.4,south:27,north:30.5,x:22,y:761,w:178,h:177}
];
const STOPS=[
 [-35,"#1b2572"],[-20,"#2352ad"],[-10,"#319ad2"],[0,"#6ecad2"],
 [7,"#53a976"],[13,"#a7c567"],[18,"#f6d762"],[23,"#f9984e"],
 [28,"#eb5f4b"],[34,"#ce3e5f"],[45,"#772b5e"]
];
const state={data:null,geo:null,index:0,pictures:new Map(),showField:true,
 showPoints:true,showNames:true,density:"dense",busy:false,
 catalog:[],prefs:{hidden:[],custom:[],positions:{},styles:{},values:{},globalFill:"#ffffff"},editMode:"off",hits:[],drag:null,
 selectedSearch:null,pointTarget:null,editorOpen:false,selectedKey:null};
function xy(lon,lat,region=MAIN){return [
 region.x+(lon-region.west)/(region.east-region.west)*region.w,
 region.y+(region.north-lat)/(region.north-region.south)*region.h
];}
function rectPath(region){
 ctx.beginPath();ctx.rect(region.x,region.y,region.w,region.h);ctx.clip();
}
function regionForCity(name){return INSETS.find(r=>r.city===name)||MAIN;}
function regionForPlace(s){return s.is_custom?(INSETS.find(r=>isInRegion(s.lon,s.lat,r))||MAIN):regionForCity(s.city);}
function isInRegion(lon,lat,region,margin=0){
 return lon>=region.west+margin&&lon<=region.east-margin&&
        lat>=region.south+margin&&lat<=region.north-margin;
}
function dateLabel(iso){
 const d=new Date(iso+"T12:00:00Z");
 return new Intl.DateTimeFormat("de-DE",{weekday:"short",day:"2-digit",month:"long",year:"numeric",timeZone:"UTC"}).format(d);
}
function setStatus(msg,error=false){
 const el=$("tmaxStatus");el.textContent=msg;el.className="status"+(error?" error":"");
}
function bg(){
 ctx.fillStyle="#f5f8fb";ctx.fillRect(0,0,canvas.width,canvas.height);
 const grad=ctx.createLinearGradient(0,MAIN.y,0,MAIN.y+MAIN.h);
 grad.addColorStop(0,"#4e799b");grad.addColorStop(1,"#6695aa");
 ctx.fillStyle=grad;ctx.fillRect(MAIN.x,MAIN.y,MAIN.w,MAIN.h);
 for(const inset of INSETS){
  ctx.fillStyle="#eaf0f4";ctx.fillRect(inset.x-3,inset.y-31,inset.w+6,inset.h+34);
  ctx.strokeStyle="#9babbb";ctx.lineWidth=2;
  ctx.strokeRect(inset.x-3,inset.y-31,inset.w+6,inset.h+34);
  ctx.fillStyle="#315d7b";ctx.fillRect(inset.x,inset.y,inset.w,inset.h);
  ctx.fillStyle="#233e55";ctx.font="bold 16px system-ui";ctx.textAlign="center";
  ctx.fillText(inset.name,inset.x+inset.w/2,inset.y-11,inset.w);
  ctx.textAlign="left";
 }
}
function strokeGeography(region){
 if(!state.geo?.countries)return;
 ctx.save();rectPath(region);
 for(const country of state.geo.countries){
  for(const poly of country.p||[]){
   ctx.beginPath();
   for(const ring of poly){
    let valid=false;
    for(const point of ring){
     if(!Array.isArray(point)||point.length<2)continue;
     const [x,y]=xy(point[0],point[1],region);
     if(!valid){ctx.moveTo(x,y);valid=true}else ctx.lineTo(x,y);
    }
    if(valid)ctx.closePath();
   }
   // Real Natural Earth coastline; no artistic/fictional islands.
   ctx.fillStyle="rgba(248,248,236,.06)";
   try{ctx.fill("evenodd")}catch(_){ctx.fill()}
   ctx.strokeStyle="rgba(20,46,61,.8)";
   ctx.lineWidth=region===MAIN?1.4:1.0;ctx.stroke();
  }
 }
 ctx.restore();
}
function drawCoast(){
 strokeGeography(MAIN);
 for(const inset of INSETS)strokeGeography(inset);
}
function drawIconField(image){
 const bounds=state.data?.grid;
 if(!image||!bounds)return;
 const sx=(MAIN.west-bounds.west)/(bounds.east-bounds.west)*image.naturalWidth;
 const sy=(bounds.north-MAIN.north)/(bounds.north-bounds.south)*image.naturalHeight;
 const sw=(MAIN.east-MAIN.west)/(bounds.east-bounds.west)*image.naturalWidth;
 const sh=(MAIN.north-MAIN.south)/(bounds.north-bounds.south)*image.naturalHeight;
 if(sx<0||sy<0||sx+sw>image.naturalWidth+.5||sy+sh>image.naturalHeight+.5)
  throw Error("Temperaturfeld und Kartenausschnitt stimmen nicht überein");
 ctx.save();rectPath(MAIN);
 ctx.drawImage(image,sx,sy,sw,sh,MAIN.x,MAIN.y,MAIN.w,MAIN.h);
 ctx.restore();
}
function drawLegend(){
 const start=500,end=1380,barY=1006,height=17;
 const grad=ctx.createLinearGradient(start,0,end,0);
 for(const [temp,color] of STOPS)grad.addColorStop((temp+35)/80,color);
 ctx.fillStyle=grad;ctx.fillRect(start,barY,end-start,height);
 ctx.strokeStyle="#536477";ctx.lineWidth=1;ctx.strokeRect(start,barY,end-start,height);
 ctx.fillStyle="#25394b";ctx.font="bold 19px system-ui";
 ctx.fillText("Temperaturmaximum (°C)",start,989);
 ctx.font="17px system-ui";ctx.textAlign="center";
 for(const t of [-30,-20,-10,0,10,20,30,40]){
  const x=start+(t+35)/80*(end-start);
  ctx.fillText(String(t)+"°",x,1044);
 }
 ctx.textAlign="left";
}


/* Presentation-only overrides, with original DWD TX retained unchanged. */
function hex(c,defaultColor){return typeof c==="string"&&/^#[0-9a-f]{6}$/i.test(c)?c.toLowerCase():defaultColor}
function contrast(hexColor){
 const a=[1,3,5].map(i=>{const v=parseInt(hexColor.slice(i,i+2),16)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});
 return .2126*a[0]+.7152*a[1]+.0722*a[2]<.19?"#ffffff":"#172d41";
}
function boxColors(key){
 const own=state.prefs.styles[key]||{},fill=hex(own.fill,hex(state.prefs.globalFill,"#ffffff"));
 return {fill,text:hex(own.text,contrast(fill)),border:hex(own.border,"#1e3444")};
}
function manualValue(key,date){
 const val=state.prefs.values[date]?.[key];
 return typeof val==="number"&&Number.isFinite(val)&&val>=-55&&val<=55?val:null;
}
function shownValue(entry,date){
 const manual=manualValue(entry.key,date);
 return manual===null?{value:entry.tmax_c,manual:false}:{value:manual,manual:true};
}
function selectedEntry(){
 const day=state.data?.days?.[state.index];
 return day&&state.selectedKey?objectsForDay(day).find(s=>s.key===state.selectedKey):null;
}
function openBoxEditor(key){
 const day=state.data?.days?.[state.index];if(!day)return;
 const s=objectsForDay(day).find(e=>e.key===key);if(!s)return;
 state.selectedKey=key;
 $("tmaxBoxEditor").hidden=false;
 $("tmaxBoxTitle").textContent="Kästchen bearbeiten: "+s.city;
 const original=Number.isFinite(s.tmax_c)?s.tmax_c.toLocaleString("de-DE",{maximumFractionDigits:1})+" °C":"kein MOSMIX-TX";
 $("tmaxOriginal").textContent="DWD MOSMIX (Original): "+original+" · "+(s.station_name||"kein Stationsname")+" · "+dateLabel(day.date);
 const manual=manualValue(key,day.date);
 $("tmaxValueOverride").value=manual===null?"":String(manual);
 const c=boxColors(key);
 $("tmaxBoxFill").value=c.fill;$("tmaxBoxText").value=c.text;$("tmaxBoxBorder").value=c.border;
 renderEditorList();
}
function closeBoxEditor(){
 state.selectedKey=null;$("tmaxBoxEditor").hidden=true;renderEditorList();
}
function applyBoxEdits(){
 const day=state.data?.days?.[state.index],entry=selectedEntry();if(!day||!entry)return;
 const raw=$("tmaxValueOverride").value.trim().replace(",",".");
 if(raw!==""){
  const value=Number(raw);
  if(!Number.isFinite(value)||value< -55||value>55){
   note("Temperatur muss zwischen −55 und +55 °C liegen.");return;
  }
  state.prefs.values[day.date]??={};
  state.prefs.values[day.date][entry.key]=Math.round(value*10)/10;
 }else if(state.prefs.values[day.date]){
  delete state.prefs.values[day.date][entry.key];
  if(!Object.keys(state.prefs.values[day.date]).length)delete state.prefs.values[day.date];
 }
 state.prefs.styles[entry.key]={
  fill:hex($("tmaxBoxFill").value,"#ffffff"),
  text:hex($("tmaxBoxText").value,"#172d41"),
  border:hex($("tmaxBoxBorder").value,"#1e3444")
 };
 persist();render();openBoxEditor(entry.key);
 note("Anzeige geändert. MOSMIX-Original bleibt erhalten; * kennzeichnet manuelle Werte.");
}
function resetBoxValue(){
 const day=state.data?.days?.[state.index],key=state.selectedKey;if(!day||!key)return;
 if(state.prefs.values[day.date]){
  delete state.prefs.values[day.date][key];
  if(!Object.keys(state.prefs.values[day.date]).length)delete state.prefs.values[day.date];
 }
 persist();render();openBoxEditor(key);note("MOSMIX-Originalwert wiederhergestellt.");
}
function resetBoxColor(){
 const key=state.selectedKey;if(!key)return;
 delete state.prefs.styles[key];persist();render();openBoxEditor(key);
 note("Individuelle Farben zurückgesetzt.");
}

const EDIT_STORAGE="climate-europa-tmax-editor-v1";
function restorePrefs(){
 try{
  const parsed=JSON.parse(localStorage.getItem(EDIT_STORAGE)||"{}");
  return {
   hidden:Array.isArray(parsed.hidden)?parsed.hidden.filter(x=>typeof x==="string").slice(0,350):[],
   custom:Array.isArray(parsed.custom)?parsed.custom.filter(x=>
     typeof x.key==="string"&&typeof x.stationId==="string"&&
     Number.isFinite(x.lon)&&Number.isFinite(x.lat)&&typeof x.name==="string").slice(0,160):[],
   positions:parsed.positions&&typeof parsed.positions==="object"?parsed.positions:{},
   styles:parsed.styles&&typeof parsed.styles==="object"?parsed.styles:{},
   values:parsed.values&&typeof parsed.values==="object"?parsed.values:{},
   globalFill:hex(parsed.globalFill,"#ffffff")
  };
 }catch(_){return {hidden:[],custom:[],positions:{},styles:{},values:{},globalFill:"#ffffff"}}
}
function persist(){
 try{localStorage.setItem(EDIT_STORAGE,JSON.stringify(state.prefs));}
 catch(err){$("tmaxEditNote").textContent="Lokales Speichern nicht möglich: "+err.message;}
}
function norm(text){
 return String(text||"").toLocaleLowerCase("de-DE").normalize("NFKD")
   .replace(/[\u0300-\u036f]/g,"").replace(/ß/g,"ss").replace(/[^a-z0-9]+/g,"");
}
function regionAt(x,y){
 return [...INSETS,MAIN].find(region=>x>=region.x&&x<=region.x+region.w&&
   y>=region.y&&y<=region.y+region.h)||null;
}
function lonlat(x,y,region){
 return [region.west+(x-region.x)/region.w*(region.east-region.west),
         region.north-(y-region.y)/region.h*(region.north-region.south)];
}
function geoDistance(lon1,lat1,lon2,lat2){
 const rad=Math.PI/180,dLat=(lat2-lat1)*rad,dLon=(lon2-lon1)*rad;
 const a=Math.sin(dLat/2)**2+Math.cos(lat1*rad)*Math.cos(lat2*rad)*Math.sin(dLon/2)**2;
 return 12742*Math.asin(Math.min(1,Math.sqrt(a)));
}
function availableValue(station,dayIndex){return station?.tx?.[dayIndex]??null}
function stationById(id){return state.catalog.find(s=>s.id===id)||null}
function objectsForDay(day){
 const keys=new Set(),objects=[];
 for(const item of day.stations){
  const key="base:"+item.city;keys.add(key);
  objects.push({...item,key});
 }
 for(const custom of state.prefs.custom){
  if(keys.has(custom.key))continue;
  const station=stationById(custom.stationId);
  if(!station)continue;
  const temp=availableValue(station,state.index);
  objects.push({key:custom.key,city:custom.name,lon:custom.lon,lat:custom.lat,
   station_id:station.id,station_name:station.name,station_lat:station.lat,
   station_lon:station.lon,tmax_c:temp,
   distance_km:Math.round(geoDistance(custom.lon,custom.lat,station.lon,station.lat)*10)/10,
   is_custom:true});
  keys.add(custom.key);
 }
 return objects;
}
function drawCoords(s){
 const moved=state.prefs.positions[s.key];
 if(Array.isArray(moved)&&moved.length===2&&
    Number.isFinite(moved[0])&&Number.isFinite(moved[1])){
  const reg=regionForPlace(s);
  if(isInRegion(moved[0],moved[1],reg))return [moved[0],moved[1]];
 }
 return [s.lon,s.lat];
}
function fullName(s){return s.city+(s.station_name?" · MOS: "+s.station_name:" · kein MOS-TX")}
function note(text){$("tmaxEditNote").textContent=text}
function toCanvas(event){
 const bound=canvas.getBoundingClientRect();
 return [(event.clientX-bound.left)*canvas.width/bound.width,
         (event.clientY-bound.top)*canvas.height/bound.height];
}
function updateMode(mode){
 state.editMode=state.editMode===mode?"off":mode;
 $("tmaxPin").setAttribute("aria-pressed",String(state.editMode==="pin"));
 $("tmaxMove").setAttribute("aria-pressed",String(state.editMode==="move"));
 $("tmaxStage").classList.toggle("editing",state.editMode!=="off");
 if(state.editMode==="pin")note("Klicke auf den exakten Kartenpunkt. Der nächstgelegene reale MOSMIX-Wert (maximal 100 km) wird verwendet.");
 else if(state.editMode==="move")note("Klicke auf ein Temperaturkästchen und ziehe es an die neue Position. Die MOS-Station und ihre Werte bleiben unverändert.");
 else note("Bearbeitungsmodus beendet.");
}
function createCustom(station,lon,lat,label){
 // A searched MOS station must be in a displayed map or island region.
 const map=[...INSETS,MAIN].find(r=>isInRegion(lon,lat,r));
 if(!map){note("Dieser Punkt liegt außerhalb der dargestellten Kartenregionen.");return false}
 const name=String(label||station.name||station.id).trim().slice(0,35);
 if(!name)return false;
 const id="custom:"+Date.now()+":"+Math.random().toString(36).slice(2,9);
 state.prefs.custom.push({key:id,name,lon,lat,stationId:station.id});
 persist();render();renderEditorList();
 note(name+" hinzugefügt · Original-MOS-Station "+station.name+
      " · "+geoDistance(lon,lat,station.lon,station.lat).toFixed(1)+" km.");
 return true;
}
function searchCandidates(search){
 const needle=norm(search);
 if(needle.length<2)return [];
 return state.catalog.filter(s=>norm(s.name).includes(needle)||
   norm(s.id).includes(needle))
   .sort((a,b)=>{
    const a0=norm(a.name).startsWith(needle)?0:1,b0=norm(b.name).startsWith(needle)?0:1;
    return a0-b0||a.name.localeCompare(b.name,"de");
   }).slice(0,9);
}
function chooseStation(station){
 state.selectedSearch=station;
 $("tmaxFind").value=station.name;
 drawMatches([]);
 $("tmaxAdd").disabled=false;
 note("Ausgewählte echte MOSMIX-Station "+station.name+" ("+station.id+") – „Ort hinzufügen“ klicken.");
}
function drawMatches(items){
 const el=$("tmaxMatches");el.replaceChildren();
 for(const station of items){
  const b=document.createElement("button");b.type="button";
  b.textContent=station.name+" · "+station.id;
  b.title="Breite "+station.lon+"°, Länge "+station.lat+"°";
  b.addEventListener("click",()=>chooseStation(station));
  el.appendChild(b);
 }
}
function renderEditorList(){
 const root=$("tmaxStationList");root.replaceChildren();
 const day=state.data?.days?.[state.index];
 if(!day)return;
 for(const station of objectsForDay(day)){
  const row=document.createElement("div");
  row.className="tmax-station-row";
  const check=document.createElement("input");check.type="checkbox";
  check.checked=!state.prefs.hidden.includes(station.key);
  check.title="Temperaturwert sichtbar";
  check.setAttribute("aria-label",station.city+" anzeigen");
  check.addEventListener("change",()=>{
   const hidden=new Set(state.prefs.hidden);
   if(check.checked)hidden.delete(station.key);else hidden.add(station.key);
   state.prefs.hidden=[...hidden];persist();render();
  });
  const name=document.createElement("span");name.className="station-name";
  name.textContent=station.city;name.title=fullName(station);
  const move=document.createElement("button");move.type="button";move.textContent="⌖";
  move.title=station.city+" durch Klick auf einen Kartenpunkt platzieren";
  move.addEventListener("click",()=>{
    state.pointTarget=station.key;updateMode("off");note("Jetzt auf die gewünschte Kartenposition für "+station.city+" klicken.");
    $("tmaxStage").classList.add("editing");
  });
  const edit=document.createElement("button");edit.type="button";edit.textContent="✎";
  edit.title=station.city+" · Temperaturwert und Kästchenfarben bearbeiten";
  edit.setAttribute("aria-label",station.city+" bearbeiten");
  if(station.key===state.selectedKey)edit.className="edit-selected";
  edit.addEventListener("click",()=>{
   if(state.prefs.hidden.includes(station.key)){
    state.prefs.hidden=state.prefs.hidden.filter(k=>k!==station.key);persist();render();
   }
   openBoxEditor(station.key);
  });
  row.append(check,name,edit,move);
  if(station.is_custom){
   const del=document.createElement("button");del.type="button";del.textContent="×";
   del.title="Zusätzliche Station entfernen";
   del.addEventListener("click",()=>{
    state.prefs.custom=state.prefs.custom.filter(c=>c.key!==station.key);
    state.prefs.hidden=state.prefs.hidden.filter(k=>k!==station.key);
    delete state.prefs.positions[station.key];
    delete state.prefs.styles[station.key];
    for(const date of Object.keys(state.prefs.values)){
     delete state.prefs.values[date][station.key];
     if(!Object.keys(state.prefs.values[date]).length)delete state.prefs.values[date];
    }
    if(state.selectedKey===station.key)closeBoxEditor();
    persist();render();renderEditorList();
   });
   row.appendChild(del);
  }
  root.appendChild(row);
 }
}
function nearestStation(lon,lat){
 let best=null,distance=Infinity;
 for(const station of state.catalog){
  if(!station.tx.some(Number.isFinite))continue;
  const d=geoDistance(lon,lat,station.lon,station.lat);
  if(d<distance){best=station;distance=d;}
 }
 return best&&distance<=100?{station:best,distance}:null;
}
function setLabelPosition(key,lon,lat,region){
 // Disallow repositioning to a different geographic map/inset.
 const day=state.data?.days?.[state.index];
 const entry=day?objectsForDay(day).find(p=>p.key===key):null;
 if(!entry)return false;
 if(region!==regionForPlace(entry)||!isInRegion(lon,lat,region)){
  note("Für diese Markierung bitte im gleichen Kartenausschnitt bleiben.");
  return false;
 }
 state.prefs.positions[key]=[+lon.toFixed(5),+lat.toFixed(5)];
 persist();render();
 return true;
}
function mapTap(x,y){
 const region=regionAt(x,y);
 if(!region){note("Bitte auf einen gültigen Bereich der Europa- oder Inselkarte klicken.");return}
 const [lon,lat]=lonlat(x,y,region);
 if(state.pointTarget){
  const target=state.pointTarget;state.pointTarget=null;
  if(setLabelPosition(target,lon,lat,region))
   note("Punkt neu gesetzt; die MOSMIX-Datenquelle des Orts bleibt unverändert.");
  $("tmaxStage").classList.toggle("editing",state.editMode!=="off");
  return;
 }
 if(state.editMode!=="pin")return;
 const nearest=nearestStation(lon,lat);
 if(!nearest){note("In höchstens 100 km Entfernung liegt keine MOSMIX-Station mit TX-Werten. Kein Wert eingefügt.");return}
 const label=$("tmaxPinLabel").value.trim()||nearest.station.name;
 if(createCustom(nearest.station,lon,lat,label))note(
  "Punkt "+label+" bei "+lat.toFixed(3)+"° N / "+lon.toFixed(3)+
  "° O gesetzt · MOS: "+nearest.station.name+" · Abstand "+
  nearest.distance.toFixed(1)+" km. (Wert der Station, keine Interpolation)");
}
function pointerDown(event){
 if(!state.editorOpen||!state.data)return;
 const [x,y]=toCanvas(event);
 if(state.pointTarget){mapTap(x,y);return}
 if(state.editMode==="move"){
  const hit=[...state.hits].reverse().find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);
  if(hit){
   state.drag={key:hit.key,region:hit.region,pointerId:event.pointerId};
   canvas.setPointerCapture(event.pointerId);
   event.preventDefault();
   note(hit.city+" verschieben – Original-MOS-Prognose bleibt erhalten.");
  }
 }else if(state.editMode==="pin"){mapTap(x,y)}
 else {
  const hit=[...state.hits].reverse().find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);
  if(hit){openBoxEditor(hit.key);note("Kästchen "+hit.city+" ausgewählt.");}
 }
}
function pointerMove(event){
 if(!state.drag||state.drag.pointerId!==event.pointerId)return;
 const [x,y]=toCanvas(event),reg=state.drag.region;
 const lon=reg.west+(x-reg.x)/reg.w*(reg.east-reg.west);
 const lat=reg.north-(y-reg.y)/reg.h*(reg.north-reg.south);
 if(isInRegion(lon,lat,reg))setLabelPosition(state.drag.key,lon,lat,reg);
 event.preventDefault();
}
function pointerUp(event){
 if(!state.drag||state.drag.pointerId!==event.pointerId)return;
 state.drag=null;
 try{canvas.releasePointerCapture(event.pointerId)}catch(_){}
 persist();note("Position gespeichert. Auf allen fünf Tageskarten bleibt derselbe Ort an dieser Stelle.");
}
function initEditor(){
 state.prefs=restorePrefs();
 $("tmaxEditorToggle").addEventListener("click",()=>{
  state.editorOpen=!state.editorOpen;
  $("tmaxEditor").hidden=!state.editorOpen;
  $("tmaxEditorToggle").setAttribute("aria-expanded",String(state.editorOpen));
  if(!state.editorOpen){
   state.editMode="off";state.pointTarget=null;$("tmaxStage").classList.remove("editing");
   $("tmaxPin").setAttribute("aria-pressed","false");$("tmaxMove").setAttribute("aria-pressed","false");
  }
  renderEditorList();
 });
 $("tmaxFind").addEventListener("input",()=>{
  state.selectedSearch=null;
  $("tmaxAdd").disabled=true;
  drawMatches(searchCandidates($("tmaxFind").value));
 });
 $("tmaxAdd").addEventListener("click",()=>{
  const station=state.selectedSearch||searchCandidates($("tmaxFind").value)[0];
  if(station)createCustom(station,station.lon,station.lat,
    $("tmaxPinLabel").value.trim()||station.name);
 });
 $("tmaxPin").addEventListener("click",()=>{state.pointTarget=null;updateMode("pin")});
 $("tmaxMove").addEventListener("click",()=>{state.pointTarget=null;updateMode("move")});
 $("tmaxReset").addEventListener("click",()=>{
  if(!confirm("Alle selbst hinzugefügten Orte, ausgeblendeten Kästchen und Positionskorrekturen zurücksetzen?"))return;
  state.prefs={hidden:[],custom:[],positions:{},styles:{},values:{},globalFill:"#ffffff"};
  $("tmaxGlobalFill").value="#ffffff";closeBoxEditor();persist();render();renderEditorList();
  note("Standardansicht wiederhergestellt.");
 });
 $("tmaxGlobalFill").value=state.prefs.globalFill;
 $("tmaxGlobalFill").addEventListener("input",e=>{
  state.prefs.globalFill=hex(e.target.value,"#ffffff");persist();render();
  if(state.selectedKey)openBoxEditor(state.selectedKey);
 });
 $("tmaxGlobalReset").addEventListener("click",()=>{
  state.prefs.globalFill="#ffffff";$("tmaxGlobalFill").value="#ffffff";
  persist();render();if(state.selectedKey)openBoxEditor(state.selectedKey);
 });
 $("tmaxStyleSave").addEventListener("click",applyBoxEdits);
 $("tmaxValueReset").addEventListener("click",resetBoxValue);
 $("tmaxColorReset").addEventListener("click",resetBoxColor);
 $("tmaxStyleClose").addEventListener("click",closeBoxEditor);
 $("tmaxBoxFill").addEventListener("input",event=>{
  $("tmaxBoxText").value=contrast(hex(event.target.value,"#ffffff"));
 });
 canvas.addEventListener("pointerdown",pointerDown);
 canvas.addEventListener("pointermove",pointerMove);
 canvas.addEventListener("pointerup",pointerUp);
 canvas.addEventListener("pointercancel",pointerUp);
}

function boxesTouch(a,b){
 return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
}
function drawTemperatureBox(s,region){
 const [lon,lat]=drawCoords(s);
 if(!isInRegion(lon,lat,region))return null;
 const [cx,cy]=xy(lon,lat,region);
 // The PIN is exact; the rectangle sits above it with no connecting line.
 const w=region===MAIN?68:62,h=state.showNames?52:39;
 const x=Math.round(cx-w/2),y=Math.round(cy-h-8);
 // Keep the box inside its own main map / island inset, without displacing
 // its geographical point. Out-of-bounds editing is therefore not accepted.
 if(x<region.x+1||x+w>region.x+region.w-1||y<region.y+1)return null;
 ctx.fillStyle="#ffffff";ctx.fillRect(x,y,w,h);
 ctx.strokeStyle="#1e3444";ctx.lineWidth=2;ctx.strokeRect(x+.5,y+.5,w-1,h-1);
 ctx.fillStyle="#172d41";ctx.textAlign="center";
 if(state.showNames){
  ctx.font=region===MAIN?"600 13px system-ui":"600 12px system-ui";
  ctx.fillText(s.city.length>11?s.city.slice(0,11):s.city,cx,y+18,w-4);
 }
 ctx.font="bold 27px system-ui";
 ctx.fillText(Number.isFinite(s.tmax_c)?String(Math.round(s.tmax_c))+"°":"–",
              cx,y+(state.showNames?44:29));
 ctx.fillStyle=s.is_custom?"#ec8a24":"#173a57";
 ctx.beginPath();ctx.arc(cx,cy,5,0,Math.PI*2);ctx.fill();
 ctx.strokeStyle="#ffffff";ctx.lineWidth=1.5;ctx.stroke();
 ctx.textAlign="left";
 const hit={x,y,w,h,city:s.city,key:s.key,region};
 state.hits.push(hit);
 return hit;
}
function labels(day){
 state.hits=[];
 const items=objectsForDay(day),used=[];
 for(const s of items){
  if(state.prefs.hidden.includes(s.key))continue;
  const region=regionForPlace(s);
  const [lon,lat]=drawCoords(s);
  if(!isInRegion(lon,lat,region))continue;
  const [cx,cy]=xy(lon,lat,region);
  const rect={x:cx-35,y:cy-(state.showNames?60:47),w:70,h:53};
  if(state.density!=="dense"&&used.some(r=>boxesTouch(rect,r)))continue;
  const hit=drawTemperatureBox(s,region);
  if(hit)used.push(hit);
 }
}
function render(){
 bg();
 const day=state.data?.days?.[state.index];
 if(day){
  const image=state.pictures.get(day.date);
  if(state.showField&&image){
   try{drawIconField(image)}catch(error){console.warn("ICON-Kartenausschnitt:",error)}
  }
 }
 drawCoast();
 ctx.fillStyle="#163047";ctx.textAlign="left";
 ctx.font="bold 48px system-ui";ctx.fillText("Europa · Tageshöchsttemperaturen",64,63);
 if(day){
  ctx.font="bold 27px system-ui";ctx.fillStyle="#18384d";
  ctx.fillText(dateLabel(day.date),1205,64);
  if(state.showPoints)labels(day);
 }else{
  ctx.font="bold 30px system-ui";ctx.fillStyle="#f2f7fb";
  ctx.fillText("Noch keine geprüften MOSMIX-/ICON-EU-Daten veröffentlicht",300,430);
 }
 drawLegend();
 ctx.fillStyle="#44566c";ctx.font="16px system-ui";
 ctx.fillText("DWD · MOSMIX-L TX (12 h) + ICON-EU TMAX_2M · 06–18 UTC · Inselkästchen: MOS",64,1070);
 ctx.textAlign="right";
 ctx.fillText(state.data?"ICON-Lauf "+state.data.icon_cycle+" UTC · MOS "+state.data.mos_issue_utc:"Experimenteller Testbereich",1825,1070);
 ctx.textAlign="left";
}
function setButtons(){
 $("tmaxPrev").disabled=!state.data||state.index===0;
 $("tmaxNext").disabled=!state.data||state.index>=state.data.days.length-1;
 $("tmaxSave").disabled=!state.data||!state.pictures.has(state.data.days[state.index].date);
 const nav=$("tmaxDays");nav.replaceChildren();
 if(!state.data)return;
 for(let i=0;i<state.data.days.length;i++){
  const d=state.data.days[i],b=document.createElement("button");
  b.type="button";b.textContent="Tag "+(i+1)+" · "+d.date.slice(5).split("-").reverse().join(".");
  b.setAttribute("aria-pressed",String(i===state.index));
  b.addEventListener("click",()=>{state.index=i;void selectDay();});
  nav.append(b);
 }
}
function fetchImage(path){
 return new Promise((resolve,reject)=>{
  const image=new Image();
  image.onload=()=>resolve(image);image.onerror=()=>reject(Error("ICON-EU-Tageskarte fehlt"));
  image.src=PREFIX+path+"?v="+encodeURIComponent(state.data.icon_cycle);
 });
}
async function selectDay(){
 setButtons();
 const day=state.data?.days?.[state.index];if(!day){render();return;}
 if(!state.pictures.has(day.date)){
  setStatus("Lade ICON-EU-Tmax vom "+dateLabel(day.date)+" …");
  try{
   const img=await fetchImage(day.icon_png);
   if(img.naturalWidth!==state.data.grid.width||img.naturalHeight!==state.data.grid.height)
    throw Error("ICON-EU-Gitter passt nicht zum veröffentlichten Datensatz");
   state.pictures.set(day.date,img);
  }catch(error){
   setStatus("ICON-EU-Fläche fehlt: "+error.message+"; MOS-Werte bleiben nutzbar.",true);
  }
 }
 setButtons();render();renderEditorList();
 if(state.pictures.has(day.date))
  setStatus("Tag "+(state.index+1)+"/5 · "+dateLabel(day.date)+" · "+
    day.stations.filter(s=>Number.isFinite(s.tmax_c)).length+" MOSMIX-Werte / "+
    day.stations.length+" Vorlagenorte · Fehlwerte als „–“ · ICON-EU-Lauf "+state.data.icon_cycle+" UTC.");
}
async function load(){
 if(state.busy)return;state.busy=true;
 $("tmaxRefresh").disabled=true;
 setStatus("Prüfe aktuelle MOSMIX-/ICON-EU-Tageskarten …");
 try{
  const responses=await Promise.all([
   fetch(PREFIX+"current.json?v="+Date.now(),{cache:"no-store"}),
   fetch(GEO,{cache:"force-cache"}),
   fetch(PREFIX+"stations_catalog.json?v="+Date.now(),{cache:"no-store"})
  ]);
  if(!responses[0].ok)throw Error("Noch kein vollständiger Datenlauf veröffentlicht (HTTP "+responses[0].status+")");
  const data=await responses[0].json();
  if(data.schema!==1||!Array.isArray(data.days)||data.days.length!==5||
     data.daily_window!=="06:00-18:00 UTC"||
     !data.grid||data.grid.width<300||data.grid.height<200||
     !data.days.every(d=>/^\d{4}-\d{2}-\d{2}$/.test(d.date)&&
       /^icon_tmax_\d{4}-\d{2}-\d{2}\.png$/.test(d.icon_png)&&
       d.stations?.length===31&&
       d.stations.every(s=>(s.tmax_c===null||Number.isFinite(s.tmax_c))&&
        Number.isFinite(s.lon)&&Number.isFinite(s.lat))&&
       d.stations.filter(s=>Number.isFinite(s.tmax_c)).length>=15))
   throw Error("Veröffentlichte MOS-/ICON-Daten sind unvollständig");
  if(Date.now()-Date.parse(data.built_utc)>72*3600000)throw Error("Vorhersagedaten älter als 72 Stunden");
  if(responses[1].ok)state.geo=await responses[1].json();
  if(!responses[2].ok)throw Error("MOSMIX-Stationskatalog ist noch nicht veröffentlicht");
  const catalog=await responses[2].json();
  if(catalog.schema!==1||catalog.issue_time!==data.mos_issue_utc||
     catalog.days.join(",")!==data.days.map(d=>d.date).join(",")||
     !Array.isArray(catalog.stations)||catalog.stations.length<1000||
     !catalog.stations.every(s=>typeof s.id==="string"&&
       typeof s.name==="string"&&Number.isFinite(s.lon)&&Number.isFinite(s.lat)&&
       Array.isArray(s.tx)&&s.tx.length===5))
    throw Error("MOSMIX-Stationskatalog passt nicht zum aktuellen Modelllauf");
  state.catalog=catalog.stations;
  state.data=data;state.index=0;state.pictures.clear();await selectDay();
  renderEditorList();
 }catch(error){
  state.data=null;state.pictures.clear();state.index=0;
  setStatus("Experimenteller Datenlauf noch nicht bereit: "+error.message+". Keine Ersatz- oder Beispielwerte.",true);
  setButtons();render();
 }finally{state.busy=false;$("tmaxRefresh").disabled=false;}
}
$("tmaxPrev").addEventListener("click",()=>{if(state.index>0){state.index--;void selectDay();}});
$("tmaxNext").addEventListener("click",()=>{if(state.data&&state.index<4){state.index++;void selectDay();}});
window.addEventListener("keydown",event=>{
 if(event.altKey||event.ctrlKey||event.metaKey||/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName||""))return;
 if(event.key==="ArrowLeft")$("tmaxPrev").click();
 if(event.key==="ArrowRight")$("tmaxNext").click();
});
$("tmaxField").addEventListener("change",e=>{state.showField=e.target.checked;render();});
$("tmaxPoints").addEventListener("change",e=>{state.showPoints=e.target.checked;render();});
$("tmaxNames").addEventListener("change",e=>{state.showNames=e.target.checked;render();});
$("tmaxDensity").addEventListener("change",e=>{state.density=e.target.value;render();});
$("tmaxSave").addEventListener("click",()=>{
 if(!state.data)return;
 const date=state.data.days[state.index].date;
 canvas.toBlob(blob=>{
  if(!blob)return;
  const url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download="Europa_Tmax_MOS_ICON_"+date+".png";
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),5000);
 },"image/png");
});
$("tmaxRefresh").addEventListener("click",()=>void load());
initEditor();setButtons();render();void load();
})();
`;
