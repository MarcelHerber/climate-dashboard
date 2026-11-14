/* Genuine NOAA WPC HIGH-RES *analyzed* frontal polylines over MTG EPSG:4326.
 * Separate from the DWD manual front source and ECMWF IFS isobars.
 * Official WPC bulletin is 0.1-degree coordinate text; do not mix source
 * labels, timestamps or invent frontal motion symbols not in the bulletin.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const svg=$("satWpcFrontSvg"),toggle=$("satShowWpcFronts"),msg=$("satWpcFrontStatus"),
 timeLabel=$("satWpcFrontUTC"),link=$("satWpcFrontSource"),
 region=$("satRegion"),source=$("satSource");
if(!svg||!toggle||!msg||!timeLabel||!link||!region||!source)return;
const INPUT="./data/synoptic_charts/noaa_wpc_fronts_geo.json";
const TRUSTED="https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt";
const BBOX={
 europe:[-27,24,49,73],atlantic:[-70,15,35,75],
 southwest:[-37,24,19,53],central:[-2,43,25,58],germany:[5,47,16,56]
};
const COLORS={cold:"#5998c9",warm:"#d77a76",occluded:"#a795c5",stationary:"#a795c5"};
let info=null,context={time:null,region:region.value,source:source.value},lastStatus="";
function utc(s){
 if(typeof s!=="string"||!/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?Z$/.test(s))return null;
 const ms=Date.parse(s);return Number.isFinite(ms)?ms:null;
}
function nice(ms){
 return new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",
  year:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(ms)+" UTC";
}
function validate(raw){
 if(raw?.schema_version!==1||raw?.status!=="verified"||raw.provider!=="NOAA WPC"||
    raw.kind!=="analysis"||raw.coordinate_reference_system!=="EPSG:4326"||
    raw.georeferencing_verified!==true||raw.front_source_format!=="CODSUS-HIRES"||
    raw.source_url!==TRUSTED||raw.geographic_precision_degrees!==0.1||
    !Array.isArray(raw.features)||!raw.features.length||raw.features.length>600)return null;
 const valid=utc(raw.valid_utc);
 if(valid===null||Date.now()-valid>14*3600000||valid-Date.now()>30*60000)return null;
 const features=[];
 let total=0;
 for(const f of raw.features){
  const p=f?.properties||{},g=f?.geometry;
  if(f?.type!=="Feature"||!Object.prototype.hasOwnProperty.call(COLORS,p.front_type)||
     g?.type!=="LineString"||!Array.isArray(g.coordinates)||
     g.coordinates.length<2||g.coordinates.length>3000)return null;
  total+=g.coordinates.length;
  if(total>60000)return null;
  let cleaned=[];
  for(const point of g.coordinates){
   if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite)||
      point[0]<-180||point[0]>180||point[1]<0||point[1]>90)return null;
   cleaned.push(point);
  }
  features.push({type:p.front_type,coords:cleaned,
   symbol_orientation_verified:p.symbol_orientation_verified===true&&["left","right"].includes(p.symbol_side),
   symbol_side:p.symbol_orientation_verified===true&&["left","right"].includes(p.symbol_side)?p.symbol_side:null});
 }
 return {...raw,features};
}
function project(point,bbox){
 return [(point[0]-bbox[0])*1000/(bbox[2]-bbox[0]),
         (bbox[3]-point[1])*1000/(bbox[3]-bbox[1])];
}
function intersect(arr,bbox){
 // Include a feature that passes through viewport even if both endpoints lie
 // outside; let SVG clip at viewbox borders.
 const xs=arr.map(p=>p[0]),ys=arr.map(p=>p[1]);
 return !(Math.max(...xs)<bbox[0]||Math.min(...xs)>bbox[2]||
          Math.max(...ys)<bbox[1]||Math.min(...ys)>bbox[3]);
}
function current(){
 const valid=info&&utc(info.valid_utc);
 return valid!==null&&valid!==undefined&&Date.now()-valid<=14*3600000&&valid-Date.now()<=30*60000;
}
function visibleFor(time,place){
 if(!info||!current()||source.value!=="mtgi1"||place!==region.value||!BBOX[place])return [];
 const stamp=utc(time),valid=utc(info.valid_utc);
 if(stamp===null||stamp===undefined||valid===null)return [];
 const delta=(stamp-valid)/3600000;
 if(delta < -1||delta > 12)return [];
 return info.features.filter(f=>intersect(f.coords,BBOX[place]));
}
function exportAt(time,place){
 if(window.SatelliteFrontsPaused===true)return null;
 // Export exactly the front layer the user enabled, with the same spatial,
 // source and temporal constraints as the visible EPSG:4326 satellite map.
 if(!toggle.checked||!current())return null;
 const selected=visibleFor(time,place);
 if(!selected.length)return null;
 return {provider:"NOAA WPC",source_url:TRUSTED,
  coordinate_reference_system:"EPSG:4326",front_source_format:"CODSUS-HIRES",
  valid_utc:info.valid_utc,satelliteUTC:time,region:place,
  features:selected.map(f=>({type:f.type,coords:f.coords.map(p=>[...p]),
   symbol_orientation_verified:f.symbol_orientation_verified,symbol_side:f.symbol_side}))};
}
function reset(){
 svg.replaceChildren();svg.setAttribute("hidden","");
}
function sync(next){
 context={time:next?.time||null,region:next?.region||region.value,
          source:next?.source||source.value};
 render();
}
function render(){
 reset();
 if(window.SatelliteFrontsPaused===true){
  toggle.checked=false;toggle.disabled=true;
  msg.textContent="Fronten auf dieser Satellitenseite vorerst deaktiviert.";
  timeLabel.textContent="";return;
 }
 const bbox=BBOX[context.region];
 if(!bbox||context.source!=="mtgi1"){
  toggle.disabled=true;msg.textContent="NOAA-Fronten auf dieser Satellitenprojektion nicht darstellbar.";
  timeLabel.textContent="";return;
 }
 if(!info||!current()){
  toggle.disabled=true;
  msg.textContent=lastStatus||"NOAA WPC: Kein gültiges aktuelles Frontalanalyse-Bulletin. "+
    "Für Europa bleiben die ECMWF-Isobaren verfügbar; DWD-Vektordaten werden separat geprüft.";
  timeLabel.textContent="";return;
 }
 const thisTime=utc(context.time),validTime=utc(info.valid_utc);
 const hours=thisTime!==null?(thisTime-validTime)/3600000:null;
 timeLabel.textContent="NOAA WPC "+nice(validTime)+(hours===null?
  " · Satellitenzeit ungeprüft":" · Differenz Satellit "+(hours>=0?"+":"")+hours.toFixed(1).replace(".",",")+" h");
 const matches=info.features.filter(f=>intersect(f.coords,bbox));
 toggle.disabled=!matches.length;
 if(!matches.length){
  msg.textContent="NOAA WPC: Keine analysierten Frontlinien in diesem Kartenausschnitt. "+
   "Der US-Dienst deckt vor allem Nordamerika und den westlichen Nordatlantik ab.";
  return;
 }
 if(!toggle.checked){
  msg.textContent="NOAA-WPC-Analysefronten ausgeschaltet · "+matches.length+" Linien verfügbar.";
  return;
 }
 if(thisTime===null||hours < -1||hours > 12){
  msg.textContent="NOAA-Fronten nicht angezeigt: Satellitenzeit fehlt oder mehr als 12 Stunden "+
   "von der NOAA-Analyse entfernt.";
  return;
 }
 const style=window.SatelliteFrontStyle;
 if(!style?.layout||!style.cmdString){
  msg.textContent="Frontendarstellung nicht geladen. Keine ungeprüfte Ersatzzeichnung.";
  return;
 }
 const NS="http://www.w3.org/2000/svg";
 const visible=matches.slice(0,350);
 const make=(d,{stroke,fill="none",width}={})=>{
  const element=document.createElementNS(NS,"path");
  element.setAttribute("d",d);element.setAttribute("fill",fill);
  if(stroke)element.setAttribute("stroke",stroke);
  if(width!==undefined)element.setAttribute("stroke-width",String(width));
  element.setAttribute("stroke-linejoin","round");
  element.setAttribute("stroke-linecap","round");
  element.setAttribute("vector-effect","non-scaling-stroke");
  return element;
 };
 for(const feature of visible){
  const g=style.layout(feature,pos=>project(pos,bbox),1);
  if(!g)continue;
  const path=style.cmdString(g.commands);
  svg.appendChild(make(path,{stroke:"#122438",width:2.55}));
  if(feature.type==="stationary"){
   for(const part of g.sections)
    svg.appendChild(make(style.cmdString(part.commands),{stroke:part.color,width:1.4}));
  }else svg.appendChild(make(path,{stroke:g.color,width:1.4}));
  for(const symbol of g.symbols){
   const shape=make(style.cmdString(symbol.commands),{
    fill:symbol.color,stroke:"#122438",width:.55
   });
   shape.setAttribute("class","sat-front-symbol");
   shape.setAttribute("data-front-type",feature.type);
   svg.appendChild(shape);
  }
 }
 svg.removeAttribute("hidden");
 msg.textContent=visible.length+" echte NOAA-WPC-Frontlinien · ruhige synoptische Symbolik."+
  " Frontseiten schematisch (Bewegungsrichtung im Bulletin nicht codiert)."+
  " Analysezeit und Herkunft siehe unten.";
}
async function refresh(){
 if(window.SatelliteFrontsPaused===true){info=null;render();return;}
 lastStatus="";msg.textContent="Lade aktuelle NOAA-WPC-Frontpositionen …";
 const ctrl=typeof AbortController==="function"?new AbortController():null;
 const timer=ctrl?setTimeout(()=>ctrl.abort(),10000):null;
 try{
  const res=await fetch(INPUT+"?v="+Date.now(),
   ctrl?{cache:"no-store",signal:ctrl.signal}:{cache:"no-store"});
  if(!res.ok)throw Error("HTTP "+res.status);
  const data=await res.json();
  info=validate(data);
  lastStatus=info?"":"NOAA WPC: Keine aktuelle, bestätigte Koordinatenanalyse ("+
   (data.error||data.status||"fehlende Quelle")+"). "+
   "Es wird kein alter oder künstlich positionierter Frontenverlauf gezeichnet.";
  render();
 }catch(error){
  info=null;
  lastStatus="NOAA WPC: Datenstatus nicht erreichbar ("+String(error.message||error)+").";
  render();
 }finally{if(timer!==null)clearTimeout(timer);}
}
region.addEventListener("change",()=>sync({time:context.time}));
source.addEventListener("change",()=>sync({time:context.time}));
toggle.addEventListener("change",render);
link.href=TRUSTED;
link.rel="noopener noreferrer";link.target="_blank";
window.SatelliteNOAAFronts={sync,validate,project,exportAt,visibleFor,COLORS};
if(window.SatelliteFrontsPaused===true)render();
else void refresh();
})();