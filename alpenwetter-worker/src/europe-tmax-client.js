export const TMAX_JS = String.raw\`
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const canvas=$("tmaxCanvas"),ctx=canvas.getContext("2d",{alpha:false});
const PREFIX="/wolkenlabor/data/europa-tmax/";
const GEO="/wolkenlabor/data/geo.json";
const BOUNDS={west:-29,east:47,south:27,north:73};
const STOPS=[
 [-35,"#1b2572"],[-20,"#2352ad"],[-10,"#319ad2"],[0,"#6ecad2"],
 [7,"#53a976"],[13,"#a7c567"],[18,"#f6d762"],[23,"#f9984e"],
 [28,"#eb5f4b"],[34,"#ce3e5f"],[45,"#772b5e"]
];
const state={data:null,geo:null,index:0,pictures:new Map(),showField:true,
 showPoints:true,showNames:true,density:"medium",busy:false};
const X0=94,Y0=105,MAP_W=1732,MAP_H=838;

function xy(lon,lat){return [
 X0+(lon-BOUNDS.west)/(BOUNDS.east-BOUNDS.west)*MAP_W,
 Y0+(BOUNDS.north-lat)/(BOUNDS.north-BOUNDS.south)*MAP_H
];}
function dateLabel(iso){
 const d=new Date(iso+"T12:00:00Z");
 return new Intl.DateTimeFormat("de-DE",{weekday:"short",day:"2-digit",month:"long",year:"numeric",timeZone:"UTC"}).format(d);
}
function setStatus(msg,error=false){
 const el=$("tmaxStatus");el.textContent=msg;el.className="status"+(error?" error":"");
}
function bg(){
 const fill=ctx.createLinearGradient(0,Y0,0,Y0+MAP_H);
 fill.addColorStop(0,"#547b9b");fill.addColorStop(1,"#6e99a7");
 ctx.fillStyle="#f5f8fb";ctx.fillRect(0,0,canvas.width,canvas.height);
 ctx.fillStyle=fill;ctx.fillRect(X0,Y0,MAP_W,MAP_H);
}
function drawCoast(){
 if(!state.geo?.countries)return;
 ctx.save();ctx.beginPath();ctx.rect(X0,Y0,MAP_W,MAP_H);ctx.clip();
 for(const country of state.geo.countries){
  for(const poly of country.p||[]){
   ctx.beginPath();
   for(const ring of poly){
    let valid=false;
    for(const p of ring){
     if(!Array.isArray(p)||p.length<2)continue;
     const [x,y]=xy(p[0],p[1]);
     if(!valid){ctx.moveTo(x,y);valid=true}else ctx.lineTo(x,y);
    }
    if(valid)ctx.closePath();
   }
   ctx.fillStyle="rgba(250,248,236,.045)";
   try{ctx.fill("evenodd")}catch(_){ctx.fill()}
   ctx.strokeStyle="rgba(17,43,56,.72)";
   ctx.lineWidth=1.45;ctx.stroke();
  }
 }
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
function within(a,b){return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;}
function labels(day){
 const points=day.stations||[];
 const placed=[],used=[];
 const pad=state.density==="sparse"?125:state.density==="medium"?55:9;
 // Priority order from the editorial list, not automatically ranked by value.
 for(const s of points){
  if(!Number.isFinite(s.tmax_c))continue;
  const [ax,ay]=xy(s.lon,s.lat);
  if(ax<X0+24||ax>X0+MAP_W-24||ay<Y0+32||ay>Y0+MAP_H-25)continue;
  if(state.density!=="dense"&&used.some(p=>Math.hypot(p[0]-ax,p[1]-ay)<pad))continue;
  const w=state.showNames?80:60,h=state.showNames?67:48;
  const variants=[[0,-56],[60,-37],[-60,-37],[0,28],[70,15],[-70,15],
                  [105,-60],[-105,-60],[110,58],[-110,58]];
  let position=null;
  for(const [dx,dy] of variants){
   const rect={x:ax-w/2+dx,y:ay-h/2+dy,w,h};
   if(rect.x<X0+4||rect.y<Y0+4||rect.x+w>X0+MAP_W-4||rect.y+h>Y0+MAP_H-4)continue;
   if(placed.some(a=>within({x:rect.x-4,y:rect.y-4,w:w+8,h:h+8},a)))continue;
   position=rect;break;
  }
  if(!position)continue;
  placed.push(position);used.push([ax,ay]);
  ctx.strokeStyle="rgba(7,25,42,.7)";
  ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(ax,ay);
  ctx.lineTo(position.x+w/2,position.y+h/2);ctx.stroke();
  ctx.fillStyle="#fbfcfe";ctx.fillRect(position.x,position.y,w,h);
  ctx.strokeStyle="#273947";ctx.lineWidth=2;ctx.strokeRect(position.x,position.y,w,h);
  if(state.showNames){
   ctx.fillStyle="#172f43";ctx.textAlign="center";
   ctx.font="600 15px system-ui";
   let name=s.city;
   while(name.length>12)name=name.slice(0,-1);
   ctx.fillText(name,position.x+w/2,position.y+19,w-6);
  }
  ctx.font="bold 29px system-ui";ctx.fillStyle="#101e2e";
  ctx.textAlign="center";
  ctx.fillText(String(Math.round(s.tmax_c))+"°",position.x+w/2,
    position.y+(state.showNames?52:33));
  ctx.textAlign="left";
 }
}
function render(){
 bg();
 const day=state.data?.days?.[state.index];
 if(day){
  const image=state.pictures.get(day.date);
  if(state.showField&&image){
   ctx.save();ctx.beginPath();ctx.rect(X0,Y0,MAP_W,MAP_H);ctx.clip();
   ctx.drawImage(image,X0,Y0,MAP_W,MAP_H);ctx.restore();
  }
 }
 drawCoast();
 ctx.fillStyle="#163047";ctx.textAlign="left";
 ctx.font="bold 48px system-ui";ctx.fillText("Europa · Tageshöchsttemperaturen",94,63);
 if(day){
  ctx.font="bold 27px system-ui";ctx.fillStyle="#18384d";
  ctx.fillText(dateLabel(day.date),1170,64);
  if(state.showPoints)labels(day);
 }else{
  ctx.font="bold 30px system-ui";ctx.fillStyle="#f2f7fb";
  ctx.fillText("Noch keine geprüften MOSMIX-/ICON-EU-Daten veröffentlicht",160,430);
 }
 drawLegend();
 ctx.fillStyle="#44566c";ctx.font="16px system-ui";
 ctx.fillText("DWD · MOSMIX-L TX (12 h) + ICON-EU TMAX_2M · 06–18 UTC",94,1070);
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
\`;\n