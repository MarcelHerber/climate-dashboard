/* Official DWD manual surface FRONT ANALYSIS (not an ICON forecast).
 * Source PNGs remain unchanged on opendata.dwd.de. No fraudulent geographic
 * overlay: DWD's paper map projection is separate from the EPSG:4326 WMS.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const region=$("satFrontRegion"),status=$("satFrontStatus"),image=$("satFrontImage");
const open=$("satFrontOpen"),origin=$("satFrontSource"),valid=$("satFrontValid");
const note=$("satFrontMeta"),refresh=$("satFrontRefresh");
if(!region||!status||!image||!open||!origin||!valid||!note||!refresh)return;

const INDEX="https://opendata.dwd.de/weather/charts/analysis/";
const REPORT="data/synoptic_charts/dwd_fronts_satellite.json";
const MAX_AGE_H=42,FRESH_H=18;
let report=null,request=0,activeURL="";

function formatUTC(value){
 const parsed=new Date(value);
 return Number.isFinite(parsed.getTime())?
  new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",hourCycle:"h23",
   day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",
   minute:"2-digit"}).format(parsed)+" UTC":"nicht verifiziert";
}
function asUTC(value){
 if(typeof value!=="string"||!/(?:Z|\+00:00)$/.test(value))return null;
 const parsed=new Date(value);
 return Number.isFinite(parsed.getTime())?parsed:null;
}
function sourceIsOfficial(value,where){
 try{
  const url=new URL(value);
  if(url.protocol!=="https:"||url.hostname!=="opendata.dwd.de"||
   !url.pathname.startsWith("/weather/charts/analysis/")||url.search||url.hash)
   return false;
  const name=decodeURIComponent(url.pathname.split("/").pop());
  const found=name.match(/^Z__C_EDZW_(\d{14})_tka01,ana_bwkman_(dwdna|dwdc)_O_000000_000000_(\d{12})_WV12SW\.png$/i);
  if(!found)return false;
  const which=where==="central"?"dwdc":"dwdna";
  if(found[2].toLowerCase()!==which)return false;
  const validName=found[3].replace(/^(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)$/,"$1-$2-$3T$4:$5:00Z");
  return Number.isFinite(Date.parse(validName))&&validName.slice(0,16)===String(report?.maps?.[where]?.valid_utc||"").slice(0,16);
 }catch(_){return false;}
}
function empty(message){
 image.hidden=true;image.removeAttribute("src");open.removeAttribute("href");
 open.hidden=true;activeURL="";valid.textContent="Gültigkeit: unbekannt";
 note.textContent="";status.textContent=message;
}
function render(){
 const which=region.value==="central"?"central":"atlantic";
 const selected=report?.maps?.[which];
 if(!selected?.image_verified||selected.kind!=="analysis"||
    !asUTC(selected.valid_utc)||!sourceIsOfficial(selected.source_url,which)){
  empty("Keine verifizierte aktuelle DWD-Originalanalyse für "+(which==="central"?"Mitteleuropa":"Nordatlantik/Europa")+
   ". Die amtliche Quelle kann jederzeit über den Link geöffnet werden.");
  return;
 }
 const age=(Date.now()-asUTC(selected.valid_utc).getTime())/3600000;
 if(age < -1||age>MAX_AGE_H){
  empty("Die letzte geprüfte DWD-Karte ist älter als 42 Stunden; sie wird nicht als aktuelle Frontenanalyse angezeigt.");
  return;
 }
 const freshness=age<=FRESH_H&&selected.fresh===true&&selected.previously_verified!==true;
 const reportTime=asUTC(report.generated_at);
 const reportAge=reportTime?(Date.now()-reportTime.getTime())/3600000:Infinity;
 const warning=(!freshness?"Ältere Analyse – nicht als aktuelle Frontenlage verwenden. ":"")+
  (reportAge>5?"Der Aktualisierungsbericht ist verzögert. ":"");
 valid.textContent="Gültig: "+formatUTC(selected.valid_utc);
 note.textContent="Analyse, keine Prognose · veröffentlicht "+formatUTC(selected.published_utc)+
  " · Stand der Quellenprüfung "+formatUTC(report.generated_at)+
  " · "+Math.max(0,age).toFixed(1).replace(".",",")+" Stunden seit Kartengültigkeit";
 open.href=selected.source_url;
 open.hidden=false;
 image.alt="Unveränderte amtliche DWD-Bodenanalyse mit Kalt-, Warm- und Okklusionsfronten für "+
  (which==="central"?"Mitteleuropa":"Nordatlantik und Europa")+
  ", Gültigkeit "+formatUTC(selected.valid_utc);
 status.textContent=(warning||"DWD-Originalkarte verifiziert. ")+
  "Bild wird direkt vom Deutschen Wetterdienst geladen …";
 if(activeURL!==selected.source_url){
  // A hidden lazy-loaded <img> may never trigger onload. Make it eligible
  // for viewport-based loading while the status still says "loading".
  image.hidden=false;activeURL=selected.source_url;const desired=activeURL;
  image.onload=()=>{
   if(activeURL===desired){
    image.hidden=false;
    status.textContent=warning||"DWD-Originalkarte geladen · Frontenanalyse, keine Prognose.";
   }
  };
  image.onerror=()=>{
   if(activeURL===desired){
    image.hidden=true;
    status.textContent="DWD-Bild momentan nicht erreichbar. Über „Original-PNG öffnen“ direkt beim DWD prüfen.";
   }
  };
  image.src=selected.source_url;
 }else if(image.complete&&image.naturalWidth>0){
  image.hidden=false;
  status.textContent=warning||"DWD-Originalkarte geladen · Frontenanalyse, keine Prognose.";
 }
}
async function load(){
 const run=++request;
 refresh.disabled=true;
 status.textContent="Prüfe amtliche DWD-Frontenanalyse und UTC-Gültigkeit …";
 const controller=typeof AbortController==="function"?new AbortController():null;
 const timer=controller?setTimeout(()=>controller.abort(),10000):null;
 try{
  const response=await fetch(REPORT+"?t="+Date.now(),
   controller?{cache:"no-store",signal:controller.signal}:{cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const data=await response.json();
  if(run!==request)return;
  if(data.schema_version!==1||data.kind!=="analysis"||!data.maps||
     !String(data.source_page||"").startsWith(INDEX))
    throw Error("unzulässige oder unvollständige Quellen-Metadaten");
  report=data;
  render();
 }catch(err){
  if(run!==request)return;
  if(report){render();status.textContent="DWD-Aktualisierung fehlgeschlagen ("+
    (err?.message||String(err))+"). Vorheriger geprüfter Stand; nicht als neu interpretieren.";}
  else empty("DWD-Quellenstatus derzeit nicht erreichbar ("+(err?.message||String(err))+
   "). Amtliches Analyseverzeichnis öffnen.");
 }finally{
  if(timer!==null)clearTimeout(timer);
  if(run===request)refresh.disabled=false;
 }
}
region.addEventListener("change",render);
refresh.addEventListener("click",load);
origin.href=INDEX;
origin.rel="noopener noreferrer";
origin.target="_blank";
load();
window.SatelliteFrontAnalysis={formatUTC,sourceIsOfficial};
})();