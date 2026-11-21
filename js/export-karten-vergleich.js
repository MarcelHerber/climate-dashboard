/* export-karten-vergleich.js – Grafik-Export (PNG/PDF), Stationskarten, Vergleichsmodus
   Aus index.html ausgelagert (Schritt 2c). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= GRAFIK-EXPORT PNG / PDF =================
const CHART_EXPORT_FALLBACK_TITLES={
  monthlyChart:"Gebietsmittel",
  monthlyDeviationChart:"Gebietsmittel - Abweichung",
  climateIndexChart:"Klima-Index",
  accumulationChart:"Seit Jahresbeginn",
  stationPrecipChart:"Stationsniederschlag - Jahresverlauf",
  stationPrecipDeviationChart:"Stationsniederschlag - Abweichung",
  stationSnowChart:"Stationsschneehöhe - hydrologisches Jahr",
  stationSnowDeviationChart:"Stationsschneehöhe - Abweichung",
  stationSnowCumChart:"Stationsschneehöhe - Kumuliert (cm-Tage)",
  dailyChart:"Tageshöchstwerte",
  dailyDeviationChart:"Tageshöchstwerte - Abweichung",
  dailyAllYearsChart:"Tageshöchstwerte - Alle Jahre",
  extremeCumulativeChart:"Deutschland-Kenntage - Akkumuliert",
  yearlyExtremeChart:"Deutschland-Kenntage nach Jahr",
  yearlyMaxChart:"Jahreshöchstwerte",
  heatmapChart:"Deutschland-Kenntage - Jahr-Monat-Heatmap",
  stationClimateDaysCumulativeChart:"Stations-Kenntage - Akkumuliert",
  stationClimateDaysBarChart:"Stations-Kenntage - Jahres- und Saisonwerte",
  stationHeatwavesBubbleChart:"Stations-Hitzewellen - Intensität und Schweregrad",
  stationHeatwavesBarChart:"Stations-Hitzewellen - Anzahl pro Jahr",
  stationProfileGtsChart:"Stationsprofil - Grünlandtemperatursumme",
  stationProfileWarmthChart:"Stationsprofil - Wärmesumme",
  stationProfileColdSumChart:"Stationsprofil - Kältesumme",
  stationProfileClimateTrendChart:"Stationsprofil - Klimazeitreihe"
};

function chartExportTitle(chart,canvas){
  const title=chart?.options?.plugins?.title?.text;
  if(Array.isArray(title) && title.length) return title.join(" - ");
  if(typeof title==="string" && title.trim()) return title.trim();
  return CHART_EXPORT_FALLBACK_TITLES[canvas.id] || canvas.id || "Climate Dashboard";
}

function safeExportFilename(title,extension){
  const clean=String(title||"climate-dashboard")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"")
    .replace(/ß/g,"ss")
    .replace(/[^a-zA-Z0-9]+/g,"_")
    .replace(/^_+|_+$/g,"")
    .slice(0,110) || "climate_dashboard";
  const date=new Date().toISOString().slice(0,10);
  return `${clean}_${date}.${extension}`;
}

function chartCanvasWithWhiteBackground(chart){
  if(!window.DashboardExportHQ)throw new Error("Die hochauflösende Exportbibliothek wurde nicht geladen.");
  const canvas=chart.canvas;
  const id=canvas.id||"";
  const source=id.startsWith("stationSnow")
    ?"DWD CDC · KL SHK_TAG / RR SH_TAG · Referenz 1991–2020"
    :id.startsWith("stationPrecip")
      ?"DWD CDC · Stationsniederschlag · Referenz 1991–2020"
      :"Climate Dashboard Deutschland · Datenquelle und Zeitraum siehe Diagramm";
  return window.DashboardExportHQ.renderChart(chart,{
    title:chartExportTitle(chart,canvas),source
  });
}

function triggerDataUrlDownload(dataUrl,filename){
  const link=document.createElement("a");
  link.href=dataUrl;
  link.download=filename;
  link.rel="noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function exportChartAsPng(canvas){
  const chart=Chart.getChart(canvas);
  if(!chart) throw new Error("Die Grafik ist noch nicht geladen. Bitte den Reiter kurz öffnen und erneut versuchen.");
  const title=chartExportTitle(chart,canvas);
  const imageCanvas=chartCanvasWithWhiteBackground(chart);
  triggerDataUrlDownload(imageCanvas.toDataURL("image/png",1),safeExportFilename(title,"png"));
}

function exportChartAsPdf(canvas){
  const chart=Chart.getChart(canvas);
  if(!chart) throw new Error("Die Grafik ist noch nicht geladen. Bitte den Reiter kurz öffnen und erneut versuchen.");
  if(!window.jspdf?.jsPDF) throw new Error("Die PDF-Bibliothek konnte nicht geladen werden.");

  const title=chartExportTitle(chart,canvas);
  const imageCanvas=chartCanvasWithWhiteBackground(chart);
  const imageData=imageCanvas.toDataURL("image/png",1);
  const landscape=imageCanvas.width>=imageCanvas.height;
  const {jsPDF}=window.jspdf;
  const pdf=new jsPDF({orientation:landscape?"landscape":"portrait",unit:"mm",format:"a4",compress:true});
  const pageWidth=pdf.internal.pageSize.getWidth();
  const pageHeight=pdf.internal.pageSize.getHeight();
  const margin=12;
  const titleSpace=0;
  const maxWidth=pageWidth-margin*2;
  const maxHeight=pageHeight-margin*2-titleSpace;
  const ratio=Math.min(maxWidth/imageCanvas.width,maxHeight/imageCanvas.height);
  const imageWidth=imageCanvas.width*ratio;
  const imageHeight=imageCanvas.height*ratio;
  const x=(pageWidth-imageWidth)/2;
  const y=margin+titleSpace;

  // Titles and provenance are already included in the image.
  pdf.addImage(imageData,"PNG",x,y,imageWidth,imageHeight,undefined,"FAST");
  pdf.setFont("helvetica","normal");
  pdf.setFontSize(8);
  pdf.setTextColor(95,95,95);
  pdf.text(`Climate Dashboard Deutschland - Export ${new Date().toLocaleDateString("de-DE")}`,margin,pageHeight-5);
  pdf.save(safeExportFilename(title,"pdf"));
}

async function runChartExport(button,canvas,format){
  const originalText=button.textContent;
  button.disabled=true;
  button.textContent="…";
  try{
    // Ein Frame Wartezeit stellt sicher, dass eine unmittelbar aktualisierte Grafik fertig gezeichnet ist.
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    if(format==="png") exportChartAsPng(canvas);
    else exportChartAsPdf(canvas);
  }catch(error){
    console.error(error);
    alert(`Download nicht möglich: ${error.message}`);
  }finally{
    button.disabled=false;
    button.textContent=originalText;
  }
}

function initializeChartExportButtons(){
  document.querySelectorAll(".chart-container > canvas").forEach(canvas=>{
    const container=canvas.closest(".chart-container");
    if(!container || container.querySelector(`.chart-export-tools[data-canvas-id="${canvas.id}"]`)) return;
    container.classList.add("has-export-tools");
    const tools=document.createElement("div");
    tools.className="chart-export-tools";
    tools.dataset.canvasId=canvas.id;
    tools.setAttribute("aria-label","Grafik herunterladen");

    const pngButton=document.createElement("button");
    pngButton.type="button";
    pngButton.className="chart-export-button";
    pngButton.textContent="PNG";
    pngButton.title="Hochauflösendes PNG mit vollständigen Achsen";
    pngButton.addEventListener("click",()=>runChartExport(pngButton,canvas,"png"));

    const pdfButton=document.createElement("button");
    pdfButton.type="button";
    pdfButton.className="chart-export-button";
    pdfButton.textContent="PDF";
    pdfButton.title="Hochauflösendes PDF mit vollständigen Achsen";
    pdfButton.addEventListener("click",()=>runChartExport(pdfButton,canvas,"pdf"));

    const csvButton=document.createElement("button");
    csvButton.type="button";
    csvButton.className="chart-export-button";
    csvButton.textContent="CSV";
    csvButton.title="Dargestellte Daten als CSV herunterladen";
    csvButton.addEventListener("click",()=>runChartCsvExport(csvButton,canvas));

    tools.append(pngButton,pdfButton,csvButton);
    container.insertBefore(tools,canvas);
  });
}






// ================= VERSION 11: STATIONSKARTEN =================
function mapColor(value,min,max,diverging=false){
  if(!Number.isFinite(value)) return "#777";
  if(diverging){
    const limit=Math.max(Math.abs(min),Math.abs(max),1);
    const normalized=Math.max(-1,Math.min(1,value/limit));
    if(normalized<0){const t=normalized+1;return `rgb(${Math.round(33+(247-33)*t)},${Math.round(102+(247-102)*t)},${Math.round(172+(247-172)*t)})`;}
    return `rgb(${Math.round(247+(178-247)*normalized)},${Math.round(247+(24-247)*normalized)},${Math.round(247+(43-247)*normalized)})`;
  }
  const t=max===min?.5:Math.max(0,Math.min(1,(value-min)/(max-min)));
  return `rgb(${Math.round(255-(255-153)*t)},${Math.round(245-(245-0)*t)},${Math.round(235-(235-0)*t)})`;
}
function stationMetadataCoordinates(station){
  const lat=Number(station.latitude??station.lat),lon=Number(station.longitude??station.lon);
  return Number.isFinite(lat)&&Number.isFinite(lon)?[lat,lon]:null;
}
async function loadMapModeData(mode){
  if(mode==="records"){await ensureStationRecordsLoaded();return stationRecordsData;}
  if(mode==="climateDays"){await ensureStationClimateDaysLoaded();return stationClimateDaysIndex;}
  if(mode==="heatwaves"){await ensureStationHeatwavesLoaded();return stationHeatwavesIndex;}
  await ensureStationPrecipLoaded();return stationPrecipIndex;
}
function mapMetricsForMode(mode,data){
  if(mode==="records") return (data.parameters||[]).map(item=>({value:item.id,label:item.label}));
  if(mode==="climateDays") return (data.climate_days||[]).map(item=>({value:item.id,label:`${item.label} · ${item.definition}`}));
  if(mode==="heatwaves") return [{value:"current_events",label:"Zahl der Hitzewellen"},{value:"current_heatwave_days",label:"Hitzewellentage"},{value:"current_max_tmax",label:"Maximale Tmax"}];
  return [{value:"deviation_percent",label:"Abweichung in %"},{value:"current_total",label:"Niederschlagssumme"}];
}
function recordsMapPoints(data,metric,state){
  const rows=data.station_records_current_year?.[metric]||[];
  return rows.map(item=>{
    const metadata=data.stations?.[item.new?.[2]];
    if(!metadata || (state!=="Deutschland"&&metadata.state!==state)) return null;
    return {station:metadata,value:Number(item.improvement),detail:`Neuer Wert: ${item.new?.[0]} · alter Wert: ${item.old?.[0]} · ${item.new?.[1]}`,missing:0};
  }).filter(Boolean);
}
function regularMapPoints(data,metric,state,mode,maxMissing){
  return (data.stations||[]).map(station=>{
    if(state!=="Deutschland"&&station.state!==state) return null;
    const map=station.map||{};
    let value,missing=0,detail="";
    if(mode==="climateDays"){
      value=Number(map.current_counts?.[metric]);
      const valid=Number(map.valid_days?.[metric]||0),elapsed=Number(map.elapsed_days||0);missing=Math.max(0,elapsed-valid);detail=`${value||0} Tage · ${missing} fehlende Tageswerte`;
    }else if(mode==="heatwaves"){
      value=map[metric]===null?null:Number(map[metric]);detail=metric==="current_max_tmax"?`${value} °C`:`${value||0}`;
    }
    if(!Number.isFinite(value)||missing>maxMissing) return null;
    return {station,value,detail,missing};
  }).filter(Boolean);
}

function stationPrecipCurrentRangeSummaries(range){
  const result=new Map();
  const labels=stationPrecipIndex.labels||[];
  const byMonth=new Map();
  for(const payload of stationPrecipMonthCache.values()) byMonth.set(Number(payload.month),payload);
  for(let index=range.startIndex;index<=range.endIndex;index++){
    const [monthText,dayText]=labels[index].split("-");
    const payload=byMonth.get(Number(monthText));
    if(!payload) continue;
    const dayIndex=Number(dayText)-1;
    for(const [stationId,values] of Object.entries(payload.stations||{})){
      const value=values?.[dayIndex];
      let item=result.get(stationId);
      if(!item){item={total:0,valid:0};result.set(stationId,item);}
      if(value===null||value===undefined||!Number.isFinite(Number(value))) continue;
      item.total+=Number(value);item.valid+=1;
    }
  }
  for(const item of result.values()) item.total=Math.round(item.total*10)/10;
  return result;
}

function precipMapPoints(data,metric,state,maxMissing,range){
  const summaries=stationPrecipCurrentRangeSummaries(range);
  const expectedDays=range.endIndex-range.startIndex+1;
  return (data.stations||[]).map(station=>{
    if(state!=="Deutschland"&&station.state!==state) return null;
    const current=summaries.get(station.id)||{total:0,valid:0};
    const missing=Math.max(0,expectedDays-current.valid);
    if(current.valid===0||missing>maxMissing) return null;
    const map=station.map||{};
    let climate=stationPrecipRangeTotalFromCumulative(map.climate_mean_cumulative||[],range);
    // Rückwärtskompatibilität: Vor dem ersten Datenlauf mit Version 11.8 ist nur YTD im Index vorhanden.
    if(climate===null&&range.startIndex===0&&range.endIndex===((data.labels||[]).indexOf(data.data_through?.slice(5)))){
      climate=Number(map.climate_mean_to_date);
    }
    const currentTotal=current.total;
    const deviationPercent=Number.isFinite(climate)&&climate>0?Math.round((currentTotal/climate-1)*1000)/10:null;
    const value=metric==="deviation_percent"?deviationPercent:currentTotal;
    if(!Number.isFinite(value)) return null;
    const detail=metric==="deviation_percent"
      ?`${value>=0?"+":""}${stationPrecipFormat(value)} % · ${stationPrecipFormat(currentTotal)} mm · Mittel ${stationPrecipFormat(climate)} mm`
      :`${stationPrecipFormat(currentTotal)} mm · Abweichung ${deviationPercent===null?"–":`${deviationPercent>=0?"+":""}${stationPrecipFormat(deviationPercent)} %`}`;
    return {station,value,detail,missing};
  }).filter(Boolean);
}
function initializeLeafletMap(){
  if(stationMap) return;
  if(!window.L) throw new Error("Die Kartenbibliothek Leaflet konnte nicht geladen werden.");
  stationMap=L.map("stationMap").setView([51.15,10.45],6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:'&copy; OpenStreetMap-Mitwirkende'}).addTo(stationMap);
  stationMapLayer=L.layerGroup().addTo(stationMap);
}
async function updateStationMap(){
  const mode=document.getElementById("mapModeSelect").value;
  const metric=document.getElementById("mapMetricSelect").value;
  const state=document.getElementById("mapStateSelect").value;
  const maxMissing=Number(document.getElementById("mapMinCoverage").value);
  const summary=document.getElementById("mapSummary");summary.textContent="Kartendaten werden geladen …";
  try{
    const data=await loadMapModeData(mode);initializeLeafletMap();stationMapLayer.clearLayers();
    let range=null,points;
    if(mode==="records") points=recordsMapPoints(data,metric,state);
    else if(mode==="precip"){
      stationPrecipConfigureDateInputs("mapPrecip",data);
      stationPrecipToggleCustomRange("mapPrecip");
      range=stationPrecipRangeFromMapControls();
      if(!range.valid){summary.textContent=range.message;return;}
      await loadStationPrecipCurrentMonths();
      points=precipMapPoints(data,metric,state,maxMissing,range);
    }else points=regularMapPoints(data,metric,state,mode,maxMissing);
    points=points.filter(point=>stationMetadataCoordinates(point.station));
    const values=points.map(point=>point.value).filter(Number.isFinite);const min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):1;
    const diverging=mode==="precip"&&metric==="deviation_percent";
    points.forEach(point=>{
      const coords=stationMetadataCoordinates(point.station);const radius=5+8*Math.sqrt(Math.max(0,(point.value-min)/(max-min||1)));
      const color=mapColor(point.value,min,max,diverging);
      const diameter=Math.max(12,Math.round(radius*2));
      const icon=L.divIcon({
        className:"station-map-marker-icon",
        html:`<span class="station-map-marker-dot" style="width:${diameter}px;height:${diameter}px;background:${color};border:1px solid #333"></span>`,
        iconSize:[diameter,diameter],iconAnchor:[diameter/2,diameter/2],popupAnchor:[0,-diameter/2]
      });
      const marker=L.marker(coords,{icon,keyboard:true,title:point.station.name||point.station.id||"DWD-Station"});
      marker.bindPopup(`<div class="map-popup-title">${point.station.name||point.station.id}</div><div>${point.detail}</div>${range?`<div>${range.displayLabel}</div>`:""}<div class="map-popup-meta">Station ${point.station.id||"–"} · ${point.station.state||"–"} · ${point.station.height??"–"} m · ${point.missing||0} fehlende Tage</div>`);marker.addTo(stationMapLayer);
    });
    if(points.length){const bounds=L.latLngBounds(points.map(point=>stationMetadataCoordinates(point.station)));stationMap.fitBounds(bounds.pad(.08),{maxZoom:8});}
    else stationMap.setView([51.15,10.45],6);
    const periodText=range?` · ${range.displayLabel}`:"";
    summary.innerHTML=`<strong>${points.length} Stationen</strong> werden dargestellt${periodText}. Wertebereich: ${values.length?`${min.toLocaleString("de-DE")} bis ${max.toLocaleString("de-DE")}`:"keine Werte"}.`;
    document.getElementById("mapMethodNote").textContent=mode==="records"
      ?"Gezeigt werden Stationen, die im laufenden Jahr einen neuen Stationsrekord aufgestellt haben. Die Punktgröße beruht auf der Rekordverbesserung."
      :mode==="climateDays"
        ?"Die Karte zeigt die Zahl der Kenntage seit Jahresbeginn. Stationen mit zu vielen fehlenden Tageswerten können herausgefiltert werden."
        :mode==="heatwaves"
          ?"Hitzewellen entsprechen mindestens drei aufeinanderfolgenden Tagen mit Tmax ≥ 30,0 °C."
          :`Die Niederschlagskarte nutzt das erweiterte DWD-RR-Netz. Für ${range.displayLabel} wird die tatsächlich gemessene Summe mit exakt demselben Kalenderabschnitt des stationsbezogenen Mittels 1991–2020 verglichen. Fehlende Tage werden nicht als 0 mm gewertet.`;
    window.setTimeout(()=>stationMap.invalidateSize(),50);
  }catch(error){summary.textContent=`Karte nicht verfügbar: ${error.message}`;}
}
async function refreshMapControls(){
  const mode=document.getElementById("mapModeSelect").value;const summary=document.getElementById("mapSummary");summary.textContent="Kartenthema wird geladen …";
  try{
    const data=await loadMapModeData(mode);
    fillSelectOptions(document.getElementById("mapMetricSelect"),mapMetricsForMode(mode,data));
    const states=["Deutschland",...(data.states||[...new Set((data.stations?Array.isArray(data.stations)?data.stations:Object.values(data.stations):[]).map(item=>item.state).filter(Boolean))]).sort((a,b)=>a.localeCompare(b,"de"))];
    fillSelectOptions(document.getElementById("mapStateSelect"),states,"Deutschland");
    document.getElementById("mapMinCoverage").closest(".control-group").hidden=!["climateDays","precip"].includes(mode);
    document.getElementById("mapPrecipPeriodGroup").hidden=mode!=="precip";
    if(mode==="precip"){
      stationPrecipConfigureDateInputs("mapPrecip",data);
      stationPrecipToggleCustomRange("mapPrecip");
    }else document.getElementById("mapPrecipCustomRangeGroup").hidden=true;
    await updateStationMap();
  }catch(error){summary.textContent=`Kartenthema nicht verfügbar: ${error.message}`;}
}
function ensureStationMaps(){
  if(!mapsInitialized){
    mapsInitialized=true;
    document.getElementById("mapModeSelect").addEventListener("change",refreshMapControls);
    ["mapMetricSelect","mapStateSelect","mapMinCoverage"].forEach(id=>document.getElementById(id).addEventListener("change",updateStationMap));
    document.getElementById("mapPrecipPeriodSelect")?.addEventListener("change",()=>{stationPrecipToggleCustomRange("mapPrecip");updateStationMap();});
    ["mapPrecipStartDate","mapPrecipEndDate"].forEach(id=>document.getElementById(id)?.addEventListener("change",updateStationMap));
    refreshMapControls();
  }
  window.setTimeout(()=>stationMap?.invalidateSize(),80);
  window.setTimeout(()=>stationMap?.invalidateSize(),350);
}

// ================= VERSION 10: VERGLEICHSMODUS =================
let comparisonInitialized=false;
function fillSelectOptions(select,items,selected){
  if(!select) return;
  const previous=select.value;
  select.innerHTML="";
  items.forEach(item=>{
    const option=document.createElement("option");
    option.value=typeof item==="string"?item:item.value;
    option.textContent=typeof item==="string"?item:item.label;
    select.appendChild(option);
  });
  const target=selected??previous;
  if([...select.options].some(option=>option.value===String(target))) select.value=String(target);
}
function fillCompareAreaSelectors(){
  if(!monthlyData.length) return;
  const areas=availableAreas();
  fillSelectOptions(document.getElementById("compareAreaA"),areas,"Deutschland");
  fillSelectOptions(document.getElementById("compareAreaB"),areas,areas.includes("Saarland")?"Saarland":areas[1]);
  updateCompareAreas();
}
function initializeCompareYearControls(){
  if(!dailyData.length) return;
  const years=[...new Set(dailyData.map(item=>item.date.slice(0,4)))];
  fillSelectOptions(document.getElementById("compareYearA"),years,years.at(-1));
  fillSelectOptions(document.getElementById("compareYearB"),years,years.includes("2003")?"2003":years.at(-2));
  updateCompareYears();
}
function updateCompareAreas(){
  if(!monthlyData.length) return;
  const areaA=document.getElementById("compareAreaA")?.value;
  const areaB=document.getElementById("compareAreaB")?.value;
  const param=document.getElementById("compareAreaParam")?.value||"temp";
  const period=document.getElementById("compareAreaPeriod")?.value||"year";
  if(!areaA||!areaB) return;
  const a=seriesFor(areaA,period,param), b=seriesFor(areaB,period,param);
  const byA=new Map(a.map(item=>[item.year,item.value])), byB=new Map(b.map(item=>[item.year,item.value]));
  const years=[...new Set([...byA.keys(),...byB.keys()])].sort((x,y)=>x-y);
  const valuesA=years.map(year=>byA.get(year)??null), valuesB=years.map(year=>byB.get(year)??null);
  const latest=[...years].reverse().find(year=>Number.isFinite(byA.get(year))&&Number.isFinite(byB.get(year)));
  const difference=latest?byA.get(latest)-byB.get(latest):null;
  document.getElementById("compareAreaSummary").innerHTML=latest
    ?`<strong>${periodLabel(period)} ${latest}:</strong> ${areaA} ${formatValue(byA.get(latest),param)}, ${areaB} ${formatValue(byB.get(latest),param)}. Differenz A minus B: ${difference>=0?"+":""}${difference.toLocaleString("de-DE",{maximumFractionDigits:2})} ${PARAM_META[param].unit}.`
    :"Für beide Gebiete liegt noch kein gemeinsamer Wert vor.";
  if(compareAreaChart) compareAreaChart.destroy();
  compareAreaChart=new Chart(document.getElementById("compareAreaChart"),{
    type:"line",data:{labels:years,datasets:[
      {label:areaA,data:valuesA,borderColor:"#c92a2a",backgroundColor:"#c92a2a",borderWidth:2.5,pointRadius:1.5,tension:.1},
      {label:areaB,data:valuesB,borderColor:"#1864ab",backgroundColor:"#1864ab",borderWidth:2.5,pointRadius:1.5,tension:.1}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`${PARAM_META[param].label}: ${areaA} und ${areaB} – ${periodLabel(period)}`},datalabels:{display:false},zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}}},scales:{x:{ticks:{maxTicksLimit:18}},y:{title:{display:true,text:PARAM_META[param].unit}}}}
  });
}
function updateCompareYears(){
  if(!dailyData.length) return;
  const yearA=document.getElementById("compareYearA")?.value, yearB=document.getElementById("compareYearB")?.value;
  const range=document.getElementById("compareYearRange")?.value||"summer";
  if(!yearA||!yearB) return;
  const dataA=dailyPeriodFilter(yearA,range), dataB=dailyPeriodFilter(yearB,range);
  const mapA=new Map(dataA.map(item=>[dailyCalendarKey(item.date),dailyNumber(item.tmax)]));
  const mapB=new Map(dataB.map(item=>[dailyCalendarKey(item.date),dailyNumber(item.tmax)]));
  const keys=[...new Set([...mapA.keys(),...mapB.keys()])].sort();
  const valuesA=keys.map(key=>mapA.get(key)??null),valuesB=keys.map(key=>mapB.get(key)??null);
  const meanA=dailyAverage(valuesA),meanB=dailyAverage(valuesB);
  document.getElementById("compareYearSummary").innerHTML=`<strong>${dailyRangeLabel(range)}:</strong> mittleres Deutschland-Tagesmaximum ${yearA}: ${Number.isFinite(meanA)?meanA.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–"} °C; ${yearB}: ${Number.isFinite(meanB)?meanB.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–"} °C.`;
  if(compareYearChart) compareYearChart.destroy();
  compareYearChart=new Chart(document.getElementById("compareYearChart"),{
    type:"line",data:{labels:keys,datasets:[
      {label:yearA,data:valuesA,borderColor:"#c92a2a",borderWidth:2.3,pointRadius:0,tension:0},
      {label:yearB,data:valuesB,borderColor:"#1864ab",borderWidth:2.3,pointRadius:0,tension:0}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`Tageshöchstwerte: ${yearA} und ${yearB} – ${dailyRangeLabel(range)}`},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:14}},y:{title:{display:true,text:"Tageshöchsttemperatur (°C)"}}}}
  });
}
async function comparisonSourceIndex(source){
  if(source==="precip"){await ensureStationPrecipLoaded();return stationPrecipIndex;}
  if(source==="climateDays"){await ensureStationClimateDaysLoaded();return stationClimateDaysIndex;}
  await ensureStationHeatwavesLoaded();return stationHeatwavesIndex;
}
function destroyCompareStationChart(){
  const canvas=document.getElementById("compareStationChart");
  const registered=canvas&&typeof Chart.getChart==="function"?Chart.getChart(canvas):null;
  if(registered){
    try{registered.destroy();}catch(_error){}
  }
  if(compareStationChart&&compareStationChart!==registered){
    try{compareStationChart.destroy();}catch(_error){}
  }
  compareStationChart=null;
}
function renderCompareStationChart(config,requestId){
  if(requestId!==compareStationRequestId) return false;
  const canvas=document.getElementById("compareStationChart");
  if(!canvas) return false;
  destroyCompareStationChart();
  if(requestId!==compareStationRequestId) return false;
  compareStationChart=new Chart(canvas,config);
  return true;
}
async function populateCompareStations(){
  const populateRequestId=++compareStationPopulateRequestId;
  compareStationRequestId++;
  destroyCompareStationChart();
  const source=document.getElementById("compareStationSource").value;
  const summary=document.getElementById("compareStationSummary");
  summary.textContent="Stationsliste wird geladen …";
  try{
    const index=await comparisonSourceIndex(source);
    if(populateRequestId!==compareStationPopulateRequestId||source!==document.getElementById("compareStationSource").value) return;
    const stations=(index.stations||[]).slice().sort((a,b)=>(a.state||"").localeCompare(b.state||"","de")||a.name.localeCompare(b.name,"de"));
    const options=stations.map(station=>({value:station.id,label:`${station.name} (${station.id}) · ${station.state||"ohne Bundesland"}`}));
    fillSelectOptions(document.getElementById("compareStationA"),options,options[0]?.value);
    fillSelectOptions(document.getElementById("compareStationB"),options,options[1]?.value||options[0]?.value);
    const metricGroup=document.getElementById("compareStationMetricGroup");
    metricGroup.hidden=source!=="climateDays";
    if(source==="climateDays"){
      fillSelectOptions(document.getElementById("compareStationMetric"),(index.climate_days||[]).map(metric=>({value:metric.id,label:`${metric.label} · ${metric.definition}`})),"hot");
    }
    await updateCompareStations();
  }catch(error){
    if(populateRequestId===compareStationPopulateRequestId) summary.textContent=`Stationsvergleich nicht verfügbar: ${error.message}`;
  }
}
async function updateCompareStations(){
  const requestId=++compareStationRequestId;
  const source=document.getElementById("compareStationSource").value;
  const idA=document.getElementById("compareStationA").value,idB=document.getElementById("compareStationB").value;
  if(!idA||!idB){destroyCompareStationChart();return;}
  const summary=document.getElementById("compareStationSummary");
  summary.textContent="Vergleichsdaten werden geladen …";
  destroyCompareStationChart();
  const index=await comparisonSourceIndex(source);
  if(requestId!==compareStationRequestId) return;
  const stationA=index.stations.find(item=>item.id===idA),stationB=index.stations.find(item=>item.id===idB);
  if(!stationA||!stationB) return;
  if(source==="precip"){
    await loadStationPrecipCurrentMonths();
    if(requestId!==compareStationRequestId) return;
    const [profileA,profileB]=await Promise.all([stationA,stationB].map(async station=>{const response=await dashboardFetch(station.file,{cache:"no-store"});if(!response.ok) throw new Error(`${station.name}: HTTP ${response.status}`);return response.json();}));
    if(requestId!==compareStationRequestId) return;
    const labels=index.labels||[];
    const currentA=stationPrecipCumulativeWithGaps(stationPrecipCurrentDaily(idA),labels,index.data_through);
    const currentB=stationPrecipCumulativeWithGaps(stationPrecipCurrentDaily(idB),labels,index.data_through);
    const lastA=currentA.findLastIndex?.(Number.isFinite)??currentA.reduce((last,v,i)=>Number.isFinite(v)?i:last,-1);
    const lastB=currentB.findLastIndex?.(Number.isFinite)??currentB.reduce((last,v,i)=>Number.isFinite(v)?i:last,-1);
    summary.innerHTML=`<strong>${stationA.name}:</strong> ${lastA>=0?currentA[lastA].toLocaleString("de-DE",{maximumFractionDigits:1}):"–"} mm · <strong>${stationB.name}:</strong> ${lastB>=0?currentB[lastB].toLocaleString("de-DE",{maximumFractionDigits:1}):"–"} mm bis ${dailyGermanDate(index.data_through,true)}.`;
    renderCompareStationChart({type:"line",data:{labels,datasets:[
      {label:`${stationA.name} ${index.current_year}`,data:currentA,borderColor:"#c92a2a",borderWidth:2.6,pointRadius:0,spanGaps:true},
      {label:`${stationA.name} Mittel`,data:profileA.climate_mean_cumulative||[],borderColor:"rgba(201,42,42,.55)",borderDash:[6,5],borderWidth:1.7,pointRadius:0},
      {label:`${stationB.name} ${index.current_year}`,data:currentB,borderColor:"#1864ab",borderWidth:2.6,pointRadius:0,spanGaps:true},
      {label:`${stationB.name} Mittel`,data:profileB.climate_mean_cumulative||[],borderColor:"rgba(24,100,171,.55)",borderDash:[6,5],borderWidth:1.7,pointRadius:0}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:"Kumulativer Stationsniederschlag im Vergleich"},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:14}},y:{title:{display:true,text:"Niederschlagssumme (mm)"}}}}},requestId);
  }else if(source==="climateDays"){
    await loadStationClimateDaysCurrentMonths();
    if(requestId!==compareStationRequestId) return;
    const metricId=document.getElementById("compareStationMetric").value;
    const metric=(index.climate_days||[]).find(item=>item.id===metricId);
    const [profileA,profileB]=await Promise.all([stationA,stationB].map(async station=>{const response=await dashboardFetch(station.file,{cache:"no-store"});if(!response.ok) throw new Error(`${station.name}: HTTP ${response.status}`);return response.json();}));
    if(requestId!==compareStationRequestId) return;
    const curveA=stationClimateDaysCurrentCumulative(idA,metric),curveB=stationClimateDaysCurrentCumulative(idB,metric);
    summary.innerHTML=`<strong>${metric?.label||metricId} ${index.current_year}:</strong> ${stationA.name} ${curveA.count}, ${stationB.name} ${curveB.count}.`;
    renderCompareStationChart({type:"line",data:{labels:index.labels||[],datasets:[
      {label:`${stationA.name} ${index.current_year}`,data:curveA,borderColor:"#c92a2a",borderWidth:2.6,pointRadius:0,spanGaps:true},
      {label:`${stationA.name} Mittel`,data:profileA.climate_mean_cumulative?.[metricId]||[],borderColor:"rgba(201,42,42,.55)",borderDash:[6,5],borderWidth:1.7,pointRadius:0},
      {label:`${stationB.name} ${index.current_year}`,data:curveB,borderColor:"#1864ab",borderWidth:2.6,pointRadius:0,spanGaps:true},
      {label:`${stationB.name} Mittel`,data:profileB.climate_mean_cumulative?.[metricId]||[],borderColor:"rgba(24,100,171,.55)",borderDash:[6,5],borderWidth:1.7,pointRadius:0}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`${metric?.label||"Kenntage"}: kumulativer Stationsvergleich`},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:14}},y:{beginAtZero:true,title:{display:true,text:"Anzahl Tage"}}}}},requestId);
  }else{
    const [profileA,profileB]=await Promise.all([stationA,stationB].map(async station=>{const response=await dashboardFetch(station.file,{cache:"no-store"});if(!response.ok) throw new Error(`${station.name}: HTTP ${response.status}`);return response.json();}));
    if(requestId!==compareStationRequestId) return;
    const annualA=new Map((profileA.annual||[]).map(item=>[Number(item[0]),Number(item[1])])),annualB=new Map((profileB.annual||[]).map(item=>[Number(item[0]),Number(item[1])]));
    annualA.set(Number(index.current_year),stationHeatwavesCurrent?.stations?.[idA]?.events?.length||0);
    annualB.set(Number(index.current_year),stationHeatwavesCurrent?.stations?.[idB]?.events?.length||0);
    const years=[...new Set([...annualA.keys(),...annualB.keys()])].sort((a,b)=>a-b);
    summary.innerHTML=`<strong>Hitzewellen ${index.current_year}:</strong> ${stationA.name} ${annualA.get(Number(index.current_year))||0}, ${stationB.name} ${annualB.get(Number(index.current_year))||0}.`;
    renderCompareStationChart({type:"line",data:{labels:years,datasets:[
      {label:stationA.name,data:years.map(year=>annualA.get(year)??null),borderColor:"#c92a2a",borderWidth:2.3,pointRadius:2,spanGaps:false},
      {label:stationB.name,data:years.map(year=>annualB.get(year)??null),borderColor:"#1864ab",borderWidth:2.3,pointRadius:2,spanGaps:false}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:"Zahl der Stations-Hitzewellen pro Jahr"},datalabels:{display:false},zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}}},scales:{x:{ticks:{maxTicksLimit:18}},y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Hitzewellen"}}}}},requestId);
  }
  if(requestId===compareStationRequestId) initializeChartExportButtons();
}
function ensureComparisonMode(){
  if(comparisonInitialized){updateCompareAreas();updateCompareYears();return;}
  comparisonInitialized=true;
  ["compareAreaA","compareAreaB","compareAreaParam","compareAreaPeriod"].forEach(id=>document.getElementById(id)?.addEventListener("change",updateCompareAreas));
  ["compareYearA","compareYearB","compareYearRange"].forEach(id=>document.getElementById(id)?.addEventListener("change",updateCompareYears));
  document.getElementById("compareStationSource")?.addEventListener("change",populateCompareStations);
  ["compareStationA","compareStationB","compareStationMetric"].forEach(id=>document.getElementById(id)?.addEventListener("change",()=>updateCompareStations().catch(error=>document.getElementById("compareStationSummary").textContent=error.message)));
  fillCompareAreaSelectors();initializeCompareYearControls();populateCompareStations();
}

