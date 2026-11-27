/* Phase 2 · true vector controls for selected scientific Chart.js diagrams.
   No chart data, viewport options or existing download paths are modified. */
(function(root){
"use strict";
const TARGETS={
 hyrasTmeanRegionCanvas:{slug:"hyras_tmean",title:"HYRAS · Temperaturmittel",source:"Quelle: Deutscher Wetterdienst · HYRAS-DE",hyras:true},
 hyrasTmaxRegionCanvas:{slug:"hyras_tmax",title:"HYRAS · Tageshöchsttemperatur",source:"Quelle: Deutscher Wetterdienst · HYRAS-DE",hyras:true},
 hyrasTminRegionCanvas:{slug:"hyras_tmin",title:"HYRAS · Tagestiefsttemperatur",source:"Quelle: Deutscher Wetterdienst · HYRAS-DE",hyras:true},
 stratoEnsembleCanvas:{
  slug:"stratosphaere_GEFS_60N_10hPa",
  title:"Stratosphäre · GEFS · zonaler Wind 60° N / 10 hPa",
  source:"Quelle: NOAA GEFS · NASA Ozone Watch / MERRA-2 (falls eingeblendet)"
 },
 stratoEpsCanvas:{
  slug:"stratosphaere_ECMWF_EPS_60N_10hPa",
  title:"Stratosphäre · ECMWF IFS ENS · zonaler Wind 60° N / 10 hPa",
  source:"Quelle: ECMWF IFS ENS Open Data · Original-Ensemblemitglieder"
 },
 stationSnowChart:{
  slug:"dwd_station_schneehoehe",
  title:"Stationsdiagramm · tägliche Schneehöhe",
  source:"Quelle: DWD Climate Data Center · Stationsmessungen und Klimareferenz"
 },
 stationSnowCumChart:{
  slug:"dwd_station_schneehoehe_kumuliert",
  title:"Stationsdiagramm · akkumulierte Schneehöhe",
  source:"Quelle: DWD Climate Data Center · Stationsmessungen und qualitätsgeprüfte Referenz"
 },
 stationPrecipChart:{
  slug:"dwd_station_niederschlag",
  title:"Stationsdiagramm · Niederschlag",
  source:"Quelle: DWD Climate Data Center · tägliche Stationsniederschläge"
 },
 sjaChart:{
  slug:"dwd_stations_jahresanalyse",
  title:"DWD Stations-Jahresanalyse",
  source:"Quelle: DWD Climate Data Center · Stationsjahrgänge und Klimareferenzen"
 }
};
let installed=false;
let jspdfPromise=null;
const controls=new WeakMap();
function status(row,msg,error){
 let el=row.querySelector(".cd-sciv-status");
 if(!el){
   el=document.createElement("span");el.className="cd-sciv-status";
   el.setAttribute("role","status");row.appendChild(el);
 }
 el.textContent=msg;
 el.style.color=error?"#b42318":"#536b80";
}
function chartFor(canvas){
 if(root.Chart?.getChart)return root.Chart.getChart(canvas);
 return Object.values(root.Chart?.instances||{}).find(chart=>chart.canvas===canvas);
}
function activeData(chart){
 return chart?.data?.datasets?.some((ds,i)=>{
   if(chart.isDatasetVisible?.(i)===false)return false;
   return (ds.data||[]).some(v=>
     (typeof v==="number"&&Number.isFinite(v))||
     (v&&typeof v==="object"&&typeof v.y==="number"&&Number.isFinite(v.y)));
 });
}
function describe(chart,config,transparent=false){
 const labels=chart.data.labels||[];
 const starts=String(labels[0]??"–"),ends=String(labels[labels.length-1]??"–");
 let station="";
 if(["stationSnowChart","stationSnowCumChart","stationPrecipChart","sjaChart"].includes(chart.canvas.id)){
   const selectedInfo=chart.canvas.id==="sjaChart"?"sjaSelected":"stationSnowSelectedMeta";
   const value=document.getElementById(selectedInfo)?.textContent?.trim();
   station=value?value.slice(0,170):"Station laut Auswahl";
 }
 if(config.hyras){
   const panel=chart.canvas.closest(".hyras-tmean-region-panel");
   const heading=panel?.querySelector(".hyras-tmean-region-head h3")?.textContent?.trim();
   const subtitle=panel?.querySelector(".hyras-tmean-region-head p")?.textContent?.trim();
   const region=document.getElementById("hyrasTmeanRegionSelect")?.value||"Deutschland";
   const period=document.getElementById("hyrasPeriodSelect")?.selectedOptions?.[0]?.textContent?.trim()||"";
   const reference=document.getElementById("hyrasReferenceSelect")?.value||"1991-2020";
   return {title:heading||config.title+" · "+region,axis:chart.scales?.y?.options?.title?.text||"Temperatur (°C)",subtitle:subtitle||period+" · Referenz "+reference,source:config.source,hyras:true,transparent,metadata:["Zeitraum: "+starts+" bis "+ends,"Klimareferenz: "+reference,"Datenlücken bleiben unverändert"]};
 }
 const annualTitle=chart.canvas.id==="sjaChart"?
   document.getElementById("sjaChartTitle")?.textContent?.trim():"";
 const selected=chart.data.datasets.filter((_,i)=>chart.isDatasetVisible?.(i)!==false).length;
 return {
   title:annualTitle?config.title+" · "+annualTitle:config.title,
   axis:chart.scales?.y?.options?.title?.text || chart.options?.scales?.y?.title?.text ||
      (chart.canvas.id.startsWith("stationSnow")?"Schneehöhe [cm]":"Einheit siehe Diagramm"),
   source:config.source,
   subtitle:"Originalwerte · unabhängige Vektoransicht",
   metadata:[
     station ? "Station: "+station : "Verifizierte Originaldaten · "+config.title,
     "Zeitraum: "+starts+" bis "+ends,
     "Sichtbare Datenreihen: "+selected+" · fehlende Werte bleiben Datenlücken",
     "Zeitachse wie im Diagramm (UTC bei Ensembleprognosen)",
     "Quelle und Einheiten: siehe Diagramm und Fußzeile",
     "Erstellt: "+new Date().toLocaleString("de-DE")+" · Climate Dashboard Deutschland"
   ]
 };
}
function jsPDF(){
 if(root.jspdf?.jsPDF)return Promise.resolve(root.jspdf.jsPDF);
 if(root.dashboardExportLibraries?.pdf)return root.dashboardExportLibraries.pdf().then(()=>{if(!root.jspdf?.jsPDF)throw Error("PDF-Bibliothek nicht verfügbar.");return root.jspdf.jsPDF;});
 if(jspdfPromise)return jspdfPromise;
 jspdfPromise=new Promise((resolve,reject)=>{
  const script=document.createElement("script");
  script.async=true;
  script.src="vendor/jspdf/4.2.1/dist/jspdf.umd.min.js";
  script.onload=()=>root.jspdf?.jsPDF?resolve(root.jspdf.jsPDF):reject(Error("jsPDF wurde nicht initialisiert."));
  script.onerror=()=>reject(Error("PDF-Bibliothek nicht erreichbar."));
  document.head.appendChild(script);
 }).catch(error=>{jspdfPromise=null;throw error;});
 return jspdfPromise;
}
async function download(canvas,format,row){
 const chart=chartFor(canvas),target=TARGETS[canvas.id];
 if(!target||!activeData(chart))throw Error("Bitte zuerst ein Diagramm mit gültigen Daten laden.");
 if(chart.config?.type!=="line"||chart.scales?.x?.type!=="category" ||
   chart.data.datasets.some((ds,i)=>
     chart.isDatasetVisible?.(i)!==false && ds.type && ds.type!=="line"))
   throw Error("Vektorexport unterstützt hier derzeit nur Linien mit Kategorien-/Datumsachse.");
 const exporter=root.T850VectorExport;
 if(!exporter)throw Error("Wissenschaftlicher Vektorexport wurde nicht geladen.");
 const transparent=target.hyras&&row.querySelector("select")?.value==="transparent";
 const info=describe(chart,target,transparent);
 const scene=exporter.buildScene(chart,info);
 const date=new Date().toISOString().slice(0,10);
 const clean=v=>String(v||"").replace(/[^\p{L}\p{N}_-]+/gu,"_").replace(/^_+|_+$/g,"");
 const region=target.hyras?document.getElementById("hyrasTmeanRegionSelect")?.value:"";
 const period=target.hyras?document.getElementById("hyrasPeriodSelect")?.value:"";
 const ref=target.hyras?document.getElementById("hyrasReferenceSelect")?.value:"";
 const name=[target.slug,region,period,ref,date].filter(Boolean).map(clean).join("_");
 if(format==="svg")exporter.saveSvg([scene],name+".svg");
 else if(format==="png4k"||format==="pnghd"){
  const width=format==="png4k"?3840:1920,height=width*9/16;
  const svg=exporter.toSvg([scene]),url=URL.createObjectURL(new Blob([svg],{type:"image/svg+xml"}));
  try{const img=new Image();img.src=url;await img.decode();const out=document.createElement("canvas");out.width=width;out.height=height;const ctx=out.getContext("2d");if(!transparent){ctx.fillStyle="#ffffff";ctx.fillRect(0,0,width,height);}const scale=Math.min(width/img.naturalWidth,height/img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale;ctx.drawImage(img,(width-w)/2,(height-h)/2,w,h);const blob=await new Promise((resolve,reject)=>out.toBlob(b=>b?resolve(b):reject(Error("PNG-Export fehlgeschlagen")),"image/png"));const a=document.createElement("a"),u=URL.createObjectURL(blob);a.href=u;a.download=name+"_"+format+".png";document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),30000);}finally{URL.revokeObjectURL(url);}
 }
 else{
  const PDF=await jsPDF(),pdf=new PDF({orientation:"landscape",unit:"mm",format:"a3"});
  exporter.drawPdf(pdf,scene);pdf.save(name+".pdf");
 }
 status(row,format.startsWith("png")?"PNG-Export erstellt.":format.toUpperCase()+"-Vektorexport erstellt.",false);
}
function add(chart){
 const canvas=chart.canvas,target=TARGETS[canvas?.id];
 if(!target)return;
 const eligible=activeData(chart)&&chart.config?.type==="line"&&
   chart.scales?.x?.type==="category"&&
   !chart.data.datasets.some((ds,i)=>
     chart.isDatasetVisible?.(i)!==false && ds.type && ds.type!=="line");
 if(!eligible){
   const old=controls.get(canvas);
   if(old){old.remove();controls.delete(canvas);}
   return;
 }
 if(controls.has(canvas))return;
 const wrapper=canvas.closest(".chart,.chart-container,.station-snow-chart,.strato-eps-chart,.sja-chartbox")||canvas.parentElement;
 if(!wrapper?.insertAdjacentElement)return;
 const row=document.createElement("div");
 row.className="cd-sciv-actions";
 row.setAttribute("role","group");
 row.setAttribute("aria-label","Vektorexporte für "+target.title);
 if(target.hyras){const select=document.createElement("select");select.setAttribute("aria-label","Exporthintergrund");select.add(new Option("Hintergrund transparent","transparent"));select.add(new Option("Hintergrund weiß","white"));row.appendChild(select);}
 for(const format of target.hyras?["pdf","svg","pnghd","png4k"]:["pdf","svg"]){
   const button=document.createElement("button");
   button.type="button";
   button.className="cd-sciv-button";
   button.textContent=({pdf:"PDF (Vektor)",svg:"SVG (Ebenen)",pnghd:"PNG Full-HD",png4k:"PNG 4K"})[format];
   button.title=format==="pdf"?"Einzelne editierbare PDF-Kurven als echte Pfade":format==="svg"?"Benannte SVG-Ebenen für Illustrator und After Effects":"16:9-PNG unabhängig von der Bildschirmgröße";
   button.addEventListener("click",async()=>{
      button.disabled=true;
      status(row,format.toUpperCase()+" wird aufgebaut …",false);
      try{await download(canvas,format,row)}
      catch(error){status(row,error.message||String(error),true);}
      finally{button.disabled=false;}
   });
   row.appendChild(button);
 }
 wrapper.insertAdjacentElement("afterend",row);
 controls.set(canvas,row);
}
function install(){
 if(installed||typeof root.Chart?.register!=="function")return;
 installed=true;
 root.Chart.register({id:"scientificVectorActionsV1",afterUpdate:add,
   beforeDestroy(chart){
     const row=controls.get(chart.canvas);
     if(row){row.remove();controls.delete(chart.canvas);}
   }});
 for(const chart of Object.values(root.Chart.instances||{}))add(chart);
}
function init(){
 install();
 if(!installed)root.addEventListener("load",install,{once:true});
 // Main dashboard may load Chart.js lazily after DOMContentLoaded.
 // Capture script load events so later-created station charts get the exporter.
 document.addEventListener("load",event=>{
   if(event.target?.tagName==="SCRIPT"&&!installed)install();
 },true);
 const css=document.createElement("style");
 css.textContent=".cd-sciv-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:7px 0 15px;max-width:100%}.cd-sciv-button{min-height:44px;padding:9px 13px;border:1px solid #9badbf;border-radius:8px;background:#fff;color:#183854;font:700 13px/1.3 system-ui,sans-serif;cursor:pointer}.cd-sciv-button:disabled{opacity:.55;cursor:wait}.cd-sciv-status{flex:1 1 170px;font:12px/1.4 system-ui,sans-serif;overflow-wrap:anywhere}";
 document.head.appendChild(css);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
root.ScientificVectorActions={install,targets:TARGETS};
})(window);
