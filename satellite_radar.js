/* Optional RainViewer past-radar composite, for personal/non-commercial usage.
 * Reprojects EPSG:3857 XYZ tiles row by row into EUMETSAT WMS EPSG:4326.
 * Rendered only on confirmed still frames; never implies exact radar acquisition UTC. */
(() => {
"use strict";
const $=id=>document.getElementById(id),toggle=$("satShowRadar"),opacity=$("satRadarOpacity");
const status=$("satRadarStatus"),overlay=$("satRadarOverlay"),region=$("satRegion"),source=$("satSource");
if(!toggle||!status||!overlay||!opacity)return;
const AREAS={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
const tx=(lon,z)=>(lon+180)/360*(2**z);
const ty=(lat,z)=>(1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2*(2**z);
const tileCache=new Map();
let metadata=null,lastMeta=0,serial=0,context={time:null,region:"europe",source:"mtgi1"};
function clear(message){overlay.hidden=true;overlay.removeAttribute("src");if(message)status.textContent=message;}
async function manifest(){
 if(metadata&&Date.now()-lastMeta<120000)return metadata;
 const response=await fetch("https://api.rainviewer.com/public/weather-maps.json",{cache:"no-store"});
 if(!response.ok)throw Error("Radar-Metadaten HTTP "+response.status);
 const data=await response.json();
 if(!Array.isArray(data.radar?.past)||!/^https:\/\/[a-z0-9.-]+\.rainviewer\.com$/i.test(data.host))
  throw Error("Unerwartete Radarquelle");
 metadata=data;lastMeta=Date.now();return data;
}
function tile(url){
 if(tileCache.has(url))return tileCache.get(url);
 const promise=new Promise(resolve=>{
  const image=new Image();image.crossOrigin="anonymous";
  const timer=setTimeout(()=>finish(null),5000);
  function finish(img){clearTimeout(timer);image.onload=null;image.onerror=null;resolve(img);}
  image.onload=()=>finish(image.naturalWidth===256?image:null);
  image.onerror=()=>finish(null);
  image.src=url;
 });
 tileCache.set(url,promise);
 while(tileCache.size>64)tileCache.delete(tileCache.keys().next().value);
 return promise;
}
async function renderFrame(frame,meta,area){
 const [west,south,east,north,w,h]=area,width=480,height=Math.round(480*h/w);
 let zoom=6,box;
 while(zoom>=2){
  const x0=Math.floor(tx(west,zoom)),x1=Math.ceil(tx(east,zoom))-1;
  const y0=Math.floor(ty(north,zoom)),y1=Math.ceil(ty(south,zoom))-1;
  box={x0,x1,y0,y1,zoom};
  if((x1-x0+1)*(y1-y0+1)<=18)break;
  zoom--;
 }
 const {x0,x1,y0,y1}=box;
 const tiles=[],links=[];
 for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
  links.push(meta.host+frame.path+"/256/"+zoom+"/"+x+"/"+y+"/2/1_0.png");
  tiles.push({x,y});
 }
 // A bounded pool avoids spamming the shared free tile service.
 const received=new Array(links.length);let cursor=0;
 const worker=async()=>{while(cursor<links.length){const i=cursor++;received[i]=await tile(links[i]);}};
 await Promise.all([worker(),worker(),worker(),worker()]);
 const valid=received.filter(Boolean).length;
 if(valid<Math.max(1,Math.ceil(links.length*.65)))throw Error("Zu viele Radar-Kacheln nicht verfügbar");
 const merc=document.createElement("canvas");
 merc.width=(x1-x0+1)*256;merc.height=(y1-y0+1)*256;
 const mc=merc.getContext("2d");
 for(let i=0;i<received.length;i++)if(received[i])
  mc.drawImage(received[i],(tiles[i].x-x0)*256,(tiles[i].y-y0)*256);
 const out=document.createElement("canvas");out.width=width;out.height=height;
 const ctx=out.getContext("2d");
 const srcX=(tx(west,zoom)-x0)*256,srcW=(tx(east,zoom)-tx(west,zoom))*256;
 for(let row=0;row<height;row++){
  const lat=north-(row+.5)/height*(north-south);
  const srcY=(ty(lat,zoom)-y0)*256;
  ctx.drawImage(merc,srcX,Math.max(0,Math.min(merc.height-1,srcY)),srcW,1,0,row,width,1);
 }
 return {url:out.toDataURL("image/png"),valid,total:links.length};
}
async function update(input){
 if(input)context={...context,...input};
 const mine=++serial;
 overlay.style.opacity=String((+opacity.value||70)/100);
 if(!toggle.checked){clear("Radar ausgeschaltet.");return;}
 const area=AREAS[context.region];
 if(context.source!=="mtgi1"||!area){clear("Radar nur bei geografisch projizierten MTG-I1-Ansichten.");return;}
 if(!$("satFilmStage").hidden){clear("Radar wird nur im Einzelbild dargestellt, nicht während der Filmwiedergabe.");return;}
 const date=Date.parse(context.time);
 if(!Number.isFinite(date)){clear("Radar benötigt einen bestätigten Satellitenzeitpunkt.");return;}
 clear("Prüfe zeitlich passenden Radarverbund …");
 try{
  const data=await manifest();
  if(mine!==serial)return;
  const candidates=data.radar.past.filter(x=>Number.isInteger(x.time)&&
   /^\/v2\/radar\/\d+$/.test(x.path)&&x.time*1000<=date)
   .sort((a,b)=>b.time-a.time);
  const best=candidates[0];
  if(!best||date-best.time*1000>20*60000)
   throw Error("Kein Radarbild innerhalb der letzten 20 Minuten zum Satellitenzeitpunkt");
  const rendered=await renderFrame(best,data,area);
  if(mine!==serial)return;
  overlay.src=rendered.url;overlay.hidden=false;
  status.textContent="RainViewer-Radarkomposit "+new Date(best.time*1000).toISOString().slice(0,16).replace("T"," ")+" UTC (Kompositzeit, Einzelradare können abweichen) · "+
   rendered.valid+"/"+rendered.total+" Kacheln · © RainViewer";
 }catch(err){if(mine===serial)clear("Radar nicht angezeigt: "+err.message+".");}
}
toggle.addEventListener("change",()=>update());
opacity.addEventListener("change",()=>update());
region.addEventListener("change",()=>update({region:region.value}));
source.addEventListener("change",()=>update({source:source.value}));
window.SatelliteRadar={sync:update};
})();
