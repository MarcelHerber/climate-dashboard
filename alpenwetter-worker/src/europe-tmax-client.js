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
 showPoints:true,showNames:true,density:"medium",busy:false};
function xy(lon,lat,region=MAIN){return [
 region.x+(lon-region.west)/(region.east-region.west)*region.w,
 region.y+(region.north-lat)/(region.north-region.south)*region.h
];}
function rectPath(region){
 ctx.beginPath();ctx.rect(region.x,region.y,region.w,region.h);ctx.clip();
}
function regionForCity(name){return INSETS.find(r=>r.city===name)||MAIN;}
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
function boxesTouch(a,b){
 return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
}
function drawTemperatureBox(s,region){
 if(!Number.isFinite(s.tmax_c))return null;
 if(!isInRegion(s.lon,s.lat,region))return null;
 const [cx,cy]=xy(s.lon,s.lat,region);
 // Exactly at the city coordinates: NO leader lines and NO displaced boxes.
 const w=region===MAIN?65:62,h=state.showNames?51:41;
 const x=Math.round(cx-w/2),y=Math.round(cy-h/2);
 ctx.fillStyle="#ffffff";ctx.fillRect(x,y,w,h);
 ctx.strokeStyle="#1e3444";ctx.lineWidth=2;ctx.strokeRect(x+.5,y+.5,w-1,h-1);
 ctx.fillStyle="#172d41";ctx.textAlign="center";
 if(state.showNames){
  ctx.font=region===MAIN?"600 13px system-ui":"600 12px system-ui";
  const short=s.city.length>11?s.city.slice(0,11):s.city;
  ctx.fillText(short,cx,y+17,w-4);
 }
 ctx.font="bold 27px system-ui";
 ctx.fillText(String(Math.round(s.tmax_c))+"°",cx,y+(state.showNames?43:30));
 ctx.textAlign="left";
 return {x,y,w,h,city:s.city};
}
function labels(day){
 const all=day.stations||[],used=[];
 for(const s of all){
  const region=regionForCity(s.city);
  if(!isInRegion(s.lon,s.lat,region))continue;
  const [cx,cy]=xy(s.lon,s.lat,region);
  const size={x:cx-33,y:cy-26,w:66,h:52};
  if(state.density!=="dense"&&used.some(r=>boxesTouch(size,r)))continue;
  // Density only hides collided labels; it never displaces values from cities.
  const added=drawTemperatureBox(s,region);
  if(added)used.push(size);
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
 setButtons();render();
 if(state.pictures.has(day.date))
  setStatus("Tag "+(state.index+1)+"/5 · "+dateLabel(day.date)+" · "+day.stations.length+
   " echte MOSMIX-Stationen · ICON-EU-Lauf "+state.data.icon_cycle+" UTC.");
}
async function load(){
 if(state.busy)return;state.busy=true;
 $("tmaxRefresh").disabled=true;
 setStatus("Prüfe aktuelle MOSMIX-/ICON-EU-Tageskarten …");
 try{
  const responses=await Promise.all([
   fetch(PREFIX+"current.json?v="+Date.now(),{cache:"no-store"}),
   fetch(GEO,{cache:"force-cache"})
  ]);
  if(!responses[0].ok)throw Error("Noch kein vollständiger Datenlauf veröffentlicht (HTTP "+responses[0].status+")");
  const data=await responses[0].json();
  if(data.schema!==1||!Array.isArray(data.days)||data.days.length!==5||
     data.daily_window!=="06:00-18:00 UTC"||
     !data.grid||data.grid.width<300||data.grid.height<200||
     !data.days.every(d=>/^\d{4}-\d{2}-\d{2}$/.test(d.date)&&
       /^icon_tmax_\d{4}-\d{2}-\d{2}\.png$/.test(d.icon_png)&&
       d.stations?.length>=15&&d.stations.every(s=>Number.isFinite(s.tmax_c)&&
        Number.isFinite(s.lon)&&Number.isFinite(s.lat))))
   throw Error("Veröffentlichte MOS-/ICON-Daten sind unvollständig");
  if(Date.now()-Date.parse(data.built_utc)>72*3600000)throw Error("Vorhersagedaten älter als 72 Stunden");
  if(responses[1].ok)state.geo=await responses[1].json();
  state.data=data;state.index=0;state.pictures.clear();await selectDay();
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
setButtons();render();void load();
})();
`;
