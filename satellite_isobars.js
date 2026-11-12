/* ECMWF IFS MSLP isobars over official Meteosat images.
 * Renders TRUE GRIB2-derived vector contours. No source imagery alterations.
 * Does not claim that model forecasts are observed surface analyses.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const svg=$("satIsobarSvg"),toggle=$("satShowIsobars"),spacing=$("satIsobarSpacing");
const status=$("satIsobarStatus"),retry=$("satRetryIsobars"),region=$("satRegion"),source=$("satSource");
const BBOX={
 europe:[-27,24,49,73],atlantic:[-70,15,35,75],
 southwest:[-37,24,19,53],central:[-2,43,25,58],
 germany:[5,47,16,56]
};
let data=null,loading=null,failed=false,errorDetail="",dataOrigin="",context={time:null,region:"europe",source:"mtgi1"};
const MAX_SEPARATION=4*3600*1000; // never show a 12h old "matching" isobar field.
const MAX_DATA_AGE=30*3600*1000;
const MAX_STANDALONE_AGE=12*3600*1000; // older forecasts may be shown, clearly labelled
const ns="http://www.w3.org/2000/svg";
const TEN_MS=10*60*1000;
const TEN_INDEX_URL="./data/satellite_mslp/ten_minute/index.json";
let tenIndex=null,tenLoading=null,tenChecked=0;
const tenChunks=new Map(),tenPending=new Map(),tenFailed=new Map();
const ENDPOINTS=["./data/satellite_mslp/preview.json","./data/satellite_mslp/latest.json","https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/data/satellite_mslp/latest.json"];
function note(s){status.textContent=s;}
function utc(time){return new Date(time).toISOString().slice(0,16).replace("T"," ")+" UTC";}
function frameFor(time){
 if(!data||!Number.isFinite(Date.parse(time)))return null;
 const target=Date.parse(time);
 const frames=data.frames.filter(f=>Number.isFinite(Date.parse(f.valid_utc))&&Date.parse(f.valid_utc)<=target)
  .sort((a,b)=>Date.parse(b.valid_utc)-Date.parse(a.valid_utc));
 const best=frames[0];
 if(!best||target-Date.parse(best.valid_utc)>MAX_SEPARATION)return null;
 return best;
}
function latestIndependentFrame(){
 if(!data)return null;
 const now=Date.now();
 const candidates=data.frames.filter(f=>Number.isFinite(Date.parse(f.valid_utc))&&Date.parse(f.valid_utc)<=now)
  .sort((a,b)=>Date.parse(b.valid_utc)-Date.parse(a.valid_utc));
 return candidates[0]&&now-Date.parse(candidates[0].valid_utc)<=MAX_STANDALONE_AGE?candidates[0]:null;
}
// New: immutable, hourly chunk files with gridded-MSLP interpolation at
// each ten-minute satellite time. No contour-line tweening or fake analyses.
async function fetchTenJson(url){
 const ctrl=typeof AbortController==="function"?new AbortController():null;
 const timer=ctrl&&typeof setTimeout==="function"?setTimeout(()=>ctrl.abort(),4800):null;
 try{
  const res=await fetch(url,{cache:url===TEN_INDEX_URL?"no-store":"force-cache",
   ...(ctrl?{signal:ctrl.signal}:{})});
  if(!res.ok)throw Error("HTTP "+res.status);
  return await res.json();
 }finally{if(timer!==null&&typeof clearTimeout==="function")clearTimeout(timer);}
}
async function loadTenIndex(force=false){
 if(tenLoading||(!force&&Date.now()-tenChecked<15*60000))return tenLoading;
 tenChecked=Date.now();
 tenLoading=(async()=>{
  try{
   const idx=await fetchTenJson(TEN_INDEX_URL);
   if(idx.schema_version!==2||idx.model!=="ECMWF IFS Open Data"||
      idx.time_resolution_minutes!==10||idx.source_interval_hours!==3||
      !Number.isFinite(Date.parse(idx.run_utc))||
      !Number.isFinite(Date.parse(idx.generated_at))||
      !idx.hours||Object.keys(idx.hours).length!==13)throw Error("Unsupported 10-minute pressure metadata");
   if(data&&Date.parse(idx.run_utc)<Date.parse(data.run_utc))return;
   if(tenIndex?.run_utc!==idx.run_utc){tenChunks.clear();tenFailed.clear();}
   tenIndex=idx;
  }catch(err){console.warn("Optional ECMWF ten-minute pressure overlay",err?.message||err);}
  finally{tenLoading=null;update();}
 })();
 return tenLoading;
}
function tenFrameAt(target){
 if(!tenIndex)return null;
 const run=Date.parse(tenIndex.run_utc),requested=Date.parse(target);
 if(!Number.isFinite(run)||!Number.isFinite(requested)||
    Date.now()-Date.parse(tenIndex.generated_at)>MAX_DATA_AGE||
    (data&&run<Date.parse(data.run_utc)))return null;
 const slot=Math.round((requested-run)/TEN_MS);
 if(slot<0||slot>72||Math.abs(run+slot*TEN_MS-requested)>5*60000)return null;
 const hour=Math.floor(slot/6),key="h"+String(hour).padStart(2,"0");
 const file=tenIndex.hours?.[key];
 if(typeof file!=="string"||!/^r\d{10}\/h\d{2}\.json$/.test(file))return null;
 const cacheKey=tenIndex.run_utc+"|"+key;
 const chunk=tenChunks.get(cacheKey);
 if(chunk){
  const f=chunk.frames[slot%6];
  if(f&&Date.parse(f.valid_utc)===run+slot*TEN_MS)return f;
  return null;
 }
 if(tenFailed.has(cacheKey)&&Date.now()-tenFailed.get(cacheKey)<5*60000)return null;
 if(!tenPending.has(cacheKey)){
  const task=(async()=>{
   try{
    const d=await fetchTenJson("./data/satellite_mslp/ten_minute/"+file);
    if(d.schema_version!==2||d.run_utc!==tenIndex?.run_utc||
       d.hour!==hour||!Array.isArray(d.frames)||
       d.frames.length!==(hour===12?1:6)||
       d.frames.some((f,i)=>!Array.isArray(f.contours)||!f.contours.length||
        Date.parse(f.valid_utc)!==run+(hour*6+i)*TEN_MS||
        f.interpolated!==((hour*6+i)%18!==0))){
      throw Error("Ten-minute pressure chunk failed UTC provenance validation");
    }
    tenChunks.set(cacheKey,d);
    tenFailed.delete(cacheKey);
    // LRU bounded to 4 hourly chunks, never load the entire 73-frame film.
    while(tenChunks.size>4)tenChunks.delete(tenChunks.keys().next().value);
   }catch(err){tenFailed.set(cacheKey,Date.now());console.warn("10-minute isobars chunk",err?.message||err);}
   finally{tenPending.delete(cacheKey);update();}
  })();
  tenPending.set(cacheKey,task);
 }
 return null;
}
function within(p,b){
 return p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
}
function draw(frame,bbox,gap){
 const [minX,minY,maxX,maxY]=bbox;
 const px=(lon)=>((lon-minX)/(maxX-minX)*1000).toFixed(2);
 const py=(lat)=>((maxY-lat)/(maxY-minY)*1000).toFixed(2);
 const batch=document.createDocumentFragment();
 let count=0;
 for(const level of frame.contours){
  if(level.hpa%gap!==0)continue;
  const paths=[];
  let candidate=null,longest=0;
  for(const coords of level.lines){
   if(!Array.isArray(coords)||coords.length<2)continue;
   const local=coords.filter(p=>within(p,bbox));
   if(local.length<2)continue;
   paths.push(coords.map((p,i)=>(i?"L":"M")+px(p[0])+" "+py(p[1])).join(" "));
   count++;
   if(local.length>longest){longest=local.length;candidate=local[Math.floor(local.length/2)];}
  }
  if(!paths.length)continue;
  const d=paths.join(" ");
  const major=level.hpa%10===0;
  const accent=major?"#ffb447":"#3bdeff";
  const halo=document.createElementNS(ns,"path");
  halo.setAttribute("d",d);halo.setAttribute("fill","none");
  halo.setAttribute("stroke","#061522");halo.setAttribute("stroke-opacity","0.93");
  halo.setAttribute("stroke-width",major?"5.3":"4.3");
  halo.setAttribute("stroke-linecap","round");
  halo.setAttribute("stroke-linejoin","round");
  halo.setAttribute("vector-effect","non-scaling-stroke");
  batch.appendChild(halo);
  const line=document.createElementNS(ns,"path");
  line.setAttribute("d",d);line.setAttribute("fill","none");
  line.setAttribute("stroke",accent);
  line.setAttribute("stroke-width",major?"2.8":"1.8");
  line.setAttribute("stroke-linejoin","round");
  line.setAttribute("vector-effect","non-scaling-stroke");
  batch.appendChild(line);
  if(major&&candidate&&longest>6){
   const x=Number(px(candidate[0])),y=Number(py(candidate[1]));
   const rect=document.createElementNS(ns,"rect");
   rect.setAttribute("x",String(x-21));rect.setAttribute("y",String(y-10));
   rect.setAttribute("width","42");rect.setAttribute("height","20");
   rect.setAttribute("rx","5");rect.setAttribute("fill","#07182a");
   rect.setAttribute("fill-opacity","0.92");
   rect.setAttribute("stroke",accent);rect.setAttribute("stroke-width","1.25");
   batch.appendChild(rect);
   const label=document.createElementNS(ns,"text");
   label.setAttribute("x",String(x));label.setAttribute("y",String(y));
   label.setAttribute("class","sat-isobar-label");
   label.textContent=String(level.hpa);
   batch.appendChild(label);
  }
 }
 svg.replaceChildren(batch);
 return count;
}
function update(){
 const supported=context.source==="mtgi1"&&Boolean(BBOX[context.region]);
 toggle.disabled=!supported;
 spacing.disabled=!supported||!toggle.checked;
 const active=supported&&toggle.checked;
 if(retry)retry.disabled=!active||Boolean(loading);
 svg.toggleAttribute("hidden",true);
 if(!active){svg.replaceChildren();note(!supported?"Isobaren für Erdscheibe/MTG-I2 nicht verfügbar (andere Projektion).":"Isobaren ausgeblendet.");return;}
 if(!data){
  if(failed){svg.replaceChildren();note("ECMWF-Isobarenabruf fehlgeschlagen ("+errorDetail+"). „Isobaren neu laden“ startet einen neuen Versuch.");return;}
  svg.replaceChildren();note("Lade echte ECMWF-IFS-Luftdruckdaten (0,25°) …");void load();return;
 }
 if(Date.now()-Date.parse(data.generated_at)>MAX_DATA_AGE){
  svg.replaceChildren();note("ECMWF-Druckdaten sind älter als 30 Stunden – Isobaren ausgeblendet.");return;
 }
 const requested=Number.isFinite(Date.parse(context.time))?context.time:new Date().toISOString();
 const satelliteTime=Number.isFinite(Date.parse(context.time))?context.time:null;
 const ten=tenFrameAt(requested);
 let frame=ten||((satelliteTime?frameFor(satelliteTime):null)||latestIndependentFrame());
 const aligned=Boolean(satelliteTime&&frame&&(!ten?frameFor(satelliteTime):true));
 if(!frame){
  svg.replaceChildren();
  note("Kein ausreichend aktuelles ECMWF-Druckfeld verfügbar. Letzter gültiger Modelllauf bleibt angegeben, statt falsche Isobaren zu zeigen.");
  return;
 }
 const lines=draw(frame,BBOX[context.region],Number(spacing.value)||5);
 if(!lines){note("ECMWF-Daten vorhanden, aber keine sichtbaren "+spacing.value+"-hPa-Isobaren in diesem Ausschnitt.");return;}
 svg.toggleAttribute("hidden",false);
 const interpolated=Boolean(ten?.interpolated);
 const run=ten?tenIndex.run_utc:data.run_utc;
 const base="ECMWF IFS Lauf "+utc(run)+" · gültig "+utc(frame.valid_utc);
 const derivation=ten?(interpolated?" · 10-Minuten-Interpolation des MSLP-Gitterfelds":" · Original-IFS-Druckfeld"):" · 3-h-Original-Isobaren (Ersatz)";
 const origin=ten?" · stündlich zwischengespeicherte Vektorkarte":
  dataOrigin==="preview"?" · kompakte Originalkonturen":" · ECMWF-Originalkonturen";
 const deltaMinutes=satelliteTime?Math.round((Date.parse(satelliteTime)-Date.parse(frame.valid_utc))/60000):null;
 const syncLabel=satelliteTime?(aligned?
   " · Satellit "+utc(satelliteTime)+(ten&&deltaMinutes!==0?" ("+(deltaMinutes>0?"+":"")+deltaMinutes+" min Zeitdifferenz)":""):
   " · nicht zeitgleich mit Satellitenbild "+utc(satelliteTime)):
   " · eigenständige ECMWF-Karte ohne Satellitenbild";
 note(base+derivation+" · "+lines+" Linien"+syncLabel+" · "+spacing.value+" hPa"+origin+" · © ECMWF");
}
async function load(force=false){
 if(loading||(!force&&(data||failed)))return loading;
 loading=(async()=>{
  const problems=[];
  try{
   // On first load use the small Pages preview. On manual/periodic refresh
   // ask GitHub for the newest full dataset without blanking the visible map.
   const choices=force&&data?[ENDPOINTS[2],ENDPOINTS[0],ENDPOINTS[1]]:ENDPOINTS;
   for(const url of choices){
    try{
     // A blocked remote host must not stall the usable same-origin vector data.
     const ctrl=typeof AbortController==="function"?new AbortController():null;
     const timer=ctrl&&typeof setTimeout==="function"?setTimeout(()=>ctrl.abort(),5500):null;
     let d;
     try{
      const r=await fetch(url,{cache:"no-store",...(ctrl?{signal:ctrl.signal}:{})});
      if(!r.ok)throw Error("HTTP "+r.status);
      d=await r.json();
     }finally{if(timer!==null&&typeof clearTimeout==="function")clearTimeout(timer);}
     if(d.schema_version!==1||d.model!=="ECMWF IFS Open Data"||
        d.field!=="mean sea-level pressure"||d.units!=="hPa"||
        d.resolution_degrees!==0.25||d.interval_hpa!==5||
        !Array.isArray(d.frames)||d.frames.length<1||
        !Array.isArray(d.bbox)||d.bbox[0]>-70||d.bbox[2]<49||d.bbox[3]<75||
        !Number.isFinite(Date.parse(d.run_utc))||
        !Number.isFinite(Date.parse(d.generated_at)))throw Error("Ungültiges ECMWF-Isobarenformat");
     for(const f of d.frames){
      if(!Number.isFinite(Date.parse(f.valid_utc))||!Number.isInteger(f.forecast_hour)||
         Date.parse(f.valid_utc)!==Date.parse(d.run_utc)+f.forecast_hour*3600000||
         !Array.isArray(f.contours)||!f.contours.length||
         f.contours.some(g=>g.hpa%5!==0||!Array.isArray(g.lines)))
        throw Error("Ungültiger UTC- oder Konturendatensatz");
     }

     if(data&&Date.parse(d.run_utc)<Date.parse(data.run_utc))throw Error("Älterer ECMWF-Lauf als der bereits geladene Stand");
     data=d;failed=false;errorDetail="";dataOrigin=url===ENDPOINTS[0]?"preview":url===ENDPOINTS[1]?"pages":"github";
     break;
    }catch(err){
     problems.push((url===ENDPOINTS[0]?"Schnelle Isobaren":url===ENDPOINTS[1]?"Lokale ECMWF-Daten":"GitHub-Rohdaten")+": "+(err?.message||String(err)));
    }
   }
   if(!data)throw Error(problems.join(" | "));
  }catch(err){
   console.warn("ECMWF isobar overlay",err);
   failed=!data;errorDetail=(err?.message||String(err)).slice(0,240);
  }finally{loading=null;update();if(data)void loadTenIndex(false);}
 })();
 return loading;
}
function sync(next){
 context={time:next?.time||null,region:next?.region||region.value,source:next?.source||source.value};
 update();
}
toggle.addEventListener("change",update);
if(retry)retry.addEventListener("click",()=>{if(loading)return;failed=false;errorDetail="";tenFailed.clear();void load(true);void loadTenIndex(true);});
spacing.addEventListener("change",update);
region.addEventListener("change",()=>{context.region=region.value;update();});
source.addEventListener("change",()=>{context.source=source.value;update();});
sync({time:null,region:region.value,source:source.value});
// Periodically retrieve newer committed ECMWF runs without removing working contours
// during transient network errors or downgrading to an older model cycle.
if(typeof setInterval==="function"){
 setInterval(()=>{
  if(source.value==="mtgi1"&&toggle.checked&&!document.hidden&&!loading){
   failed=false;void loadTenIndex(true);
   if(!tenIndex)void load(true);
  }
 },15*60*1000);
}
window.SatelliteIsobars={sync,frameFor,tenFrameAt};
})();