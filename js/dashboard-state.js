/* dashboard-state.js – Zustand/Persistenz, mobile Tab-Navigation, Status-Badges, CSV-Export, initializeDashboardState()
   Aus index.html ausgelagert (Schritt 5). Klassisches Skript, gemeinsamer globaler Scope. */

function persistDashboardState(key,value){
  const normalized=String(value);
  const isEmptySearch=key.endsWith("Search") && normalized==="";
  if(isEmptySearch) delete dashboardState[key];
  else dashboardState[key]=normalized;
  try{localStorage.setItem(DASHBOARD_STATE_KEY,JSON.stringify(dashboardState));}catch(_error){}
  const url=new URL(window.location.href);
  if(key==="tab") url.searchParams.set("tab",normalized);
  else if(isEmptySearch) url.searchParams.delete(`s_${key}`);
  else url.searchParams.set(`s_${key}`,normalized);
  history.replaceState(null,"",url);
}

let restoringDashboardControls=false;
function restoreDashboardControls(root=document){
  if(restoringDashboardControls)return;
  restoringDashboardControls=true;
  try{
  root.querySelectorAll("select[id], input[id]").forEach(control=>{
    // Mobile navigation mirrors dashboardState.tab and must never restore
    // a stale independent value when other station selects are populated.
    if(control.id==="mobileTabSelect")return;
    if(window.isDashboardLazyPending?.(control))return;
    const saved=dashboardState[control.id];
    if(saved===undefined) return;
    if(control.type==="checkbox"){
      const checked=saved==="true";
      if(control.checked!==checked){control.checked=checked;control.dispatchEvent(new Event("change",{bubbles:true}));}
      return;
    }
    const optionExists=!control.options || [...control.options].some(option=>option.value===saved);
    if(optionExists && control.value!==saved){
      control.value=saved;
      const eventType=control instanceof HTMLInputElement && control.type==="search"?"input":"change";
      control.dispatchEvent(new Event(eventType,{bubbles:true}));
    }
  });
  }finally{restoringDashboardControls=false;}
}

function initializeMobileTabNavigation(){
  const select=document.getElementById("mobileTabSelect");
  if(!select) return;
  select.innerHTML="";
  const seen=new Set();
  document.querySelectorAll(".tab-button").forEach(button=>{
    const match=button.getAttribute("onclick")?.match(/switchTab\('([^']+)'\)/);
    if(!match || seen.has(match[1])) return;
    seen.add(match[1]);
    const option=document.createElement("option");
    option.value=match[1];
    option.textContent=button.textContent.trim();
    select.appendChild(option);
  });
  [
    ["jahresextremwerte.html","Jahresextreme"],
    ["dekadenrekorde.html","Dekadenrekorde"],
    ["feiertagsextremwerte.html","Feiertags-Extreme"],
    ["stratosphaere.html","Stratosphäre (60° N)"],
    ["wettergefahren.html","Europa · ICON-EU Wettergefahren"],
    ["saharastaub.html","Sonstiges · Saharastaub-Monitor (ICON-ART-EU)"],
    ["gfs_f003_europe.html","Sonstiges · GFS +3 h · Anomalie 1991–2020"],
    ["gfs_weekly_europe.html","Sonstiges · GFS · 7-Tage-Abweichung"],
    ["satelliten.html","Sonstiges · Satellitenbilder"],
    ["saisonal_europa.html","Europa · Saisonal SEAS5"],
    ["zirkulation.html","Sonstiges · NAO, AO & Zirkulationsmuster"],
    ["isobaren_original.html","Europa · Isobaren & Fronten"],
    ["blocking.html","Sonstiges · Blocking-Monitor"],
    ["enso.html","Sonstiges · ENSO / El Niño / La Niña"],
    ["qbo.html","Sonstiges · QBO"],
    ["mjo.html","Sonstiges · MJO"],
    ["meereis.html","Sonstiges · Meereis (Arktis & Antarktis)"],
    ["arktis_temperatur.html","Sonstiges · Arktische Temperaturen (DMI &gt;80° N)"],
    ["ace.html","Sonstiges · ACE / Tropische Wirbelstürme"]
  ].forEach(([href,label])=>{
    const option=document.createElement("option");
    option.value=href;
    option.textContent=label;
    option.dataset.page="external";
    select.appendChild(option);
  });

  const alpenOption=document.createElement("option");
  alpenOption.value="__alpenwetter__";
  alpenOption.textContent="Alpenwetter 🔒";
  alpenOption.dataset.page="alpenwetter";
  select.appendChild(alpenOption);

  select.addEventListener("change",()=>{
    const option=select.options[select.selectedIndex];
    if(option?.dataset.page==="external"){
      window.location.href=option.value;
      return;
    }
    if(option?.dataset.page==="alpenwetter"){
      const activeTab=document.querySelector(".tab-content.active")?.id||"overview";
      openAlpenwetter();
      select.value=activeTab;
      return;
    }
    switchTab(select.value);
  });
  select.value=dashboardState.tab||document.querySelector(".tab-content.active")?.id||"overview";
}

