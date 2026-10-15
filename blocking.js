(()=>{"use strict";
const $=id=>document.getElementById(id),ROOT="data/blocking/";
let published=null;
const de=s=>/^\d{4}-\d{2}-\d{2}$/.test(s||"")?s.slice(8,10)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
const lon=n=>n===0?"0°":Math.abs(n)+"° "+(n<0?"W":"E");
function sectors(container,items,missingText){
 container.replaceChildren();
 if(!items?.length){container.textContent=missingText;return;}
 for(const x of items){
  const n=document.createElement("span");n.className="sector";
  n.textContent=lon(x.west)+" bis "+lon(x.east)+" · "+x.width_degrees+"°";
  container.append(n);
 }
}
async function refresh(){
 const status=$("blockStatus"),pic=$("blockImage"),button=$("blockDownload");
 status.textContent="Prüfe veröffentlichte ERA5-Kartendaten …";
 $("blockMissing").hidden=false;pic.hidden=true;button.disabled=true;published=null;
 try{
  const r=await fetch(ROOT+"current.json?t="+Date.now(),{cache:"no-store"});
  if(!r.ok)throw Error("Noch keine erfolgreich veröffentlichte ERA5-Analyse (HTTP "+r.status+")");
  const meta=await r.json();
  if(meta.schema_version!==1||meta.ready!==true||meta.forecast!==false||meta.pressure_hpa!==500||
     meta.image!=="blocking_z500_current.png"||!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(meta.analysis_date||"")||
     !Array.isArray(meta.instantaneous_sectors)||!Array.isArray(meta.persistent_sectors)||
     meta.history_complete!==true || meta.days_analysed<5)throw Error("Blocking-Metadaten nicht vollständig");
  if(Date.parse(meta.analysis_date+"T00:00:00Z")>Date.now())throw Error("Ungültiges Analysedatum");
  const image=ROOT+meta.image+"?date="+meta.analysis_date;
  await new Promise((ok,fail)=>{pic.onload=ok;pic.onerror=()=>fail(Error("PNG-Karte ist noch nicht über Pages erreichbar"));pic.src=image;});
  published=meta;pic.hidden=false;$("blockMissing").hidden=true;button.disabled=false;
  const n=meta.instantaneous_sectors.length,p=meta.persistent_sectors.length;
  $("blockDate").textContent=de(meta.analysis_date);
  $("blockSpan").textContent=de(meta.dates_used?.[0])+" – "+de(meta.analysis_date);
  $("blockInstant").textContent=String(n);
  $("blockPersistent").textContent=String(p);
  sectors($("blockInstantSectors"),meta.instantaneous_sectors,"Keine Gradienten-Umkehr in einem Sektor ≥10° erkannt.");
  sectors($("blockPersistSectors"),meta.persistent_sectors,"Kein mindestens fünf Tage anhaltendes TM-Signal in einem Sektor ≥10° erkannt.");
  const lag=Math.floor((Date.now()-Date.parse(meta.analysis_date+"T00:00:00Z"))/86400000);
  status.textContent="ERA5-Tagesanalyse vom "+de(meta.analysis_date)+
   " · Stand "+lag+" Tage zurück · 500 hPa · 1°-Raster · Beobachtungsbasierte Reanalyse, keine Vorhersage.";
  $("blockSummary").textContent=p?
   "An "+p+" Längengradsektor"+(p===1?"":"en")+" liegt ein über mindestens fünf aufeinanderfolgende Tage bestätigtes TM-Gradientensignal vor.":
   n?"Es liegt eine momentane Gradienten-Umkehr vor, aber kein fünftägig bestätigter Sektor.":
   "An diesem Analysedatum wurde in der betrachteten Region kein TM-Gradientensignal oberhalb der gewählten Sektorbreite nachgewiesen.";
 }catch(err){
  status.textContent="Karte derzeit nicht verfügbar: "+err.message;
  $("blockSummary").textContent="Noch kein überprüfbarer Datenstand. Ein grüner Workflow-Status wird hier nicht ohne veröffentlichte Tagesfelder angenommen.";
  for(const id of ["blockDate","blockSpan","blockInstant","blockPersistent"])$(id).textContent="–";
  $("blockInstantSectors").textContent="Noch keine Daten veröffentlicht.";
  $("blockPersistSectors").textContent="Noch keine Daten veröffentlicht.";
 }
}
function download(){
 if(!published)return;
 const a=document.createElement("a");a.href=ROOT+"blocking_z500_current.png?date="+published.analysis_date;
 a.download="Blocking_ERA5_Z500_"+published.analysis_date+".png";
 document.body.append(a);a.click();a.remove();
}
function init(){
 $("blockReload").addEventListener("click",refresh);
 $("blockDownload").addEventListener("click",download);
 refresh();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();