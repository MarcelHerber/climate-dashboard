/* Inline browser source is a literal; avoid esbuild function.toString() helper leaks. */
export const CANARIAS_RADAR_CLIENT_SOURCE = String.raw`(function canariasRadarClient(){
"use strict";
const $=id=>document.getElementById(id),canvas=$("radar"),ctx=canvas.getContext("2d",{alpha:false});
const API="/radarlabor/api/canarias/";
const REGIONS={
 all:{w:-19.5,e:-12.2,s:27,n:30.6},
 west:{w:-18.75,e:-16.48,s:27.3,n:29.45},
 central:{w:-17.25,e:-14.85,s:27.5,n:29.4},
 east:{w:-14.9,e:-12.65,s:27.6,n:29.7}
};
const LABELS=[
 ["La Palma",-17.82,28.69],["El Hierro",-18.02,27.74],
 ["La Gomera",-17.25,28.11],["Teneriffa",-16.57,28.26],
 ["Gran Canaria",-15.56,27.99],["Fuerteventura",-14.04,28.48],
 ["Lanzarote",-13.67,29.06]
];
const state={m:null,geo:null,idx:0,cache:new Map(),serial:0,playing:false,timer:0};
const view=()=>REGIONS[$("region").value],entries=()=>state.m?.frames||[];
const px=lon=>(lon-view().w)/(view().e-view().w)*canvas.width;
const py=lat=>(view().n-lat)/(view().n-view().s)*canvas.height;
const date=s=>new Date(s).toLocaleString("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})+" UTC";
const rgb=hex=>[parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)];
function message(msg,bad=false){$("status").textContent=msg;$("status").className="status"+(bad?" error":"")}
function stop(){state.playing=false;clearTimeout(state.timer);$("play").textContent="▶ Animation"}
function basemap(){
 ctx.fillStyle="#d6e8f2";ctx.fillRect(0,0,canvas.width,canvas.height);
 const r=view();
 ctx.strokeStyle="#a4c2d5";ctx.lineWidth=1.2;ctx.setLineDash([3,8]);ctx.beginPath();
 for(let x=-20;x<=-12;x+=1)if(x>r.w&&x<r.e){ctx.moveTo(px(x),0);ctx.lineTo(px(x),canvas.height)}
 for(let y=27;y<31;y+=1)if(y>r.s&&y<r.n){ctx.moveTo(0,py(y));ctx.lineTo(canvas.width,py(y))}
 ctx.stroke();ctx.setLineDash([]);
 if(!state.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 for(const f of state.geo.features||[]){
  const g=f.geometry||{};
  const polygon=g.type==="Polygon"?[g.coordinates]:g.type==="MultiPolygon"?g.coordinates:[];
  for(const poly of polygon){
   ctx.beginPath();
   for(const ring of poly){
    let last=NaN;
    ring.forEach((pt,i)=>{
     const x=px(pt[0]),y=py(pt[1]);
     if(!Number.isFinite(x+y))return;
     if(i===0||Math.abs(last-x)>canvas.width*.4)ctx.moveTo(x,y);
     else ctx.lineTo(x,y);
     last=x;
    });
    ctx.closePath();
   }
   ctx.fillStyle="#eef2ed";ctx.fill("evenodd");
   ctx.strokeStyle="#415c70";ctx.lineWidth=2.0;ctx.stroke();
  }
 }
 ctx.restore();
}
function labels(){
 ctx.save();ctx.font="bold 21px system-ui";ctx.textAlign="center";
 ctx.lineWidth=4.4;ctx.strokeStyle="#fafcfee8";ctx.fillStyle="#1a3953";
 for(const [name,lon,lat] of LABELS){
  const x=px(lon),y=py(lat);
  if(x<-100||x>canvas.width+100||y<-40||y>canvas.height+40)continue;
  // Offset labels below the island center to keep echoes visible.
  ctx.strokeText(name,x,y+28);ctx.fillText(name,x,y+28);
 }
 ctx.restore();
}
function imageToLayer(img){
 const g=state.m.grid;
 if(img.naturalWidth!==g.width||img.naturalHeight!==g.height)throw Error("Radargröße unplausibel");
 const off=document.createElement("canvas");off.width=g.width;off.height=g.height;
 const x=off.getContext("2d",{willReadFrequently:true});x.drawImage(img,0,0);
 const rgba=x.getImageData(0,0,g.width,g.height),d=rgba.data;
 const colors=state.m.palette.colors.map(rgb);
 for(let i=0;i<d.length;i+=4){
  const cls=d[i];
  if(cls===0||cls===255){d[i+3]=0;continue}
  if(cls<1||cls>11)throw Error("Unbekannter AEMET-Radarschwellencode");
  const c=colors[cls-1];
  d[i]=c[0];d[i+1]=c[1];d[i+2]=c[2];d[i+3]=235;
 }
 x.putImageData(rgba,0,0);
 return off;
}
function load(frame){
 const path=frame.image;
 if(state.cache.has(path))return Promise.resolve(state.cache.get(path));
 return new Promise((resolve,reject)=>{
  const img=new Image();
  img.onload=()=>{
   try{
    const layer=imageToLayer(img);
    state.cache.set(path,layer);
    while(state.cache.size>16)state.cache.delete(state.cache.keys().next().value);
    resolve(layer);
   }catch(e){reject(e)}
  };
  img.onerror=()=>reject(Error("AEMET-Radarbild nicht erreichbar: "+path));
  img.src=API+path;
 });
}
function drawLayer(layer){
 const r=view(),g=state.m.grid;
 const sx=(r.w-g.west)/(g.east-g.west)*g.width;
 const sy=(g.north-r.n)/(g.north-g.south)*g.height;
 const sw=(r.e-r.w)/(g.east-g.west)*g.width;
 const sh=(r.n-r.s)/(g.north-g.south)*g.height;
 ctx.imageSmoothingEnabled=false;
 ctx.drawImage(layer,sx,sy,sw,sh,0,0,canvas.width,canvas.height);
}
function header(frame){
 ctx.fillStyle="#17314aE6";ctx.fillRect(0,0,canvas.width,54);
 ctx.fillStyle="#fff";ctx.font="bold 24px system-ui";
 ctx.fillText("AEMET · Kanaren · "+date(frame.utc),15,36);
 ctx.font="17px system-ui";ctx.textAlign="right";
 ctx.fillText("PPI · 0,5° · dBZ",canvas.width-18,35);ctx.textAlign="left";
}
async function render(){
 if(!state.m)return;
 const serial=++state.serial,frame=entries()[state.idx];
 $("timeline").value=state.idx;
 $("time").textContent=date(frame.utc);
 $("stamp").textContent="AEMET Kanaren · "+date(frame.utc);
 try{
  const layer=await load(frame);
  if(serial!==state.serial)return;
  basemap();
  if($("layer").value==="rain")drawLayer(layer);
  labels();header(frame);
  const age=Math.round((Date.now()-Date.parse(entries().at(-1).utc))/60000);
  message("Echte AEMET-Messung aus georeferenziertem GeoTIFF · "+entries().length+
   " Zeitpunkte · letzter Zeitpunkt "+age+" Minuten zurück"+
   (age>50?" · Achtung: Daten möglicherweise verspätet":"")+".");
 }catch(e){
  if(serial!==state.serial)return;
  stop();basemap();labels();message("Radarmessung nicht darstellbar: "+e.message,true);
 }
}
function makeLegend(){
 const box=$("legend");box.replaceChildren();
 state.m.palette.labels.forEach((label,i)=>{
  const item=document.createElement("div"),sw=document.createElement("div"),value=document.createElement("span");
  item.className="swatch";sw.className="color";sw.style.background=state.m.palette.colors[i];
  value.textContent=label;item.append(sw,value);box.append(item);
 });
 const u=document.createElement("strong");u.textContent="dBZ";u.style.fontSize="11px";box.append(u);
}
async function boot(){
 stop();state.serial++;state.cache.clear();message("Prüfe aktuelle AEMET-Geodaten …");
 try{
  const r=await fetch(API+"current.json",{cache:"no-store"});
  if(!r.ok)throw Error(r.status===404?"Erster geprüfter Kanaren-Datenlauf noch ausstehend":"HTTP "+r.status);
  const m=await r.json();
  if(m.schema!==1||m.unit!=="dBZ"||!m.grid||m.grid.width!==1460||
     !Array.isArray(m.frames)||m.frames.length<1||
     !Array.isArray(m.palette?.colors)||m.palette.colors.length!==11||
     !m.frames.every(f=>typeof f.utc==="string"&&/^frames\/\d{12}\.png$/.test(f.image))){
    throw Error("Unvollständiger oder ungültiger AEMET-Datensatz");
  }
  state.m=m;state.idx=entries().length-1;makeLegend();
  $("model").textContent="AEMET LPA / Com-Canarias · 10 min";
  for(const id of ["prev","next","play","timeline","png"])$(id).disabled=false;
  $("timeline").max=Math.max(0,entries().length-1);render();
 }catch(e){
  state.m=null;
  for(const id of ["prev","next","play","timeline","png"])$(id).disabled=true;
  basemap();labels();
  message(e.message+" · keine künstlichen Radarbilder.",true);
 }
}
async function advance(){
 if(!state.playing)return;
 state.idx=(state.idx+1)%entries().length;
 await render();
 if(state.playing)state.timer=setTimeout(advance,Math.round(850/Number($("speed").value)));
}
$("prev").addEventListener("click",()=>{stop();state.idx=Math.max(0,state.idx-1);render()});
$("next").addEventListener("click",()=>{stop();state.idx=Math.min(entries().length-1,state.idx+1);render()});
$("timeline").addEventListener("input",()=>{stop();state.idx=Number($("timeline").value);render()});
$("region").addEventListener("change",()=>{stop();render()});
$("layer").addEventListener("change",render);
$("refresh").addEventListener("click",boot);
$("play").addEventListener("click",()=>{
 if(!state.m)return;
 if(state.playing){stop();return}
 state.playing=true;$("play").textContent="❚❚ Pause";
 state.timer=setTimeout(advance,Math.round(850/Number($("speed").value)));
});
$("png").addEventListener("click",()=>{
 if(!state.m)return;
 canvas.toBlob(blob=>{
  if(!blob)return;
  const link=document.createElement("a"),url=URL.createObjectURL(blob);
  link.href=url;link.download="aemet-kanaren-"+entries()[state.idx].utc.replace(/[-:]/g,"").replace("T","_")+".png";
  document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
 },"image/png");
});
fetch("/radarlabor/api/borders_europe.geojson").then(r=>{if(!r.ok)throw Error("Natural Earth");return r.json()})
 .then(data=>{state.geo=data;if(state.m)render();else{basemap();labels()}})
 .catch(()=>{});
basemap();labels();boot();
})();`;
