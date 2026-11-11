/* Browser code stored as untransformed literal; Wrangler cannot inject missing __name. */
export const AZORES_RADAR_CLIENT_SOURCE = String.raw`(function azoresRadarClient(){
"use strict";
const $=id=>document.getElementById(id),canvas=$("radar"),ctx=canvas.getContext("2d",{alpha:false});
const API="/radarlabor/api/azoren/";
const REGIONS={
 all:{w:-32,e:-24,s:36.4,n:40.35},
 west:{w:-31.75,e:-29.6,s:38.7,n:40.3},
 center:{w:-29.25,e:-26.4,s:37.85,n:39.45},
 east:{w:-26.65,e:-24.35,s:36.6,n:38.5}
};
const ISLANDS=[
 ["Corvo",-31.11,39.7],["Flores",-31.2,39.45],
 ["Faial",-28.73,38.58],["Pico",-28.36,38.47],
 ["São Jorge",-28.08,38.65],["Graciosa",-28.05,39.05],
 ["Terceira",-27.22,38.72],["São Miguel",-25.53,37.78],
 ["Santa Maria",-25.14,36.97]
];
const state={m:null,idx:0,geo:null,images:new Map(),serial:0,playing:false,timer:null};
const view=()=>REGIONS[$("region").value];
const merc=lat=>Math.log(Math.tan(Math.PI/4+(lat*Math.PI/180)/2));
const px=lon=>(lon-view().w)/(view().e-view().w)*canvas.width;
const py=lat=>(merc(view().n)-merc(lat))/(merc(view().n)-merc(view().s))*canvas.height;
const when=s=>new Date(s).toLocaleString("de-DE",{timeZone:"UTC",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC";
const frames=()=>state.m?.frames||[];
function status(msg,bad=false){$("status").textContent=msg;$("status").className="status"+(bad?" error":"")}
function stop(){state.playing=false;clearTimeout(state.timer);$("play").textContent="▶ Animation"}
function landPaths(){
 if(!state.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 for(const feature of state.geo.features||[]){
  const g=feature.geometry||{};
  const polygons=g.type==="Polygon"?[g.coordinates]:g.type==="MultiPolygon"?g.coordinates:[];
  for(const polygon of polygons){
   ctx.beginPath();
   for(const ring of polygon||[]){
    let previous=NaN;
    for(let i=0;i<ring.length;i++){
     const point=ring[i],X=px(point[0]),Y=py(point[1]);
     if(!Number.isFinite(X+Y))continue;
     if(i===0||Math.abs(previous-X)>canvas.width*.45)ctx.moveTo(X,Y);else ctx.lineTo(X,Y);
     previous=X;
    }
    ctx.closePath();
   }
   ctx.fillStyle="#edf3ee";ctx.fill("evenodd");
  }
 }
 ctx.restore();
}
function outlines(){
 if(!state.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 ctx.beginPath();
 for(const f of state.geo.features||[]){
  const geom=f.geometry||{};
  const polygons=geom.type==="Polygon"?[geom.coordinates]:geom.type==="MultiPolygon"?geom.coordinates:[];
  for(const poly of polygons)for(const ring of poly||[]){
   let lastX=NaN;
   for(let i=0;i<ring.length;i++){
    const X=px(ring[i][0]),Y=py(ring[i][1]);
    if(!Number.isFinite(X+Y))continue;
    if(i===0||Math.abs(X-lastX)>canvas.width*.45)ctx.moveTo(X,Y);else ctx.lineTo(X,Y);
    lastX=X;
   }
   ctx.closePath();
  }
 }
 ctx.lineWidth=2.3;ctx.strokeStyle="#395468e8";ctx.stroke();ctx.restore();
}
function base(){
 ctx.fillStyle="#d4e8f3";ctx.fillRect(0,0,canvas.width,canvas.height);
 const r=view();
 ctx.save();ctx.lineWidth=1.1;ctx.strokeStyle="#abc8d8";ctx.setLineDash([4,9]);ctx.beginPath();
 for(let lon=-32;lon<=-24;lon+=1)if(lon>r.w&&lon<r.e){ctx.moveTo(px(lon),0);ctx.lineTo(px(lon),canvas.height)}
 for(let lat=36;lat<41;lat+=1)if(lat>r.s&&lat<r.n){ctx.moveTo(0,py(lat));ctx.lineTo(canvas.width,py(lat))}
 ctx.stroke();ctx.restore();
 landPaths();
}
function labels(){
 ctx.save();ctx.font="bold 20px system-ui";ctx.textAlign="center";
 ctx.strokeStyle="#f6fafbdf";ctx.fillStyle="#163c57";ctx.lineWidth=4.5;
 for(const [name,lon,lat] of ISLANDS){
  const X=px(lon),Y=py(lat);
  if(X<25||X>canvas.width-25||Y<20||Y>canvas.height-40)continue;
  ctx.strokeText(name,X,Y+27);ctx.fillText(name,X,Y+27);
 }
 ctx.restore();
}
function overlay(img){
 const bounds=state.m.overlay_bounds;
 const left=px(bounds.west),top=py(bounds.north),width=px(bounds.east)-left,height=py(bounds.south)-top;
 if(!Number.isFinite(left+top+width+height)||width<=0||height<=0)throw Error("Unzulässige geografische IPMA-Grenzen");
 ctx.save();
 ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 ctx.globalAlpha=.83;
 ctx.imageSmoothingEnabled=true;
 ctx.drawImage(img,left,top,width,height);
 ctx.restore();
}
function load(frame){
 if(state.images.has(frame.image))return Promise.resolve(state.images.get(frame.image));
 return new Promise((resolve,reject)=>{
  const img=new Image();
  img.onload=()=>{
   if(img.naturalWidth<50||img.naturalHeight<50){reject(Error("IPMA-Radarbild hat eine ungültige Größe"));return}
   state.images.set(frame.image,img);
   while(state.images.size>16)state.images.delete(state.images.keys().next().value);
   resolve(img);
  };
  img.onerror=()=>reject(Error("Radarbild nicht abrufbar: "+frame.utc));
  img.src=API+frame.image;
 });
}
function title(frame){
 ctx.fillStyle="#102940da";ctx.fillRect(0,0,canvas.width,60);
 ctx.fillStyle="#fff";ctx.font="bold 23px system-ui";
 ctx.fillText("IPMA Azoren · Intensität mm/h · "+when(frame.utc),16,39);
 ctx.font="17px system-ui";ctx.textAlign="right";
 ctx.fillText("© IPMA · Original-Radaroverlay",canvas.width-20,39);
 ctx.textAlign="left";
}
async function render(){
 if(!state.m||!frames().length)return;
 const serial=++state.serial,frame=frames()[state.idx];
 $("timeline").value=state.idx;
 $("time").textContent=when(frame.utc);
 $("stamp").textContent="IPMA Azoren · "+when(frame.utc);
 try{
  const image=await load(frame);
  if(serial!==state.serial)return;
  base();
  if($("showRadar").value==="on")overlay(image);
  outlines();labels();title(frame);
  const delta=Math.round((Date.now()-Date.parse(frames().at(-1).utc))/60000);
  status("Original-IPMA-Radardaten · "+frames().length+" verfügbare Beobachtungen · letzter Zeitstempel "+
   delta+" Minuten zurück"+(delta>60?" · Achtung: Radarverfügbarkeit oder Aktualisierung eingeschränkt":"")+".",
   delta>120);
  const next=frames()[state.idx+1];
  if(next&&!state.images.has(next.image))load(next).catch(()=>{});
 }catch(e){
  if(serial!==state.serial)return;
  stop();base();outlines();labels();
  status("IPMA-Radarbild konnte nicht geladen werden: "+e.message,true);
 }
}
async function boot(){
 stop();++state.serial;state.images.clear();
 status("Aktuelle IPMA-Radarzeitpunkte abrufen …");
 try{
  const response=await fetch(API+"current.json",{cache:"no-store"});
  if(!response.ok)throw Error("IPMA-Datenindex HTTP "+response.status);
  const m=await response.json();
  if(m.schema!==1||m.units!=="mm/h"||!m.overlay_bounds||
     !Array.isArray(m.frames)||!m.frames.length||
     !m.frames.every(f=>typeof f.utc==="string"&&/^frames\/[A-Za-z0-9_./-]{1,150}\.(?:png|gif|jpe?g|webp)$/i.test(f.image)))
      throw Error("Unvollständiger amtlicher IPMA-Datensatz");
  state.m=m;state.idx=frames().length-1;
  $("product").textContent="IPMA · Azoren · Niederschlagsintensität mm/h";
  $("timeline").max=Math.max(0,frames().length-1);
  for(const id of ["prev","next","play","timeline","png"])$(id).disabled=false;
  if(frames().length===1)$("play").disabled=true;
  render();
 }catch(e){
  state.m=null;
  for(const id of ["prev","next","play","timeline","png"])$(id).disabled=true;
  base();outlines();labels();
  status("IPMA-Daten nicht verfügbar: "+e.message+". Keine Ersatz-Radarbilder.",true);
 }
}
async function tick(){
 if(!state.playing)return;
 state.idx=(state.idx+1)%frames().length;
 await render();
 if(state.playing)state.timer=setTimeout(tick,Math.round(800/Number($("speed").value)));
}
$("prev").addEventListener("click",()=>{stop();state.idx=Math.max(0,state.idx-1);render()});
$("next").addEventListener("click",()=>{stop();state.idx=Math.min(frames().length-1,state.idx+1);render()});
$("timeline").addEventListener("input",()=>{stop();state.idx=Number($("timeline").value);render()});
$("region").addEventListener("change",()=>{stop();render()});
$("showRadar").addEventListener("change",render);
$("refresh").addEventListener("click",boot);
$("play").addEventListener("click",()=>{
 if(!state.m||frames().length<2)return;
 if(state.playing){stop();return}
 state.playing=true;$("play").textContent="❚❚ Pause";
 state.timer=setTimeout(tick,Math.round(800/Number($("speed").value)));
});
$("png").addEventListener("click",()=>{
 if(!state.m)return;
 canvas.toBlob(blob=>{
  if(!blob)return;
  const url=URL.createObjectURL(blob),link=document.createElement("a");
  link.href=url;link.download="ipma-azoren-radar-"+frames()[state.idx].utc.replace(/[-:]/g,"").replace("T","_")+".png";
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),3000);
 },"image/png");
});
fetch("/radarlabor/api/borders_europe.geojson").then(response=>{if(!response.ok)throw Error("Natural Earth");return response.json()})
 .then(data=>{state.geo=data;if(state.m)render();else{base();outlines();labels()}})
 .catch(()=>{});
base();labels();boot();
// Only refresh while the user is viewing the most recent frame and not animating.
setInterval(()=>{if(!state.playing&&state.m&&state.idx===frames().length-1)boot();},300000);
})();`;
