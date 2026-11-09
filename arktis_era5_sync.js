/* DMI day selection <-> verified ERA5 archive, mobile gestures and paired maps. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const dateLabel=s=>/^\d{4}-\d{2}-\d{2}$/.test(s||"")?s.slice(8)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
const fmt=x=>Number.isFinite(x)?x.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const signed=x=>Number.isFinite(x)?(x>0?"+":"")+fmt(x):"–";
const api=()=>window.ArcticEra5Archive;
let enabled=false,comparisonDate="",pendingDmiDate="",lastSelection="";
const ids=["arcticEra5CompareATemp","arcticEra5CompareAAnomaly","arcticEra5CompareBTemp","arcticEra5CompareBAnomaly"];

function message(text,isError=false){
 const el=$("arcticEra5SyncStatus");
 if(!el)return;
 el.textContent=text;el.classList.toggle("error",isError);
}
function primaryDate(){return api()?.getState()?.date||"";}
function region(){return api()?.getState()?.region||"80";}
function dates(){return api()?.getDates?.()||[];}
function detail(iso){return api()?.getRow?.(iso)?.regions?.[region()]||null;}

function resetSelect(){
 const options=dates(),selector=$("arcticEra5CompareDate");
 if(!selector)return;
 // Rebuild only when the archive or chosen region actually changes.
 const old=Array.from(selector.options).map(o=>o.value);
 if(old.join("|")!==options.join("|")){
  selector.replaceChildren();
  options.forEach(d=>{
   const opt=document.createElement("option");opt.value=d;opt.textContent=dateLabel(d);
   selector.append(opt);
  });
 }
 if(!options.includes(comparisonDate)){
  comparisonDate=options.find(d=>d!==primaryDate())||options[0]||"";
 }
 selector.value=comparisonDate;
 selector.disabled=!enabled||options.length<2;
 $("arcticEra5CompareSwap").disabled=!enabled||options.length<2;
}
function setPair(side,date){
 const data=detail(date),title=$("arcticEra5Compare"+side+"Title");
 const stats=$("arcticEra5Compare"+side+"Metrics");
 if(!data){
  title.textContent="Tag "+side+" · keine geprüften Karten";
  stats.textContent="Für diesen Tag gibt es in der gewählten Region noch keine ERA5-Karten.";
  return false;
 }
 title.textContent="Tag "+side+" · "+dateLabel(date);
 stats.textContent="Flächenmittel "+fmt(data.mean_c)+" °C · Abweichung vom Monatsmittel "+
   signed(data.mean_anomaly_k)+" K";
 for(const [suffix,key,label] of [
  ["Temp","temperature_png","Temperatur"],
  ["Anomaly","anomaly_png","Monatsanomalie"]
 ]){
  const image=$("arcticEra5Compare"+side+suffix);
  const a=$("arcticEra5Compare"+side+suffix+"Png");
  const source=data[key],valid=api()?.validFile?.(source);
  if(!valid){
   image.removeAttribute("src");a.removeAttribute("href");a.removeAttribute("download");
   continue;
  }
  const v=data.boundary_version||3;
  const url="data/arctic_era5_maps/"+source+"?map=b"+v;
  image.loading="eager";
  if(image.getAttribute("src")!==url)image.src=url;
  image.alt="ERA5 "+label+" · "+region()+"–90°N · "+dateLabel(date)+" · feste Farbskala und Küstenlinien";
  a.href=url;
  a.download="ERA5_Arktis_"+region()+"-90N_"+label+"_"+date+".png";
 }
 return true;
}
function updatePdfAvailability(){
 const button=$("arcticEra5ComparePdf");
 if(!button)return;
 button.disabled=!enabled||!ids.every(id=>{
  const image=$(id);
  return image?.hasAttribute("src")&&image.complete&&image.naturalWidth>=800;
 });
}
function updateComparison(){
 const available=dates();
 if(enabled&&available.length<2){
  enabled=false;$("arcticEra5CompareEnabled").checked=false;
  message("Für einen Zwei-Tage-Vergleich müssen mindestens zwei geprüfte ERA5-Tage vorliegen.",true);
 }
 resetSelect();
 const comp=$("arcticEra5CompareGrid");
 const primary=$("arcticEra5Maps");
 primary.hidden=enabled;comp.hidden=!enabled;
 $("arcticEra5PrimaryDownloads").hidden=enabled;
 $("arcticEra5CompareDownloads").hidden=!enabled;
 $("arcticEra5CompareSummary").hidden=!enabled;
 if(!enabled){updatePdfAvailability();return;}
 const aDate=primaryDate();
 if(!available.includes(aDate)||!available.includes(comparisonDate)){
  $("arcticEra5CompareSummary").textContent="Mindestens eine Karte ist für die gewählte Region nicht verfügbar.";
  $("arcticEra5ComparePdf").disabled=true;
  return;
 }
 const a=setPair("A",aDate),b=setPair("B",comparisonDate);
 const left=detail(aDate),right=detail(comparisonDate);
 if(a&&b){
  $("arcticEra5CompareSummary").textContent="Tag B minus Tag A · Temperatur-Kappenmittel: "+
   signed(right.mean_c-left.mean_c)+" K · Anomalie-Kappenmittel: "+
   signed(right.mean_anomaly_k-left.mean_anomaly_k)+
   " K. Identische ERA5-Farbskalen für beide Tage; Monatsanomalien sind nicht mit den tagesbezogenen DMI-Anomalien gleichzusetzen.";
 }
 applyMode();updatePdfAvailability();
}
function applyMode(){
 const mode=$("arcticEra5MapMode").value;
 for(const card of $("arcticEra5CompareGrid").querySelectorAll("[data-era5-kind]")){
  card.hidden=mode!=="both"&&card.dataset.era5Kind!==mode;
 }
}
function onDmiSelected(e){
 const date=e.detail?.date,source=e.detail?.source;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date||"")||source==="era5")return;
 lastSelection=date;
 const viewer=api(),state=viewer?.getState?.();
 if(!state?.ready){pendingDmiDate=date;message("ERA5-Archiv lädt. DMI-Tag "+dateLabel(date)+" ist vorgemerkt.");return;}
 if(!viewer.selectDate(date,"dmi")){
  message("DMI-Tag "+dateLabel(date)+": noch keine geprüfte ERA5-Karte. Angezeigt bleibt der ausdrücklich gewählte ERA5-Tag "+dateLabel(primaryDate())+".",true);
  return;
 }
 pendingDmiDate="";
 message("Synchronisiert: DMI-Tag und ERA5-Karten "+dateLabel(date)+
  " · ERA5-Monatsklima 1991–2020, DMI-Tagesklima 1958–2002.");
 const panel=$("arcticEra5MapPanel");panel.open=true;
 panel.scrollIntoView({behavior:"smooth",block:"start"});
}
function onMapSelected(e){
 const date=e.detail?.date,source=e.detail?.source;
 updateComparison();
 if(source!=="user"&&source!=="touch"&&source!=="keyboard")return;
 if(window.Arctic80NavigateToDate?.(date,"era5")){
  lastSelection=date;
  message("Gemeinsames Datum: "+dateLabel(date)+
   " · DMI-Diagramme und ERA5-Karten aktualisiert (unterschiedliche Klimareferenzen).");
 }else{
  message("ERA5 "+dateLabel(date)+" ist ausgewählt; für diesen Tag ist keine passende DMI-Tagesreihe geladen.",true);
 }
}
function onReady(){
 resetSelect();updateComparison();
 if(pendingDmiDate){
  const date=pendingDmiDate;pendingDmiDate="";
  onDmiSelected({detail:{date,source:"dmi"}});
 }else message("ERA5-Karten verfügbar. Klick auf einen DMI-Tag oder navigiere im Kartenausschnitt mit Pfeiltasten bzw. Wischgesten.");
}
function navigate(step,source){
 if(!api()?.navigate?.(step,source)){
  message("Am Anfang oder Ende der bereits geprüften ERA5-Kartentage angekommen.");
 }
}
function bindNavigation(id){
 const surface=$(id);let start=null;
 surface.addEventListener("touchstart",event=>{
  if(event.touches.length!==1||event.target.closest("a,button,input,select")){start=null;return;}
  const t=event.touches[0];start={x:t.clientX,y:t.clientY};
 },{passive:true});
 surface.addEventListener("touchend",event=>{
  if(!start||event.changedTouches.length!==1)return;
  const t=event.changedTouches[0],dx=t.clientX-start.x,dy=t.clientY-start.y;
  start=null;
  if(Math.abs(dx)>=65&&Math.abs(dx)>1.4*Math.abs(dy)){
   navigate(dx<0?1:-1,"touch");
  }
 },{passive:true});
 surface.addEventListener("touchcancel",()=>start=null,{passive:true});
 surface.addEventListener("keydown",event=>{
  if(event.target!==surface||!["ArrowLeft","ArrowRight"].includes(event.key))return;
  event.preventDefault();navigate(event.key==="ArrowLeft"?1:-1,"keyboard");
 });
}
async function comparePdf(){
 if($("arcticEra5ComparePdf").disabled)return;
 const Pdf=window.jspdf?.jsPDF;
 if(!Pdf){message("PDF-Bibliothek nicht verfügbar; die einzelnen PNG-Exporte bleiben nutzbar.",true);return;}
 const left=primaryDate(),right=comparisonDate;
 try{
  const pdf=new Pdf({orientation:"portrait",format:"a4",unit:"mm"});
  for(let i=0;i<ids.length;i++){
   const image=$(ids[i]);
   if(!image.complete||image.naturalWidth<800)throw Error("Vergleichskarte noch nicht vollständig geladen");
   if(i)pdf.addPage();
   const ratio=Math.min(184/image.naturalWidth,257/image.naturalHeight);
   const width=image.naturalWidth*ratio,height=image.naturalHeight*ratio;
   const canvas=document.createElement("canvas");
   canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
   canvas.getContext("2d").drawImage(image,0,0);
   pdf.addImage(canvas.toDataURL("image/png"),"PNG",(210-width)/2,12,width,height);
   pdf.setFontSize(8);pdf.setTextColor(50,67,83);
   pdf.text("ERA5 "+region()+"–90°N · "+(i<2?left:right)+" · "+
    (i%2===0?"Temperatur":"Monatsanomalie")+
    " · 1991–2020 · Copernicus C3S / ECMWF",12,289);
  }
  pdf.save("ERA5_Arktis_Vergleich_"+left+"_vs_"+right+"_"+region()+"N.pdf");
 }catch(error){message("Vergleichs-PDF konnte nicht erstellt werden: "+error.message,true);}
}
function init(){
 if(!$("arcticEra5CompareEnabled")||!$("arcticEra5Maps"))return;
 $("arcticEra5CompareEnabled").addEventListener("change",e=>{
  enabled=e.target.checked;updateComparison();
 });
 $("arcticEra5CompareDate").addEventListener("change",e=>{
  comparisonDate=e.target.value;updateComparison();
 });
 $("arcticEra5CompareSwap").addEventListener("click",()=>{
  const old=primaryDate(),newDate=comparisonDate;
  if(!old||!newDate)return;
  comparisonDate=old;
  if(!api()?.selectDate?.(newDate,"user"))comparisonDate=newDate;
  updateComparison();
 });
 $("arcticEra5MapMode").addEventListener("change",applyMode);
 $("arcticEra5ComparePdf").addEventListener("click",comparePdf);
 for(const id of ids){
  $(id).addEventListener("load",updatePdfAvailability);
  $(id).addEventListener("error",()=>{
   $("arcticEra5ComparePdf").disabled=true;
   message("Eine der ERA5-Vergleichskarten ist nicht ladbar. Bitte Archiv prüfen.",true);
  });
 }
 bindNavigation("arcticEra5Maps");
 bindNavigation("arcticEra5CompareGrid");
 window.addEventListener("arctic80:day-selected",onDmiSelected);
 window.addEventListener("arctic-era5:date-change",onMapSelected);
 window.addEventListener("arctic-era5:ready",onReady);
 if(api()?.getState?.().ready)onReady();
}
window.ArcticEra5Sync={
 getState:()=>({ready:!!api()?.getState?.().ready,enabled,primaryDate:primaryDate(),
  comparisonDate,lastDmiDate:lastSelection,availableDays:dates().length}),
 navigate
};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();