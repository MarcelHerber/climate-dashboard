/* ECMWF IFS MSLP isobars over official Meteosat images.
 * Renders TRUE GRIB2-derived vector contours. No source imagery alterations.
 * Does not claim that model forecasts are observed surface analyses.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const svg=$("satIsobarSvg"),toggle=$("satShowIsobars"),spacing=$("satIsobarSpacing");
const status=$("satIsobarStatus"),region=$("satRegion"),source=$("satSource");
const BBOX={
 europe:[-27,24,49,73],atlantic:[-70,15,35,75],
 southwest:[-37,24,19,53],central:[-2,43,25,58],
 germany:[5,47,16,56]
};
let data=null,loading=null,failed=false,context={time:null,region:"europe",source:"mtgi1"};
const MAX_SEPARATION=4*3600*1000; // never show a 12h old "matching" isobar field.
const MAX_DATA_AGE=30*3600*1000;
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
 svg.toggleAttribute("hidden",!active||!data);
 if(!active){svg.replaceChildren();note(!supported?"Isobaren für Erdscheibe/MTG-I2 nicht verfügbar (andere Projektion).":"Isobaren ausgeblendet.");return;}
 if(failed){svg.replaceChildren();note("ECMWF-IFS-Druckfeld momentan nicht verfügbar. Satellitenbilder bleiben nutzbar.");return;}
 if(!data){svg.replaceChildren();note("Lade echte ECMWF-IFS-Luftdruckdaten (0,25°) …");load();return;}
 if(!context.time){svg.replaceChildren();svg.toggleAttribute("hidden",true);note("Isobaren erst nach bestätigtem Satelliten-UTC-Zeitpunkt verfügbar.");return;}
 const frame=frameFor(context.time),bbox=BBOX[context.region];
 if(!frame){
  svg.replaceChildren();svg.toggleAttribute("hidden",true);
  note("Für "+utc(context.time)+" gibt es kein passendes ECMWF-IFS-Feld innerhalb von 4 Stunden. Isobaren ausgeblendet.");
  return;
 }
 if(Date.now()-Date.parse(data.generated_at)>MAX_DATA_AGE){
  svg.replaceChildren();svg.toggleAttribute("hidden",true);
  note("ECMWF-Vektordaten sind älter als 30 Stunden. Kein veraltetes Druckfeld einblenden.");
  return;
 }
 draw(frame,bbox,Number(spacing.value)||5);
 svg.toggleAttribute("hidden",false);
 const lag=Math.round((Date.parse(context.time)-Date.parse(frame.valid_utc))/60000);
 note("ECMWF IFS "+utc(data.run_utc)+" · +"+frame.forecast_hour+" h Vorhersage · gültig "+utc(frame.valid_utc)
  +" · Satellit "+utc(context.time)+" ("+lag+" min später) · 0,25° · "+spacing.value+" hPa · © ECMWF (CC BY 4.0)");
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
      !Array.isArray(d.bbox)||d.bbox[0]>-70||d.bbox[2]<35||
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
spacing.addEventListener("change",update);
region.addEventListener("change",()=>{context.region=region.value;update();});
source.addEventListener("change",()=>{context.source=source.value;update();});
sync({time:null,region:region.value,source:source.value});
window.SatelliteIsobars={sync,frameFor};
})();