function renderDashboardStatusBadges(status){
  const target=document.getElementById("statusBadges");
  if(!target) return;
  const badges=[];
  const now=new Date(),today=Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate());
  const add=(label,stamp,monthly=false)=>{
    const valid=typeof stamp==="string"&&(monthly?/^\d{4}-\d{2}$/:/^\d{4}-\d{2}-\d{2}$/).test(stamp)&&Number.isFinite(Date.parse(stamp));
    const d=valid?new Date(stamp):null;
    const age=valid?(monthly?(now.getUTCFullYear()-d.getUTCFullYear())*12+now.getUTCMonth()-d.getUTCMonth():(today-d.getTime())/86400000):Infinity;
    const ready=valid&&age>=(monthly?1:0)&&age<=(monthly?(now.getUTCDate()<=5?2:1):3);
    badges.push(`<span class="status-badge ${ready?"ok":"warn"}" title="Datenstand: ${valid?stamp:"unbekannt"}">${label}${ready?"":valid?" · veraltet":" · fehlt"}</span>`);
  };
  add("Gebietsmittel",status.monthly?.latest_complete_month,true);
  add("Tageswerte",status.daily?.latest_date);
  add("Stationsrekorde",status.station_records?.data_through);
  add("Stationsniederschlag",status.station_precip?.data_through);
  add("Stations-Kenntage",status.station_climate_days?.data_through);
  add("Hitzewellen",status.station_heatwaves?.data_through);
  target.innerHTML=badges.join("");
}

function csvEscape(value){
  if(value===null || value===undefined) return "";
  const text=typeof value==="number"?String(value).replace(".",","):String(value);
  return /[;"\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text;
}
function chartRowsForCsv(chart){
  const datasets=chart.data.datasets||[];
  const labels=chart.data.labels||[];
  const objectData=datasets.some(dataset=>(dataset.data||[]).some(value=>value && typeof value==="object"));
  if(objectData){
    const headers=["Datensatz","Label","x","y","r","v","Jahr","Datum","Start","Ende"];
    const rows=[];
    datasets.forEach(dataset=>(dataset.data||[]).forEach((point,index)=>{
      if(point===null || point===undefined) return;
      const p=typeof point==="object"?point:{y:point};
      rows.push([dataset.label||"",labels[index]??p.label??"",p.x??"",p.y??"",p.r??"",p.v??"",p.year??"",p.date??"",p.start??"",p.end??""]);
    }));
    return {headers,rows};
  }
  return {
    headers:["Label",...datasets.map(dataset=>dataset.label||"Wert")],
    rows:labels.map((label,index)=>[label,...datasets.map(dataset=>dataset.data?.[index]??"")])
  };
}
function exportChartAsCsv(canvas){
  const chart=Chart.getChart(canvas);
  if(!chart) throw new Error("Die Grafik ist noch nicht geladen.");
  const {headers,rows}=chartRowsForCsv(chart);
  const separator=";";
  const content="\ufeff"+[headers,...rows].map(row=>row.map(csvEscape).join(separator)).join("\r\n");
  const blob=new Blob([content],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const link=document.createElement("a");
  link.href=url;link.download=safeExportFilename(chartExportTitle(chart,canvas),"csv");
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
}
async function runChartCsvExport(button,canvas){
  const original=button.textContent;button.disabled=true;button.textContent="…";
  try{await new Promise(resolve=>requestAnimationFrame(resolve));exportChartAsCsv(canvas);}
  catch(error){console.error(error);alert(`CSV-Download nicht möglich: ${error.message}`);}
  finally{button.disabled=false;button.textContent=original;}
}

function initializeDashboardState(){
  initializeMobileTabNavigation();
  document.addEventListener("input",event=>{
    if(restoringDashboardControls)return;
    const control=event.target;
    if(!(control instanceof HTMLInputElement) || !control.id || control.type!=="search") return;
    persistDashboardState(control.id,control.value);
  });
  document.addEventListener("change",event=>{
    if(restoringDashboardControls)return;
    const control=event.target;
    if(!(control instanceof HTMLSelectElement || control instanceof HTMLInputElement) || !control.id) return;
    if(control.id==="mobileTabSelect")return; // persisted by switchTab only
    persistDashboardState(control.id,control.type==="checkbox"?control.checked:control.value);
  });
  const observer=new MutationObserver(()=>window.setTimeout(restoreDashboardControls,0));
  document.querySelectorAll("select[id]").forEach(select=>observer.observe(select,{childList:true}));
  window.setTimeout(()=>{
    restoreDashboardControls();
    switchTab(dashboardState.tab||"overview",{persist:false});
  },120);
}


