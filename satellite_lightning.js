/* Official MTG Lightning Imager LI-AFA, 5-minute optical flash-area accumulations.
 * Each image is requested at its own WMS-advertised UTC time; never infer live data. */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const toggle=$("satShowLightning"),period=$("satLightningWindow"),status=$("satLightningStatus");
const stack=$("satImageStack"),region=$("satRegion"),source=$("satSource");
if(!toggle||!period||!status||!stack)return;
const LAYER="mtg_fd:li_afa",API="https://view.eumetsat.int/geoserver/wms";
const AREAS={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
const stage=$("satLightningOverlay");
let context={time:null,region:"europe",source:"mtgi1"},timeline=[],checked=0,loading=null,epoch=0,lastLoadError="";
const fmt=t=>new Date(t).toISOString().slice(0,16).replace("T"," ")+" UTC";
function clear(message){
 stage.replaceChildren();stage.hidden=true;
 if(message)status.textContent=message;
}
function readTimes(value){
 const now=Date.now()+600000,out=new Set();
 for(const item of String(value||"").split(",")){
  const s=item.trim();
  if(!s)continue;
  if(s.includes("/")){
   const parts=s.split("/"),start=Date.parse(parts[0]),end=Date.parse(parts[1]);
   const match=(parts[2]||"").match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
   const step=match?((+match[1]||0)*60+(+match[2]||0))*60000+(+match[3]||0)*1000:0;
   if(!step||!Number.isFinite(start)||!Number.isFinite(end))continue;
   for(let i=0;i<96;i++){const n=end-i*step;if(n<start)break;if(n<=now)out.add(new Date(n).toISOString());}
  }else if(Number.isFinite(Date.parse(s))&&Date.parse(s)<=now)out.add(new Date(s).toISOString());
 }
 return [...out].sort().slice(-96);
}
async function loadTimes(){
 if(loading)return loading;
 if(Date.now()-checked<3*60000)return timeline;
 checked=Date.now();
 loading=(async()=>{
  try{
   // Abort a stalled Pages manifest fetch so LI does not show an endless spinner.
   const controller=typeof AbortController==="function"?new AbortController():null;
   const deadline=controller?setTimeout(()=>controller.abort(),8000):null;
   let response;
   try{
    response=await fetch("./data/satellite_wms_times.json",controller?
      {cache:"no-store",signal:controller.signal}:{cache:"no-store"});
   }finally{if(deadline!==null)clearTimeout(deadline);}
   if(!response.ok)throw Error("Statusdatei nicht erreichbar");
   const info=await response.json();
   // The hourly WMS monitor publishes LI at the root, while some prior
   // schemas used products.lightning. Accept only validated values.
   const entry=info.lightning||info.products?.lightning;
   const age=Date.now()-Date.parse(info.generated_at);
   if(!info.capabilities_ok||age<0||age>4*3600000||
      entry?.layer!==LAYER||!entry.map_ok||!entry.latest_verified_time)
    throw Error("Noch kein bildgeprüfter LI-WMS-Lauf");
   const listed=readTimes((entry.available_times||[]).join(","));
   if(!listed.includes(new Date(entry.latest_verified_time).toISOString()))throw Error("LI-Zeitprüfung widersprüchlich");
   timeline=listed;lastLoadError="";
  }catch(err){
   timeline=[];lastLoadError=err.message;status.textContent="LI-AFA derzeit nicht verifiziert: "+err.message+". Keine Blitzdaten eingeblendet.";
  }finally{loading=null;}
  return timeline;
 })();
 return loading;
}
function url(t,area){
 const width=480,height=Math.round(width*area[5]/area[4]);
 return API+"?"+new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetMap",
  layers:LAYER,styles:"",format:"image/png",transparent:"true",srs:"EPSG:4326",
  bbox:area.slice(0,4).join(","),width:String(width),height:String(height),time:t}).toString();
}
async function update(input){
 if(input)context={...context,...input};
 const mine=++epoch,area=AREAS[context.region];
 if(!toggle.checked){clear("Blitzdaten ausgeschaltet.");return;}
 if(context.source!=="mtgi1"||!area){
  clear("LI-Overlay nur für georeferenzierte MTG-I1-Kartenausschnitte verfügbar.");return;
 }
 if(!$("satFilmStage").hidden){clear("LI während der Filmwiedergabe pausiert; in Einzelbildern verfügbar.");return;}
 if(!Number.isFinite(Date.parse(context.time))){clear("Kein geprüfter Satellitenzeitpunkt für die LI-Synchronisierung.");return;}
 clear("Prüfe offizielle MTG-LI-Blitzakkumulationen …");
 const times=await loadTimes();if(epoch!==mine)return;
 if(!times.length){clear("LI-AFA nicht verfügbar: "+(lastLoadError||"keine geprüften UTC-Zeitpunkte")+".");return;}
 const target=Date.parse(context.time);
 // AFA timestamp describes the beginning of its 5-minute accumulation.
 const latest=[...times].reverse().find(t=>Date.parse(t)+5*60000<=target);
 if(!latest||target-(Date.parse(latest)+5*60000)>10*60000){
  clear("Keine zeitlich passende LI-AFA-Akkumulation (maximal 10 Minuten Differenz).");return;
 }
 const n=+period.value||1;
 const chosen=[];
 for(let i=0;i<n;i++){
  const t=new Date(Date.parse(latest)-i*5*60000).toISOString();
  if(!times.includes(t))break;
  chosen.unshift(t);
 }
 if(chosen.length!==n){clear("Für "+(n*5)+" Minuten fehlen bestätigte LI-Teilbilder.");return;}
 const nodes=chosen.map((t,i)=>{
  const img=new Image();img.crossOrigin="anonymous";img.decoding="async";
  img.alt="MTG-LI Accumulated Flash Area · "+fmt(t);
  img.style.opacity=String(Math.min(.9,1.15/n)); // not a quantitative lightning count
  img.src=url(t,area);
  return img;
 });
 const result=await Promise.all(nodes.map(img=>new Promise(resolve=>{
  let done=false;
  const finish=ok=>{if(done)return;done=true;clearTimeout(timer);img.onload=null;img.onerror=null;resolve(ok);};
  const timer=setTimeout(()=>finish(false),8000);
  img.onload=()=>finish(img.naturalWidth>0);img.onerror=()=>finish(false);
  if(img.complete)finish(img.naturalWidth>0);
 })));
 if(epoch!==mine)return;
 if(!result.every(Boolean)){
  clear("LI-Bildabruf nicht vollständig oder WMS gestört. Keine unbestätigten Blitzbilder angezeigt.");return;
 }
 stage.replaceChildren(...nodes);stage.hidden=false;
 status.textContent="MTG LI-AFA · "+(n*5)+" Minuten, "+fmt(chosen[0])+" bis "+fmt(new Date(Date.parse(chosen.at(-1))+5*60000))+
  " · optische Blitzflächen, keine Blitzpunktmessung · © EUMETSAT";
}
toggle.addEventListener("change",()=>update());
period.addEventListener("change",()=>update());
region.addEventListener("change",()=>update({region:region.value}));
source.addEventListener("change",()=>update({source:source.value}));
window.SatelliteLightning={sync:update};
})();
