/* Verified ERA5 polar-cap 2m temperature and monthly-reference anomaly maps. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const BASE="data/arctic_era5_maps/";
let index=null,position=0;
const sanitizeFile=p=>/^maps\/(?:t2m|anomaly)_[0-9]{8}\.png$/.test(p);
const germanDate=s=>s&&/^\d{4}-\d{2}-\d{2}$/.test(s)?s.slice(8)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
const numeric=x=>Number.isFinite(x)?x.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const fmtSigned=x=>Number.isFinite(x)?(x>0?"+":"")+numeric(x):"–";
function message(text,warning=false){
  const p=$("arcticEra5MapStatus");p.textContent=text;p.classList.toggle("error",warning);
}
function src(name){return BASE+name+(index?.boundary_version?"?map=b"+index.boundary_version:"");}
function link(id,filename,date,label){
  const a=$(id);
  if(!sanitizeFile(filename)){a.removeAttribute("href");a.removeAttribute("download");return;}
  a.href=src(filename);a.download="ERA5_Arktis80_"+label+"_"+date+".png";
}
function selectPosition(n){
  if(!index?.days?.length)return;
  position=Math.min(index.days.length-1,Math.max(0,n));
  const item=index.days[position];
  $("arcticEra5MapDate").value=item.date;
  const main=$("arcticEra5TempMap"),anom=$("arcticEra5AnomalyMap");
  const temp=src(item.temperature_png),deviation=src(item.anomaly_png);
  main.src=temp;anom.src=deviation;
  main.alt="ERA5-2-m-Temperaturkarte nördlich 80°N vom "+germanDate(item.date)+
    " mit fester Farbskala −45 bis +15 °C und Küstenlinien";
  anom.alt="ERA5-Tagesmittelabweichung vom Monatsklima 1991–2020 am "+germanDate(item.date)+
    " mit fester Skala −15 bis +15 K";
  $("arcticEra5MeanTemp").textContent=numeric(item.mean_c)+" °C";
  $("arcticEra5MeanAnomaly").textContent=fmtSigned(item.mean_anomaly_k)+" K";
  $("arcticEra5MeanMethod").textContent="Flächengewichtetes Mittel von 80°N bis 90°N · ERA5 · "+germanDate(item.date);
  link("arcticEra5TempPng",item.temperature_png,item.date,"Temperatur");
  link("arcticEra5AnomalyPng",item.anomaly_png,item.date,"Monatsanomalie");
  $("arcticEra5MapPrev").disabled=position>=index.days.length-1;
  $("arcticEra5MapNext").disabled=position===0;
  message("ERA5-Reanalyse vom "+germanDate(item.date)+
    " · 2-m-Lufttemperatur · Tagesmittel 00–24 UTC · 0,5° · Monatsreferenz 1991–2020.");
}
function showMode(){
  const mode=$("arcticEra5MapMode").value;
  const both=mode==="both";
  $("arcticEra5Maps").classList.toggle("single",!both);
  $("arcticEra5TempFrame").hidden=mode==="anomaly";
  $("arcticEra5AnomalyFrame").hidden=mode==="temperature";
}
async function asPdf(){
  if(!index?.days?.length)return;
  const Pdf=window.jspdf?.jsPDF;
  if(!Pdf){message("PDF-Bibliothek derzeit nicht verfügbar. Die PNG-Karten bleiben abrufbar.",true);return;}
  const item=index.days[position];
  const images=[
    {el:$("arcticEra5TempMap"),name:"Temperaturkarte"},
    {el:$("arcticEra5AnomalyMap"),name:"Abweichung zum Monatsmittel 1991–2020"}
  ];
  try {
    const pdf=new Pdf({orientation:"portrait",format:"a4",unit:"mm"});
    for(let i=0;i<images.length;i++){
      const img=images[i].el;
      if(!img.complete||img.naturalWidth<800)throw Error("Eine Karte ist noch nicht vollständig geladen.");
      if(i)pdf.addPage();
      const originalWidth=img.naturalWidth,originalHeight=img.naturalHeight;
      const scale=Math.min(184/originalWidth,257/originalHeight);
      const w=originalWidth*scale,h=originalHeight*scale;
      const canvas=document.createElement("canvas");
      canvas.width=originalWidth;canvas.height=originalHeight;
      canvas.getContext("2d").drawImage(img,0,0);
      pdf.addImage(canvas.toDataURL("image/png"),"PNG",(210-w)/2,12,w,h);
      pdf.setFontSize(9);
      pdf.setTextColor(62,80,97);
      pdf.text("Quelle: Copernicus C3S / ECMWF ERA5 · "+item.date+" · "+images[i].name,13,289);
    }
    pdf.save("ERA5_Arktis80_Temperatur_und_Monatsanomalie_"+item.date+".pdf");
  }catch(err){
    message("PDF konnte nicht erstellt werden: "+err.message,true);
  }
}
function ready(data){
  if(data?.ready!==true||!Array.isArray(data.days)||!data.days.length)return false;
  const days=data.days.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x.date||"")&&
    sanitizeFile(x.temperature_png)&&sanitizeFile(x.anomaly_png)&&
    Number.isFinite(x.mean_c)&&Number.isFinite(x.mean_anomaly_k))
    .sort((a,b)=>b.date.localeCompare(a.date));
  if(!days.length)return false;
  index={...data,days};
  $("arcticEra5MapDate").replaceChildren();
  for(const item of days){
    const o=document.createElement("option");o.value=item.date;o.textContent=germanDate(item.date);
    $("arcticEra5MapDate").append(o);
  }
  selectPosition(0);showMode();
  $("arcticEra5Pdf").disabled=false;
  return true;
}
async function load(){
  try{
    const res=await fetch(BASE+"index.json?t="+Date.now(),{cache:"no-store"});
    if(!res.ok)throw Error("HTTP "+res.status);
    const json=await res.json();
    if(!ready(json)){
      message("Die ERA5-Kartenpipeline ist eingerichtet, aber noch keine vollständig geprüften echten Karten veröffentlicht. Es werden keine Ersatzwerte angezeigt.",true);
    }
  }catch(err){
    message("ERA5-Kartendaten derzeit nicht verfügbar ("+err.message+"). Bestehende DMI-Temperaturdiagramme bleiben unabhängig davon nutzbar.",true);
  }
}
function init(){
  if(!$("arcticEra5MapPanel"))return;
  $("arcticEra5MapDate").addEventListener("change",event=>{
    const n=index?.days?.findIndex(x=>x.date===event.target.value)??-1;
    if(n>=0)selectPosition(n);
  });
  $("arcticEra5MapPrev").addEventListener("click",()=>selectPosition(position+1));
  $("arcticEra5MapNext").addEventListener("click",()=>selectPosition(position-1));
  $("arcticEra5MapMode").addEventListener("change",showMode);
  $("arcticEra5Pdf").addEventListener("click",asPdf);
  for(const id of ["arcticEra5TempMap","arcticEra5AnomalyMap"])
    $(id).addEventListener("error",()=>message("Eine ERA5-Bilddatei kann nicht geladen werden; bitte die veröffentlichte Kartenliste überprüfen.",true));
  load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();
