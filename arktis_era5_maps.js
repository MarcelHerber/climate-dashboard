/* Copernicus ERA5 Arctic 30-day archive, 60/70/80N real-data maps. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const BASE="data/arctic_era5_maps/";
const REGIONS=["80","70","60"];
let archive=null,days=[],position=0;
const validFile=p=>/^maps\/(?:t2m|anomaly)_(?:(?:60|70|80)n_)?[0-9]{8}\.png$/.test(p);
const dateLabel=s=>s&&/^\d{4}-\d{2}-\d{2}$/.test(s)?s.slice(8)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
const number=x=>Number.isFinite(x)?x.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const signed=x=>Number.isFinite(x)?(x>0?"+":"")+number(x):"–";
const region=()=>$("arcticEra5MapRegion").value;
const regionLabel=()=>region()+"–90°N";
function status(text,error=false){
 const el=$("arcticEra5MapStatus");el.textContent=text;el.classList.toggle("error",error);
}
function fileURL(name,version){
 return BASE+name+(version?"?map=b"+version:"");
}
function link(id,filename,date,kind,version){
 const a=$(id);
 if(!validFile(filename)){a.removeAttribute("href");a.removeAttribute("download");return;}
 a.href=fileURL(filename,version);
 a.download="ERA5_Arktis_"+region()+"-90N_"+kind+"_"+date+".png";
}
function normalize(data){
 if(data?.ready!==true||![1,2].includes(data.schema)||!Array.isArray(data.days))return null;
 const normalized=[];
 const used=new Set();
 for(const row of data.days){
   if(!/^\d{4}-\d{2}-\d{2}$/.test(row.date||"")||used.has(row.date))continue;
   const regions={};
   if(data.schema===2&&row.regions){
     for(const key of REGIONS){
       const r=row.regions[key];
       if(r&&validFile(r.temperature_png)&&validFile(r.anomaly_png)&&
          Number.isFinite(r.mean_c)&&Number.isFinite(r.mean_anomaly_k))regions[key]=r;
     }
   }else if(validFile(row.temperature_png)&&validFile(row.anomaly_png)&&
         Number.isFinite(row.mean_c)&&Number.isFinite(row.mean_anomaly_k)){
     regions["80"]={...row};
   }
   if(!Object.keys(regions).length)continue;
   used.add(row.date);normalized.push({date:row.date,regions});
 }
 normalized.sort((a,b)=>b.date.localeCompare(a.date));
 return normalized.length?{...data,days:normalized}:null;
}
function available(){return archive?.days.filter(row=>row.regions[region()])||[];}
function clearMap(text){
 for(const id of ["arcticEra5TempMap","arcticEra5AnomalyMap"]){
   $(id).removeAttribute("src");$(id).alt="Keine validierte ERA5-Karte für diesen Ausschnitt";
 }
 for(const id of ["arcticEra5TempPng","arcticEra5AnomalyPng"]){
   $(id).removeAttribute("href");$(id).removeAttribute("download");
 }
 $("arcticEra5Pdf").disabled=true;
 $("arcticEra5MeanTemp").textContent="–";
 $("arcticEra5MeanAnomaly").textContent="–";
 $("arcticEra5MapPrev").disabled=true;$("arcticEra5MapNext").disabled=true;
 $("arcticEra5MeanMethod").textContent="Für diesen Kartenausschnitt sind noch keine geprüften Daten verfügbar.";
 status(text,true);
}
function current(){return days[position]||null;}
function render(n){
 if(!days.length)return;
 position=Math.max(0,Math.min(n,days.length-1));
 const row=current(),data=row.regions[region()],lower=region();
 const v=data.boundary_version||archive.boundary_version||2;
 $("arcticEra5MapDate").value=row.date;
 const cal=$("arcticEra5Calendar");cal.value=row.date;
 cal.min=days.at(-1).date;cal.max=days[0].date;
 const temp=$("arcticEra5TempMap"),anom=$("arcticEra5AnomalyMap");
 $("arcticEra5Pdf").disabled=true;
 temp.src=fileURL(data.temperature_png,v);
 anom.src=fileURL(data.anomaly_png,v);
 temp.alt="ERA5-Tagesmitteltemperatur "+lower+"–90°N vom "+dateLabel(row.date)+
  ", feste Farbskala −45 bis +15 °C mit Küstenlinien";
 anom.alt="ERA5-Abweichung vom Monatsklima 1991–2020 für "+lower+"–90°N am "+
  dateLabel(row.date)+", feste Farbskala −15 bis +15 K";
 $("arcticEra5MeanTemp").textContent=number(data.mean_c)+" °C";
 $("arcticEra5MeanAnomaly").textContent=signed(data.mean_anomaly_k)+" K";
 $("arcticEra5MeanMethod").textContent="Flächengewichtetes ERA5-Kappenmittel "+lower+
   " · "+dateLabel(row.date)+" · nicht identisch mit dem DMI-Index.";
 link("arcticEra5TempPng",data.temperature_png,row.date,"Temperatur",v);
 link("arcticEra5AnomalyPng",data.anomaly_png,row.date,"Monatsanomalie",v);
 $("arcticEra5MapPrev").disabled=position===days.length-1;
 $("arcticEra5MapNext").disabled=position===0;
 status("ERA5-Reanalyse "+dateLabel(row.date)+" · Region "+regionLabel()+
   " · 0,5°-Raster · Referenz: Monatsmittel 1991–2020 · feste Farbskalen.");
}
function setRegion(preferredDate){
 days=available();position=0;
 const selector=$("arcticEra5MapDate");
 selector.replaceChildren();
 const cal=$("arcticEra5Calendar");
 cal.disabled=days.length===0;
 const totals=archive?.days.length||0;
 const counts=REGIONS.map(k=>k+"–90°N: "+archive.days.filter(x=>x.regions[k]).length+" Tage");
 $("arcticEra5ArchiveProgress").textContent="Kartenarchiv: "+totals+" von "+
   (archive?.target_days||30)+" Zieltagen · "+counts.join(" · ")+
   ". Weitere ERA5-Tage werden automatisch ergänzt, sobald sie verfügbar sind.";
 if(!days.length){
   const option=document.createElement("option");option.value="";option.textContent="Noch keine Karten";
   selector.append(option);cal.value="";
   clearMap("Für "+regionLabel()+" liegen noch keine geprüften Karten vor. Die ERA5-Archivverarbeitung läuft schrittweise.");
   return;
 }
 for(const row of days){
   const opt=document.createElement("option");opt.value=row.date;opt.textContent=dateLabel(row.date);
   selector.append(opt);
 }
 let index=days.findIndex(x=>x.date===preferredDate);
 if(index<0)index=0;
 render(index);
}
function showMode(){
 const mode=$("arcticEra5MapMode").value;
 $("arcticEra5Maps").classList.toggle("single",mode!=="both");
 $("arcticEra5TempFrame").hidden=mode==="anomaly";
 $("arcticEra5AnomalyFrame").hidden=mode==="temperature";
}
async function exportPdf(){
 if(!current())return;
 const Pdf=window.jspdf?.jsPDF;
 if(!Pdf){status("PDF-Bibliothek nicht verfügbar; PNG-Karten können heruntergeladen werden.",true);return;}
 const row=current();
 const imgs=[{img:$("arcticEra5TempMap"),title:"Temperatur"},
             {img:$("arcticEra5AnomalyMap"),title:"Monatsanomalie"}];
 try{
  const pdf=new Pdf({orientation:"portrait",format:"a4",unit:"mm"});
  for(let i=0;i<imgs.length;i++){
   const image=imgs[i].img;
   if(!image.complete||image.naturalWidth<800)throw Error("Kartendatei noch nicht geladen");
   if(i)pdf.addPage();
   const ratio=Math.min(184/image.naturalWidth,257/image.naturalHeight);
   const w=image.naturalWidth*ratio,h=image.naturalHeight*ratio;
   const canvas=document.createElement("canvas");
   canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
   canvas.getContext("2d").drawImage(image,0,0);
   pdf.addImage(canvas.toDataURL("image/png"),"PNG",(210-w)/2,12,w,h);
   pdf.setFontSize(9);pdf.setTextColor(62,80,97);
   pdf.text("Copernicus C3S / ECMWF ERA5 · "+row.date+" · "+regionLabel()+" · "+imgs[i].title,13,289);
  }
  pdf.save("ERA5_Arktis_"+region()+"-90N_Temperatur_und_Anomalie_"+row.date+".pdf");
 }catch(err){status("PDF-Export nicht möglich: "+err.message,true);}
}
function enablePdfWhenLoaded(){
 const ready=["arcticEra5TempMap","arcticEra5AnomalyMap"].every(id=>{
  const e=$(id);return e.hasAttribute("src")&&e.complete&&e.naturalWidth>=800;
 });
 $("arcticEra5Pdf").disabled=!ready;
}
async function load(){
 try{
  const response=await fetch(BASE+"index.json?t="+Date.now(),{cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  archive=normalize(await response.json());
  if(!archive)throw Error("noch keine geprüften Kartendaten");
  setRegion();
  showMode();
 }catch(error){
  $("arcticEra5ArchiveProgress").textContent="Kartenarchiv noch nicht verfügbar.";
  clearMap("ERA5-Kartendaten nicht verfügbar ("+error.message+"). Die DMI-Auswertungen bleiben nutzbar.");
 }
}
function init(){
 if(!$("arcticEra5MapPanel"))return;
 $("arcticEra5MapRegion").addEventListener("change",()=>setRegion(current()?.date));
 $("arcticEra5MapDate").addEventListener("change",event=>{
  const n=days.findIndex(r=>r.date===event.target.value);
  if(n>=0)render(n);
 });
 $("arcticEra5Calendar").addEventListener("change",event=>{
  const date=event.target.value;
  const n=days.findIndex(row=>row.date===date);
  if(n>=0)render(n);
  else{
   event.target.value=current()?.date||"";
   status("Für den "+dateLabel(date)+" ist im "+regionLabel()+"-Archiv noch keine geprüfte ERA5-Karte verfügbar.",true);
  }
 });
 $("arcticEra5MapPrev").addEventListener("click",()=>render(position+1));
 $("arcticEra5MapNext").addEventListener("click",()=>render(position-1));
 $("arcticEra5MapMode").addEventListener("change",showMode);
 $("arcticEra5Pdf").addEventListener("click",exportPdf);
 for(const id of ["arcticEra5TempMap","arcticEra5AnomalyMap"]){
  $(id).addEventListener("load",enablePdfWhenLoaded);
  $(id).addEventListener("error",()=>{
   $("arcticEra5Pdf").disabled=true;
   status("Eine ERA5-Kartendatei konnte nicht geladen werden. Bitte Archiv-/Datenstatus prüfen.",true);
  });
 }
 load();
}
window.ArcticEra5Archive={normalize,validFile,getState:()=>({schema:archive?.schema,region:region(),days:days.map(x=>x.date)})};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();
