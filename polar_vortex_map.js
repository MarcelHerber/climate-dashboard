/* Single ERA5 10-hPa north-polar map. Only validated daily reanalysis. */
(()=>{"use strict";
const $=id=>document.getElementById(id);
const BASE="data/polar_vortex/";
const dateDE=s=>/^\d{4}-\d\d-\d\d$/.test(s||"")?s.slice(8,10)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
let imageUrl="",latestData=null;
async function reload(){
 const status=$("polarVortexStatus"),image=$("polarVortexImage"),button=$("polarVortexDownload");
 status.textContent="Lade verifizierte ERA5-Analyse …";
 button.disabled=true;image.hidden=true;imageUrl="";
 try{
  const res=await fetch(BASE+"current.json?v="+Date.now(),{cache:"no-store"});
  if(!res.ok)throw Error("Kartendaten noch nicht veröffentlicht (HTTP "+res.status+")");
  const data=await res.json();
  if(data.schema_version!==1||data.ready!==true||data.forecast!==false||
     !/^\d{4}-\d\d-\d\d$/.test(data.analysis_date||"")||data.pressure_hpa!==10||
     data.parameter!=="geopotential_height"||data.image!=="polar_vortex_10hpa_current.png")
    throw Error("Kartenmetadaten unvollständig oder ungültig");
  if(Date.parse(data.analysis_date+"T00:00:00Z")>Date.now())throw Error("Ungültiges Zukunftsdatum");
  const url=BASE+"polar_vortex_10hpa_current.png?v="+encodeURIComponent(data.analysis_date);
  await new Promise((resolve,reject)=>{
   image.onload=resolve;
   image.onerror=()=>reject(Error("Kartenbild nicht verfügbar"));
   image.src=url;
  });
  const lag=Math.floor((Date.now()-Date.parse(data.analysis_date+"T00:00:00Z"))/86400000);
  image.hidden=false;imageUrl=url;latestData=data;button.disabled=false;
  $("polarVortexDate").textContent=dateDE(data.analysis_date)+" · Tagesmittel 00–24 UTC";
  $("polarVortexRange").textContent="10 hPa · "+data.region+" · "+data.min_gpm.toLocaleString("de-DE")+"–"+data.max_gpm.toLocaleString("de-DE")+" gpm";
  status.textContent="ERA5-Reanalyse vom "+dateDE(data.analysis_date)+
    " · "+(lag<=10?"Analyse verfügbar":"Archivstand "+lag+" Tage zurück")+
    " · Quelle: Copernicus C3S / ECMWF. Keine Prognose.";
 }catch(err){
  latestData=null;image.hidden=true;button.disabled=true;
  $("polarVortexDate").textContent="Noch keine verifizierte Karte";
  $("polarVortexRange").textContent="10 hPa · Nordhemisphäre";
  status.textContent=err.message+". Die übrige Stratosphärenseite bleibt unabhängig nutzbar.";
 }
}
function savePNG(){
 if(!imageUrl||!latestData)return;
 const a=document.createElement("a");
 a.href=imageUrl;
 a.download="Polarwirbel_ERA5_10hPa_"+latestData.analysis_date+".png";
 document.body.append(a);a.click();a.remove();
}
function mount(){
 if(!$("polarVortexCard"))return;
 $("polarVortexReload").addEventListener("click",reload);
 $("polarVortexDownload").addEventListener("click",savePNG);
 reload();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);
else mount();
})();