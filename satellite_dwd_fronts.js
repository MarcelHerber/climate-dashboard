/* Georeferenced DWD manual front LINES directly on EUMETSAT EPSG:4326.
 * The original DWD bitmap has NO trusted geotransform, and is NEVER placed
 * over the satellite. Unverified/inaccessible NinJo GML => explicit no data.
 * Existing ECMWF IFS isobars are independent and remain over the Satbild.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const toggle=$("satShowDwdFronts"),svg=$("satDwdFrontSvg");
const status=$("satDwdFrontStatus"),utcLabel=$("satDwdFrontUTC");
const sourceLink=$("satDwdFrontSource"),refresh=$("satDwdFrontRefresh");
const source=$("satSource"),region=$("satRegion");
if(!toggle||!svg||!status||!utcLabel||!sourceLink||!refresh||!source||!region)return;
const SOURCE="https://opendata.dwd.de/weather/charts/analysis/";
const INDEX="./data/synoptic_charts/dwd_fronts_satellite.json";
const GEO="./data/synoptic_charts/dwd_fronts_geo.json";
const NS="http://www.w3.org/2000/svg";
const BBOX={
 europe:[-27,24,49,73],atlantic:[-70,15,35,75],
 southwest:[-37,24,19,53],central:[-2,43,25,58],
 germany:[5,47,16,56]
};
const COLOR={cold:"#47a5fa",warm:"#ff6464",occluded:"#cc74f4",stationary:"#ed719b"};
let context={time:null,source:source.value,region:region.value};
let frontData=null,official=null,seq=0,loading=false;
function fmt(date){
 const d=new Date(date);
 return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{
  timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",
  hour:"2-digit",minute:"2-digit",hourCycle:"h23"
 }).format(d)+" UTC":"Zeitpunkt unbekannt";
}
function parseUTC(text){
 if(typeof text!=="string"||!/\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:\.\d+)?Z$/.test(text))return null;
 const n=Date.parse(text);return Number.isFinite(n)?n:null;
}
function dwdURL(value){
 try{
  const u=new URL(value);
  return u.protocol==="https:"&&u.hostname==="opendata.dwd.de"&&
   u.pathname.startsWith("/weather/charts/analysis/")&&!u.search&&!u.hash;
 }catch(_){return false;}
}
function verifiedGmlURL(value){
 try{
  const u=new URL(value);
  return u.protocol==="https:"&&
   (u.hostname==="opendata.dwd.de"||u.hostname==="maps.dwd.de")&&
   /\\.(?:gml|xml)$/i.test(u.pathname)&&!u.hash;
 }catch(_){return false;}
}
function clean(){
 svg.replaceChildren();
 svg.setAttribute("hidden","");
}
function message(text){
 status.textContent=text;
}
function geographic(){
 return context.source==="mtgi1"&&Boolean(BBOX[context.region]);
}
function validate(json){
 if(!json||json.schema_version!==1||json.status!=="verified"||
    json.provider!=="DWD"||json.kind!=="analysis"||
    json.coordinate_reference_system!=="EPSG:4326"||
    json.georeferencing_verified!==true||
    json.front_source_format!=="NinJo-GML"||
    !verifiedGmlURL(json.source_url)||parseUTC(json.valid_utc)===null||
    !Array.isArray(json.features)||json.features.length<1||json.features.length>700)return null;
 const age=Date.now()-parseUTC(json.valid_utc);
 if(age < -15*60000||age>30*3600000)return null;
 let total=0,valid=[];
 for(const f of json.features){
  const p=f?.properties||{},g=f?.geometry;
  if(f?.type!=="Feature"||g?.type!=="LineString"||
     !(p.front_type in COLOR)||!Array.isArray(g.coordinates)||
     g.coordinates.length<2||g.coordinates.length>3000)return null;
  total+=g.coordinates.length;
  if(total>60000)return null;
  const coordinates=[];
  for(const point of g.coordinates){
   if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite)||
      point[0]<-180||point[0]>180||point[1]<-90||point[1]>90)return null;
   coordinates.push(point);
  }
  valid.push({type:p.front_type,coordinates});
 }
 return {...json,features:valid};
}
function project(point,bbox){
 return [(point[0]-bbox[0])*1000/(bbox[2]-bbox[0]),
         (bbox[3]-point[1])*1000/(bbox[3]-bbox[1])];
}
function update(){
 clean();
 if(!geographic()){
  toggle.disabled=true;
  message("DWD-Analysefronten sind auf der Vollscheibe und bei MTG-I2 nicht geografisch darstellbar.");
  return;
 }
 if(!frontData){
  toggle.disabled=true;
  message("DWD-Frontlinien: Noch keine öffentlich zugänglichen, geografisch verifizierten NinJo-/GML-Daten. "+
   "Die ECMWF-Isobaren sind bereits direkt auf dem Satellitenbild verfügbar.");
  utcLabel.textContent=official?.maps?.atlantic?.valid_utc?
   "Letzte DWD-Originalanalyse: "+fmt(official.maps.atlantic.valid_utc):"";
  return;
 }
 toggle.disabled=false;
 const frame=parseUTC(context.time),valid=parseUTC(frontData.valid_utc);
 const lag=frame!==null?((frame-valid)/3600000):null;
 const delay=lag===null?"Satelliten-UTC nicht bestätigt":
  (lag>=0?"+":"")+lag.toFixed(1).replace(".",",")+" h gegenüber dem Satellitenbild";
 utcLabel.textContent="DWD-Fronten "+fmt(frontData.valid_utc)+" · "+delay;
 if(!toggle.checked){
  message("DWD-Analysefronten ausgeschaltet. Die ECMWF-Isobaren bleiben unabhängig sichtbar.");
  return;
 }
 if(frame===null){
  message("Keine überprüfte Satelliten-UTC – DWD-Fronten werden nicht als synchron ausgegeben.");
  return;
 }
 if(Math.abs(lag)>18){
  message("DWD-Analyse und Satellitenbild liegen "+Math.abs(lag).toFixed(1)+
   " Stunden auseinander. Fronten nicht eingeblendet.");
  return;
 }
 const bbox=BBOX[context.region];
 let count=0;
 for(const f of frontData.features){
  const arr=f.coordinates;
  // Project all points from DWD's verified WGS84 coordinates into the exact
  // EUMETSAT WMS 1.1.1 bbox; no screen/image-pixel alignment.
  const d=arr.map((point,i)=>{
   const [x,y]=project(point,bbox);
   return (i?"L":"M")+x.toFixed(2)+" "+y.toFixed(2);
  }).join(" ");
  const path=document.createElementNS(NS,"path");
  path.setAttribute("d",d);
  path.setAttribute("fill","none");
  path.setAttribute("stroke",COLOR[f.type]);
  path.setAttribute("stroke-width","2.3");
  path.setAttribute("vector-effect","non-scaling-stroke");
  path.setAttribute("stroke-linejoin","round");
  path.setAttribute("stroke-linecap","round");
  svg.appendChild(path);count++;
 }
 if(count){
  svg.removeAttribute("hidden");
  message(count+" georeferenzierte DWD-Analysefronten direkt im Satellitenbild · "+
   "Gültigkeit "+fmt(frontData.valid_utc)+". Isobaren: ECMWF IFS, eigene Zeitprüfung. "+
   "Frontsymbole werden ohne nachgewiesene Ausrichtungsinformation nicht erfunden.");
 }
}
async function load(){
 if(loading)return;
 loading=true;seq++;const mine=seq;
 refresh.disabled=true;
 message("Prüfe amtliche DWD-Daten und geografische Frontlinien …");
 const controller=typeof AbortController==="function"?new AbortController():null;
 const timer=controller?setTimeout(()=>controller.abort(),8500):null;
 try{
  const fetchJSON=async url=>{
   const response=await fetch(url+"?t="+Date.now(),controller?{
    cache:"no-store",signal:controller.signal}:{cache:"no-store"});
   if(!response.ok)throw Error("HTTP "+response.status);
   return response.json();
  };
  official=await fetchJSON(INDEX);
  if(mine!==seq)return;
  const dwdMap=official?.maps?.atlantic;
  if(dwdMap?.source_url&&dwdURL(dwdMap.source_url))
   sourceLink.href=dwdMap.source_url;
  else sourceLink.href=SOURCE;
  // A published PNG by itself is NEVER accepted as a georeferenced front.
  // Only a verified NinJo GML conversion may populate this overlay.
  try{frontData=validate(await fetchJSON(GEO));}
  catch(_){frontData=null;}
  if(mine===seq)update();
 }catch(err){
  if(mine!==seq)return;
  frontData=null;clean();toggle.disabled=true;
  sourceLink.href=SOURCE;
  message("DWD-Frontendaten derzeit nicht verfügbar ("+(err?.message||String(err))+
   "). Die korrekt positionierten ECMWF-Isobaren bleiben über dem Satellitenbild.");
 }finally{
  if(timer!==null)clearTimeout(timer);
  if(mine===seq){loading=false;refresh.disabled=false;}
 }
}
function sync(next){
 context={time:next?.time||null,region:next?.region||region.value,
          source:next?.source||source.value};
 update();
}
toggle.addEventListener("change",update);
refresh.addEventListener("click",()=>void load());
region.addEventListener("change",()=>sync({time:context.time}));
source.addEventListener("change",()=>sync({time:context.time}));
window.SatelliteFrontAnalysis={sync,project,validate};
void load();
})();