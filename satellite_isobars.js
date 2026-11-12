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
let data=null,loading=null,failed=false,context={time:null,region:"europe",source:"mtgi1"};
const MAX_SEPARATION=4*3600*1000; // never show a 12h old "matching" isobar field.
const MAX_DATA_AGE=30*3600*1000;
const MAX_STANDALONE_AGE=6*3600*1000; // latest forecast without a satellite image
const ns="http://www.w3.org/2000/svg";
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
function within(p,b){
 return p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
}
function draw(frame,bbox,gap){
 const [minX,minY,maxX,maxY]=bbox;
 const px=(lon)=>((lon-minX)/(maxX-minX)*1000).toFixed(2);
 const py=(lat)=>((maxY-lat)/(maxY-minY)*1000).toFixed(2);
 const batch=document.createDocumentFragment();
 for(const lineSet of frame.contours){
  const hpa=lineSet.hpa;
  if(hpa%gap!==0)continue;
  let labelCandidate=null,labelLen=0;
  for(const coords of lineSet.lines){
   if(coords.length<4)continue;
   const local=coords.filter(p=>within(p,bbox));
   if(local.length===0)continue;
   const shape=document.createElementNS(ns,"path");
   shape.setAttribute("d",coords.map((p,i)=>(i?"L":"M")+px(p[0])+" "+py(p[1])).join(" "));
   shape.setAttribute("fill","none");
   shape.setAttribute("stroke",hpa%10===0?"#ffffff":"#dbeaf6");
   shape.setAttribute("stroke-width",hpa%10===0?"1.45":"1");
   shape.setAttribute("vector-effect","non-scaling-stroke");
   shape.setAttribute("stroke-linejoin","round");
   batch.appendChild(shape);
   if(local.length>labelLen){labelLen=local.length;labelCandidate=local[Math.floor(local.length/2)];}
  }
  if(hpa%10===0&&labelCandidate&&labelLen>15){
   const [lon,lat]=labelCandidate;
   const text=document.createElementNS(ns,"text");
   text.setAttribute("x",px(lon));text.setAttribute("y",py(lat));
   text.setAttribute("class","sat-isobar-label");
   text.textContent=String(hpa);
   batch.appendChild(text);
  }
 }
 svg.replaceChildren(batch);
}
function update(){
 const supported=context.source==="mtgi1"&&Boolean(BBOX[context.region]);
 toggle.disabled=!supported;
 spacing.disabled=!supported||!toggle.checked;
 const active=supported&&toggle.checked;
 if(retry)retry.disabled=!active||Boolean(loading);
 svg.toggleAttribute("hidden",true);
 if(!active){svg.replaceChildren();note(!supported?"Isobaren für Erdscheibe/MTG-I2 nicht verfügbar (andere Projektion).":"Isobaren ausgeblendet.");return;}
 if(failed){svg.replaceChildren();note("ECMWF-Isobarenabruf fehlgeschlagen. Über „Isobaren neu laden“ erneut versuchen; Satellitenbilder bleiben unabhängig.");return;}
 if(!data){svg.replaceChildren();note("Lade echte ECMWF-IFS-Luftdruckdaten (0,25°) …");void load();return;}
 if(Date.now()-Date.parse(data.generated_at)>MAX_DATA_AGE){
  svg.replaceChildren();note("ECMWF-Druckdaten älter als 30 Stunden – Isobaren ausgeblendet. Bitte „Isobaren neu laden“ nutzen.");return;
 }
 const satelliteTime=Number.isFinite(Date.parse(context.time))?context.time:null;
 const frame=satelliteTime?frameFor(satelliteTime):latestIndependentFrame();
 if(!frame){
  svg.replaceChildren();
  note(satelliteTime
   ?"Für Satellit "+utc(satelliteTime)+" fehlt ein ECMWF-Feld innerhalb von 4 Stunden. Keine unpassenden Isobaren einblenden."
   :"Kein ECMWF-Feld mit Gültigkeit innerhalb der letzten 6 Stunden vorhanden. Isobaren ausgeblendet.");
  return;
 }
 draw(frame,BBOX[context.region],Number(spacing.value)||5);
 svg.toggleAttribute("hidden",false);
 const headline="ECMWF IFS "+utc(data.run_utc)+" · +"+frame.forecast_hour+" h Prognose · gültig "+utc(frame.valid_utc);
 if(satelliteTime){
  const lag=Math.round((Date.parse(satelliteTime)-Date.parse(frame.valid_utc))/60000);
  note(headline+" · Satellit "+utc(satelliteTime)+" ("+lag+" min später) · 0,25° · "+spacing.value+" hPa · © ECMWF (CC BY 4.0)");
 }else{
  note(headline+" · eigenständige Modellansicht ohne verifiziertes Satellitenbild · nicht als Satellitenmessung verstehen · "+spacing.value+" hPa · © ECMWF (CC BY 4.0)");
 }
}
async function load(){
 if(loading||data||failed)return loading;
 loading=(async()=>{
  try{
   const r=await fetch("./data/satellite_mslp/latest.json",{cache:"no-store"});
   if(!r.ok)throw Error("HTTP "+r.status);
   const d=await r.json();
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
   data=d;failed=false;
  }catch(err){console.warn("ECMWF isobar overlay",err);failed=true;}
  finally{loading=null;update();}
 })();
 return loading;
}
function sync(next){
 context={time:next?.time||null,region:next?.region||region.value,source:next?.source||source.value};
 update();
}
toggle.addEventListener("change",update);
if(retry)retry.addEventListener("click",()=>{data=null;failed=false;svg.replaceChildren();void load();});
spacing.addEventListener("change",update);
region.addEventListener("change",()=>{context.region=region.value;update();});
source.addEventListener("change",()=>{context.source=source.value;update();});
sync({time:null,region:region.value,source:source.value});
window.SatelliteIsobars={sync,frameFor};
})();