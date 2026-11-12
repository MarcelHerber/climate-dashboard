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
const FINE_REGIONS=new Set(["europe","southwest","central","germany"]);
const isFineRegion=place=>FINE_REGIONS.has(place);
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
      !idx.hours||![13,19].includes(Object.keys(idx.hours).length))throw Error("Unsupported 10-minute pressure metadata");
   if(data&&Date.parse(idx.run_utc)<Date.parse(data.run_utc))return;
   // Legacy manifests without a fine_hours map still work in default 5 hPa.
   const fine=idx.fine_hours;
   if(fine!==undefined&&(
      idx.fine_interval_hpa!==2||
      !Array.isArray(idx.fine_regions)||
      ![13,19].includes(Object.keys(fine).length)||
      !Object.values(fine).every(x=>typeof x==="string"&&/^r\d{10}\/h\d{2}_2hpa\.json$/.test(x))))
       throw Error("Ungültige 2-hPa-Metadaten");
   if(tenIndex?.run_utc!==idx.run_utc){tenChunks.clear();tenFailed.clear();}
   tenIndex=idx;
  }catch(err){console.warn("Optional ECMWF ten-minute pressure overlay",err?.message||err);}
  finally{tenLoading=null;update();}
 })();
 return tenLoading;
}
function tenFrameAt(target,gap=5){
 if(!tenIndex)return null;
 const run=Date.parse(tenIndex.run_utc),requested=Date.parse(target);
 if(!Number.isFinite(run)||!Number.isFinite(requested)||
    Date.now()-Date.parse(tenIndex.generated_at)>MAX_DATA_AGE||
    (data&&run<Date.parse(data.run_utc)))return null;
 const slot=Math.round((requested-run)/TEN_MS);
 const lastHour=Object.keys(tenIndex.hours).length-1;
 if(slot<0||slot>lastHour*6||Math.abs(run+slot*TEN_MS-requested)>5*60000)return null;
 const hour=Math.floor(slot/6),key="h"+String(hour).padStart(2,"0");
 const fine=Number(gap)===2;
 const lookup=fine?tenIndex.fine_hours:tenIndex.hours;
 const file=lookup?.[key];
 if(fine&&!isFineRegion(context.region))return null;
 const expected=fine?/^r\d{10}\/h\d{2}_2hpa\.json$/:/^r\d{10}\/h\d{2}\.json$/;
 if(typeof file!=="string"||!expected.test(file))return null;
 const cacheKey=tenIndex.run_utc+"|"+(fine?"2":"5")+"|"+key;
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
       (fine&&(d.interval_hpa!==2||!d.regions?.includes(context.region)))||
       d.hour!==hour||!Array.isArray(d.frames)||
       d.frames.length!==(hour===lastHour?1:6)||
       d.frames.some((f,i)=>!Array.isArray(f.contours)||!f.contours.length||
        (fine&&f.contours.some(group=>group.hpa%2!==0))||
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
 const geometry=window.SatelliteIsobarGeometry;
 if(!geometry?.prepare)throw Error("Isobaren-Darstellungsfilter fehlt.");
 const groups=geometry.prepare(frame.contours,bbox,gap);
 const [minX,minY,maxX,maxY]=bbox;
 const px=lon=>((lon-minX)/(maxX-minX)*1000).toFixed(2);
 const py=lat=>((maxY-lat)/(maxY-minY)*1000).toFixed(2);
 const batch=document.createDocumentFragment();
 let count=0;
 for(const group of groups){
  const d=group.runs.map(points=>{
   count++;
   return points.map((p,i)=>(i?"L":"M")+px(p[0])+" "+py(p[1])).join(" ");
  }).join(" ");
  const inner=Number(gap)===2?"0.75":group.heavy?"1.55":"0.9";
  const outer=Number(gap)===2?"1.85":group.heavy?"2.95":"2.3";
  const halo=document.createElementNS(ns,"path");
  halo.setAttribute("d",d);halo.setAttribute("fill","none");
  halo.setAttribute("stroke","#061522");halo.setAttribute("stroke-opacity","0.93");
  halo.setAttribute("stroke-width",outer);
  halo.setAttribute("stroke-linecap","round");
  halo.setAttribute("stroke-linejoin","round");
  halo.setAttribute("vector-effect","non-scaling-stroke");
  batch.appendChild(halo);
  const line=document.createElementNS(ns,"path");
  line.setAttribute("d",d);line.setAttribute("fill","none");
  line.setAttribute("stroke","#ff4fcf");
  line.setAttribute("stroke-width",inner);
  line.setAttribute("stroke-linecap","round");
  line.setAttribute("stroke-linejoin","round");
  line.setAttribute("vector-effect","non-scaling-stroke");
  batch.appendChild(line);
  if(group.label){
   const x=Number(px(group.label[0])),y=Number(py(group.label[1]));
   const rect=document.createElementNS(ns,"rect");
   rect.setAttribute("x",String(x-21));rect.setAttribute("y",String(y-10));
   rect.setAttribute("width","42");rect.setAttribute("height","20");
   rect.setAttribute("rx","5");rect.setAttribute("fill","#07182a");
   rect.setAttribute("fill-opacity","0.92");
   rect.setAttribute("stroke","#ff4fcf");rect.setAttribute("stroke-width","0.65");
   batch.appendChild(rect);
   const label=document.createElementNS(ns,"text");
   label.setAttribute("x",String(x));label.setAttribute("y",String(y));
   label.setAttribute("class","sat-isobar-label");
   label.textContent=String(group.hpa);
   batch.appendChild(label);
  }
 }
 // H/T only for significant, fully closed nested IFS isobars.
 const limits={atlantic:8,europe:6,southwest:5,central:3,germany:2};
 const systems=geometry.detectVisiblePressureSystems?.(frame.contours,bbox,{
  maxSystems:limits[context.region]||5,minRings:3,minSeparation:94
 })||[];
 for(const center of systems){
  const lon=((center.lon-minX)/(maxX-minX))*1000;
  const lat=((maxY-center.lat)/(maxY-minY))*1000;
  const glyph=document.createElementNS(ns,"text");
  glyph.setAttribute("x",lon.toFixed(2));
  glyph.setAttribute("y",lat.toFixed(2));
  glyph.setAttribute("class","sat-pressure-center");
  glyph.setAttribute("data-pressure-type",center.type);
  glyph.setAttribute("aria-label",(center.type==="T"?"Tief":"Hoch")+
   "druckzentrum "+center.hpa+" hPa");
  glyph.setAttribute("fill",center.type==="T"?"#cf4baf":"#9750c4");
  glyph.textContent=center.type;
  batch.appendChild(glyph);
 }
 svg.replaceChildren(batch);
 return count;
}
function refreshSpacing(){
 const permitted=isFineRegion(context.region)&&context.source==="mtgi1";
 const fineOption=spacing.querySelector?.('option[value="2"]');
 if(fineOption){fineOption.hidden=!permitted;fineOption.disabled=!permitted;}
 if(!permitted&&spacing.value==="2")spacing.value="5";
}
function update(){
 refreshSpacing();
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
 const gap=Number(spacing.value)||5;
 const ten=tenFrameAt(requested,gap);
 let frame=ten||(gap===2?null:
  ((satelliteTime?frameFor(satelliteTime):null)||latestIndependentFrame()));
 const aligned=Boolean(satelliteTime&&frame&&(!ten?frameFor(satelliteTime):true));
 if(!frame){
  svg.replaceChildren();
  note(gap===2?
   "2-hPa-Isobaren für diesen ECMWF-Lauf noch nicht bereitgestellt oder werden geladen. Keine 5-hPa-Ersatzlinien als 2 hPa ausgeben.":
   "Kein ausreichend aktuelles ECMWF-Druckfeld verfügbar. Letzter gültiger Modelllauf bleibt angegeben, statt falsche Isobaren zu zeigen.");
  return;
 }
 const lines=draw(frame,BBOX[context.region],gap);
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
// Expose only genuine, time-provenanced grid-derived lines for map exports.
// Await the correct ten-minute chunk; never silently export an empty overlay.
async function exportAt(time,place,gap=5,{strictTenMinute=false}={}){
 gap=Number(gap)||5;
 if(gap===2&&!isFineRegion(place))
  throw Error("2-hPa-Isobaren gibt es nur für Europa, Südwesteuropa, Mitteleuropa und Deutschland.");
 if(!BBOX[place])throw Error("Für diesen Kartenausschnitt gibt es keine georeferenzierten Isobaren.");
 if(!Number.isFinite(Date.parse(time)))throw Error("Kein verifizierter Satellitenzeitpunkt für den Isobarenexport.");
 if(!data&&!loading)await load();
 else if(loading)await loading;
 if(!tenIndex)await loadTenIndex();
 let frame=tenFrameAt(time,gap);
 if(!frame&&tenIndex){
  const run=Date.parse(tenIndex.run_utc),slot=Math.round((Date.parse(time)-run)/TEN_MS);
  const hour=Math.floor(slot/6),key="h"+String(hour).padStart(2,"0");
  const promise=tenPending.get(tenIndex.run_utc+"|"+(gap===2?"2":"5")+"|"+key);
  if(promise)await promise;
  frame=tenFrameAt(time,gap);
 }
 if(gap===2&&!frame)throw Error("Für "+utc(time)+" fehlen die berechneten 2-hPa-Konturen. Export nicht erstellt.");
 if(strictTenMinute&&!frame)
  throw Error("Für "+utc(time)+" fehlen die passenden 10-Minuten-Isobaren. GIF mit Isobaren nicht erzeugt.");
 if(!frame)frame=frameFor(time);
 if(!frame)throw Error("Keine gültigen ECMWF-Isobaren zu "+utc(time)+". Kein Export ohne Drucklinien.");
 const exact10=Boolean(tenIndex&&frame.forecast_minute!==undefined);
 const run=exact10?tenIndex.run_utc:data.run_utc;
 const method=exact10?(frame.interpolated?"10-Minuten-Interpolation des MSLP-Gitterfeldes":"Original-IFS-Druckfeld"):"3-h-IFS-Druckfeld (Ersatz)";
 if(!Array.isArray(frame.contours)||!frame.contours.length)throw Error("Isobaren-Konturen fehlen.");
 return {contours:frame.contours,validUTC:frame.valid_utc,runUTC:run,
  satelliteUTC:time,method,interpolated:exact10&&Boolean(frame.interpolated),
  spacing:gap,region:place,exact10};
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
window.SatelliteIsobars={sync,frameFor,tenFrameAt,exportAt};
})();