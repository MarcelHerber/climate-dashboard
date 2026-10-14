/* Historischer Major-SSW-Katalog; nur bestätigte NASA-MERRA-2-Winddaten. */
(()=>{"use strict";
const ROOT="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/ssw_catalog.json";
const $=id=>document.getElementById(id);
const fmt=d=>d?new Date(d+"T12:00:00Z").toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",timeZone:"UTC"}):"–";
const number=x=>Number.isFinite(x)?x.toLocaleString("de-DE",{maximumFractionDigits:1,minimumFractionDigits:1}):"–";
let catalog=null,chart=null;
function cell(row,value){const td=document.createElement("td");td.textContent=value==null?"–":String(value);row.append(td);}
function download(csv,name){const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500);}
function selectedRows(){
 const type=$("sswArchiveType").value,year=$("sswArchiveWinter").value;
 const rows=type==="final"?catalog.excluded_final_warmings:catalog.events;
 return rows.filter(r=>!year||String(r.year)===year);
}
function renderTable(){
 const body=$("sswArchiveRows");body.replaceChildren();
 const rows=selectedRows();
 for(const e of rows){
  const tr=document.createElement("tr");
  cell(tr,e.winter);cell(tr,fmt(e.date));cell(tr,$("sswArchiveType").value==="final"?"Final warming (ausgeschlossen)":"Windbasiertes Major SSW");
  cell(tr,number(e.minimum_30d_ms)+" m/s");
  cell(tr,e.easterly_days+" Tage");
  cell(tr,fmt(e.return_west_10d));
  body.append(tr);
 }
 if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.textContent="Für diese Auswahl liegen keine bestätigten Ereignisse vor.";tr.append(td);body.append(tr);}
 $("sswArchiveCountLabel").textContent=rows.length+" Ereignisse in der Auswahl";
}
function drawChart(){
 if(!window.Chart)return;
 const complete=catalog.seasons.filter(x=>x.status==="complete");
 if(chart)chart.destroy();
 chart=new Chart($("sswArchiveChart"),{type:"bar",
  data:{labels:complete.map(s=>s.label),datasets:[{label:"Major SSW (windbasiert)",data:complete.map(s=>s.events),backgroundColor:"#2672b4",borderRadius:2,maxBarThickness:14}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>ctx.parsed.y+" Ereignis(se)"}}},
    scales:{x:{ticks:{maxTicksLimit:15,maxRotation:45},grid:{display:false}},
      y:{beginAtZero:true,ticks:{stepSize:1},title:{display:true,text:"Ereignisse pro Winter"}}}}});
}
function csvExport(){
 const rows=[["Saison","Zentraldatum_UTC","Typ","Minimum_30T_m_s","Ostwindtage_erste_Phase","Rueckkehr_10_Westwindtage"]];
 const type=$("sswArchiveType").value;
 for(const e of selectedRows())rows.push([e.winter,e.date,type==="final"?"Final warming (ausgeschlossen)":"Major SSW",e.minimum_30d_ms,e.easterly_days,e.return_west_10d||""]);
 download(rows.map(row=>row.map(x=>'"'+String(x??"").replace(/"/g,'""')+'"').join(";")).join("\r\n"),"SSW_Ereigniskatalog_60N_10hPa.csv");
}
async function load(){
 $("sswArchiveStatus").textContent="Lade NASA-Ereigniskatalog …";
 try{
  const r=await fetch(ROOT+"?v="+Math.floor(Date.now()/3600000),{cache:"no-store"});
  if(!r.ok)throw Error("Datenarchiv HTTP "+r.status);
  const x=await r.json();
  if(x.schema_version!==1||!Array.isArray(x.events)||!Array.isArray(x.seasons)||!Array.isArray(x.excluded_final_warmings))throw Error("Archivschema nicht gültig");
  catalog=x;
  const full=catalog.seasons.filter(s=>s.status==="complete");
  $("sswArchiveEventCount").textContent=String(catalog.event_count);
  $("sswArchiveWinterCount").textContent=String(full.length);
  $("sswArchiveLastEvent").textContent=fmt(catalog.events[0]?.date);
  $("sswArchiveDataDate").textContent=fmt(catalog.analysis_through);
  const years=$("sswArchiveWinter");years.replaceChildren(new Option("Alle Winter",""));
  for(const s of [...catalog.seasons].reverse())if(s.status==="complete")years.add(new Option(s.label,String(s.year)));
  $("sswArchiveStatus").textContent="MERRA-2-Tagesanalysen · "+
   catalog.complete_seasons+" vollständige Winter · "+
   catalog.incomplete_seasons+" unvollständige ältere Winter · Katalog erstellt "+String(catalog.generated_utc).slice(0,16).replace("T"," ")+" UTC.";
  $("sswArchiveCsv").disabled=false;renderTable();drawChart();
 }catch(err){$("sswArchiveStatus").textContent="Ereignisarchiv noch nicht verfügbar: "+err.message+" · Bestehende Winddiagramme bleiben nutzbar.";}
}
function start(){
 if(!$("sswArchiveCard"))return;
 $("sswArchiveWinter").addEventListener("change",renderTable);
 $("sswArchiveType").addEventListener("change",renderTable);
 $("sswArchiveCsv").addEventListener("click",csvExport);
 $("sswArchiveReload").addEventListener("click",load);
 load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();
