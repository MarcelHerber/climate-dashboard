/* core.js – Zustand, Navigation, Hilfsfunktionen
   Aus index.html ausgelagert (Schritt 2a). Klassisches Skript, gemeinsamer globaler Scope. */

Chart.register(ChartDataLabels);
// Native Canvas-Auflösung verwenden, auf maximal 2× begrenzt.
Chart.defaults.devicePixelRatio=Math.min(2,window.devicePixelRatio||1);

const DASHBOARD_STATE_KEY="climateDashboardStateV9";
let dashboardState={};
try{dashboardState=JSON.parse(localStorage.getItem(DASHBOARD_STATE_KEY)||"{}");}catch(_error){dashboardState={};}
const dashboardUrl=new URL(window.location.href);
for(const [key,value] of dashboardUrl.searchParams.entries()){
  if(key==="tab") dashboardState.tab=value;
  else if(key.startsWith("s_")) dashboardState[key.slice(2)]=value;
}

const MONTH_NAMES = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const MONTH_SHORT = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const PERIOD_OPTIONS = [
  {group:"Monate", value:"01", label:"Januar"},
  {group:"Monate", value:"02", label:"Februar"},
  {group:"Monate", value:"03", label:"März"},
  {group:"Monate", value:"04", label:"April"},
  {group:"Monate", value:"05", label:"Mai"},
  {group:"Monate", value:"06", label:"Juni"},
  {group:"Monate", value:"07", label:"Juli"},
  {group:"Monate", value:"08", label:"August"},
  {group:"Monate", value:"09", label:"September"},
  {group:"Monate", value:"10", label:"Oktober"},
  {group:"Monate", value:"11", label:"November"},
  {group:"Monate", value:"12", label:"Dezember"},
  {group:"Jahreszeiten", value:"spring", label:"Frühling (MAM)"},
  {group:"Jahreszeiten", value:"summer", label:"Sommer (JJA)"},
  {group:"Jahreszeiten", value:"autumn", label:"Herbst (SON)"},
  {group:"Jahreszeiten", value:"winter", label:"Winter (DJF)"},
  {group:"Gesamt", value:"year", label:"Ganzes Jahr"}
];
const PARAM_META = {
  temp:{label:"Temperatur", unit:"°C", decimals:2},
  rain:{label:"Niederschlag", unit:"mm", decimals:1},
  sun:{label:"Sonnenscheindauer", unit:"h", decimals:1}
};
const AREA_ORDER = [
  "Deutschland","Baden-Württemberg","Bayern","Brandenburg","Brandenburg/Berlin",
  "Hessen","Mecklenburg-Vorpommern","Niedersachsen","Niedersachsen/Hamburg/Bremen",
  "Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt",
  "Schleswig-Holstein","Thüringen","Thüringen/Sachsen-Anhalt"
];

let monthlyData=[];
let dailyData=[];
let monthlyChart=null;
let monthlyDeviationChart=null;
let regionalMap=null;
let regionalMapB=null;
let regionalMapDiff=null;
let regionalMapLayer=null;
let regionalMapLayerB=null;
let regionalMapLayerDiff=null;
let regionalMapGeoJson=null;
let regionalMapGeoPromise=null;
let regionalMapHoverTooltip=null;
let regionalMapHoverTooltipB=null;
let regionalMapHoverTooltipDiff=null;
let regionalDetailChart=null;
let regionalDetailDiffChart=null;
let regionalDetailArea="Deutschland";
let regionalDetailDisplayName="Deutschland";
let climateIndexChart=null;
let accumulationChart=null;
let dailyChart=null;
let dailyDeviationChart=null;
let dailyAllYearsChart=null;
let currentConditionsChart=null;
let currentWindChart=null;
let currentPrecipChart=null;
let currentLiveIndex=null;
let currentFastIndex=null;
let currentFastByStation=new Map();
let currentLiveProfile=null;
let currentLiveLoading=null;
let currentLiveLastFetch=0;
let currentLiveMap=null;
let currentLiveMapLayer=null;
let currentLiveMapBoundaryLayer=null;
let currentLiveMapBoundaryData=null;
let currentLiveMapBoundaryPromise=null;
const CURRENT_LIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/live-data";
const CURRENT_FAST_LIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/fast-live";
const CURRENT_MAP_BOUNDARY_URL="https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json";
const HYRAS_DATA_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-data";
let hyrasRankRenderToken=0;
const HYRAS_RANK_PERIODS=[
  {key:"day",imageId:"hyrasRankDayImage",placeholderId:"hyrasRankDayPlaceholder",openId:"hyrasRankDayOpen"},
  {key:"month_to_date",imageId:"hyrasRankMonthImage",placeholderId:"hyrasRankMonthPlaceholder",openId:"hyrasRankMonthOpen"},
  {key:"summer_to_date",imageId:"hyrasRankSummerImage",placeholderId:"hyrasRankSummerPlaceholder",openId:"hyrasRankSummerOpen"}
];
let hyrasIndex=null;
let hyrasLoading=null;
let hyrasLastFetch=0;
let hyrasWebManifest=null;
let hyrasCustomState=null;
let hyrasHistoricalManifest=null;
let hyrasHistoricalState=null;
let hyrasPresetState=null;
let hyrasLivePresetState=null;
let hyrasTmeanIndex=null;
let hyrasTmeanHistoryManifest=null;
let hyrasTmeanHistoricalState=null;
const hyrasTmeanFileCache=new Map();
const hyrasTmeanMonthCache=new Map();
// HYRAS_TMEAN_PERFORMANCE_V1
const HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR=2;
let hyrasTmeanBoundaryBitmapPromise=null;
let hyrasTmeanExportObjectUrl=null;
// HYRAS_TMEAN_REGION_CURVES_V1
let hyrasTmeanRegionsIndex=null;
let hyrasTmeanRegionsCurrent=null;
let hyrasTmeanRegionsClimate=null;
let hyrasTmeanRegionsClimateReference=null;
let hyrasTmeanMapDownloads=null;
// HYRAS_TMEAN_DAILY_RECORDS_V1
let hyrasTmeanRegionsRecords=null;
let hyrasTmeanRegionChart=null;
let hyrasTemperatureRenderGeneration=0;
function hyrasTemperatureRenderStart(parameter){
  const generation=++hyrasTemperatureRenderGeneration,reference=hyrasReferencePeriod();
  const frame=document.getElementById("hyrasMapFrame");
  if(frame)frame.innerHTML='<div class="hyras-loading">Temperaturdaten werden geladen …</div>';
  return ()=>generation===hyrasTemperatureRenderGeneration&&hyrasParameter()===parameter&&hyrasReferencePeriod()===reference;
}
let hyrasTmeanRegionsLoading=null;
let hyrasPointChart=null;
let hyrasClickSeriesManifest=null;
let hyrasSelectedGridPoint=null;
let hyrasPointRequest=0;
const hyrasClickSeriesPackCache=new Map();
const hyrasWebImageCache=new Map();
const hyrasGeoLookupCache=new Map();
let extremeCumulativeChart=null;
let yearlyExtremeChart=null;
let yearlyMaxChart=null;
let heatmapChart=null;
let stationPrecipChart=null;
let stationPrecipDeviationChart=null;
let stationPrecipIndex=null;
let stationPrecipLoading=null;
let stationPrecipProfile=null;
const stationPrecipMonthCache=new Map();
let stationSnowIndex=null;
let stationSnowCurrentIndex=null;
let stationSnowCurrentById=new Map();
let stationSnowStationById=new Map();
let stationSnowLoading=null;
let stationSnowProfile=null;
let stationSnowCurrent=null;
let stationSnowChart=null;
let stationSnowDeviationChart=null;
let stationSnowRequestId=0;
let stationSnowYearsArchive=null;
let stationSnowYearStationId=null;
let stationSnowAvailableYears=[];
const stationSnowSelectedYears=new Set();
const stationSnowFileCache=new Map();
let stationClimateDaysIndex=null;
let stationClimateDaysLoading=null;
let stationClimateDaysProfile=null;
let stationClimateDaysCumulativeChart=null;
let stationClimateDaysBarChart=null;
let stationClimateDaysTemperatureFrequencyChart=null;
let stationClimateDaysSnowFrequencyChart=null;
let stationClimateDaysSnowFrequencyIndex=null;
const stationClimateDaysSnowFrequencyProfileCache=new Map();
let stationClimateDaysFrequencyRequest=0;
const stationClimateDaysMonthCache=new Map();
let stationHeatwavesIndex=null;
let stationHeatwavesCurrent=null;
let stationHeatwavesLoading=null;
let stationHeatwavesProfile=null;
let stationHeatwavesBubbleChart=null;
let stationHeatwavesBarChart=null;
let compareAreaChart=null;
let compareYearChart=null;
let compareStationChart=null;
let compareStationRequestId=0;
let compareStationPopulateRequestId=0;
let stationMap=null;
let stationMapLayer=null;
let stationMapLegend=null;
let mapsInitialized=false;


let era5EuropeIndex=null;
let era5EuropeLoading=null;
let era5RunningTemperatureRanks=null;
let era5RunningTemperatureRanksLoading=null;
let era5RunningTemperatureRanksDisplay=null;
let era5RunningTemperatureRankProduct="day";
let era5RunningRankDates=[];
let era5RunningRankDateIndex=-1;
let era5RunningRankPlayTimer=null;
let era5RunningRankPlayBusy=false;
const era5RunningRankArchiveCache=new Map();
const ERA5_RUNNING_TEMPERATURE_RANKS_INDEX="era5_land_europe/running/temperature_ranks/index.json";
let era5EuropeAnalysis=null;
let era5EuropeAnalysisLoading=null;
let era5EuropeSelectedPoint=null;
let era5EuropePointMonthlyChart=null;
let era5EuropePointHistoryChart=null;
let era5EuropeHistoricalEntries=[];
let era5EuropeHistoricalScale=null;
let era5EuropeHistoricalRaster=null;
let era5EuropeHighresArchive=null;
let era5EuropeHighresArchiveLoading=null;
const era5EuropeHighresPackCache=new Map();
const era5EuropeHighresReferenceCache=new Map();
let era5EuropeRankingRequest=0;
let era5EuropeRankingPoints=[];
const ERA5_EUROPE_RAW_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/";
let europeStationMap=null;
let europeStationLayer=null;
let europeStationLoading=null;
let europeStationLoaded=false;
let europeStationData=null;
let europeStationRenderer=null;
let europeStationRenderToken=0;
let europeStationMarkerById=new Map();
let europeStationLastRows=[];
let europeStationSearchTimer=null;
const europeStationCalendarCache=new Map();
const EUROPE_STATION_RAW_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/";
const EUROPE_STATION_DATA_URL="europe_stations/index.json";
let stationRecordsData=null;
let stationRecordsLoading=null;
let stationStreakIndex=null;
let stationStreakLoading=null;
let nationalStreakMap=null;
let nationalStreakMapLayer=null;
const stationYearCache=new Map();

let stationObservationsIndex=null;
let stationObservationsIndexLoading=null;
let stationObservationsPayload=null;
let stationObservationsChart=null;
let stationObservationsRequestId=0;

let overviewMap=null;
let overviewMapLayer=null;
let overviewMapParam="temp";
let overviewStatusPayload=null;

function showError(message){
  const box=document.getElementById("loadError");
  box.style.display="block";
  box.textContent=message;
}

function updatePrimaryNavigation(tab){
  document.querySelectorAll(".nav-dropdown").forEach(dropdown=>{
    const group=dropdown.dataset.navGroup;
    const active=Boolean(dropdown.querySelector(`.tab-button.active[data-nav-group="${group}"]`));
    dropdown.classList.toggle("group-active",active);
  });
  document.querySelectorAll(".nav-link[data-nav-group]").forEach(link=>{
    if(link.classList.contains("tab-button")) link.classList.toggle("active",link.getAttribute("onclick")?.includes(`'${tab}'`));
  });
}
function closeNavigationDropdowns(){
  document.querySelectorAll(".nav-dropdown.open").forEach(dropdown=>{
    dropdown.classList.remove("open");
    dropdown.querySelector(".nav-dropdown-toggle")?.setAttribute("aria-expanded","false");
  });
}

async function openAlpenwetter(){
  closeNavigationDropdowns();
  try{
    const response=await fetch("data/alpenwetter_endpoint.json",{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload=await response.json();
    const target=new URL(String(payload?.url||""),window.location.href);

    const validHost=
      target.protocol==="https:" &&
      target.hostname.startsWith("climate-dashboard-alpenwetter.") &&
      target.hostname.endsWith(".workers.dev");

    if(!validHost) throw new Error("Unerwartete Zieladresse");
    window.location.href=target.href;
  }catch(error){
    showError(
      "Der geschützte Alpenwetter-Bereich konnte gerade nicht geöffnet werden. " +
      "Bitte prüfe, ob der Alpenwetter-Worker bereits erfolgreich veröffentlicht wurde."
    );
    console.error("Alpenwetter-Link:",error);
  }
}

function switchTab(tab,{persist=true}={}){
  const target=document.getElementById(tab);
  if(!target) tab="overview";
  document.querySelectorAll(".tab-button").forEach(b=>b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c=>c.classList.remove("active"));
  const button=document.querySelector(`[onclick="switchTab('${tab}')"]`);
  if(button) button.classList.add("active");
  document.getElementById(tab)?.classList.add("active");
  updatePrimaryNavigation(tab);
  closeNavigationDropdowns();
  const mobile=document.getElementById("mobileTabSelect");
  if(mobile) mobile.value=tab;
  if(persist) persistDashboardState("tab",tab);
  if(tab==="overview"){
    renderOverview();
  }
  if(tab==="daily"||tab==="extremes"||tab==="compare") ensureDailyDashboardLoaded();
  if(tab==="current") ensureCurrentConditions();
  if(tab==="stationObservations") ensureStationObservationsLoaded();
  if(tab==="hyras") ensureHyrasLoaded();
  if(tab==="era5Europe"){ensureEra5EuropeLoaded();ensureEra5RunningTemperatureRanksLoaded().catch(()=>{});}
  if(tab==="era5Atmosphere") ensureEra5AtmosphereLoaded();
  if(tab==="era5Synoptic") ensureEra5SynopticLoaded();
  if(tab==="europeStations") ensureEuropeStationMap();
  if(tab==="state-monthly-ensemble") window.ensureStateMonthlyEnsembleLoaded?.();
  if(tab==="gebietsmittelArchive") window.ensureGebietsmittelArchiveLoaded?.(monthlyData);
  if(tab==="monthly") window.setTimeout(()=>{
    updateMonthly();
    updateMonthlyAnomalyTable();
    updateMonthlyAbsoluteAnomalyTable();
    updateClimateIndex();
    updateAccumulation();
    updateRegionalMap();
    if(regionalMap) regionalMap.invalidateSize();
  },80);
  if(tab==="index") updateClimateIndex();
  if(tab==="stationProfile") ensureStationProfile();
  if(tab==="stationPrecip") ensureStationPrecipLoaded();
  if(tab==="stationSnow") ensureStationSnowLoaded();
  if(tab==="stationClimateDays") ensureStationClimateDaysLoaded();
  if(tab==="stationHeatwaves") ensureStationHeatwavesLoaded();
  if(tab==="compare") ensureComparisonMode();
  if(tab==="maps") ensureStationMaps();
  if(tab==="records"){
    ensureStationRecordsLoaded();
    ensureStationStreaksLoaded();
  }
  window.setTimeout(()=>{
    [monthlyChart,monthlyDeviationChart,climateIndexChart,accumulationChart,currentConditionsChart,stationObservationsChart,stationPrecipChart,stationPrecipDeviationChart,stationSnowChart,stationSnowDeviationChart,window.stationSnowAccumulationChart,stationClimateDaysCumulativeChart,stationClimateDaysBarChart,stationHeatwavesBubbleChart,stationHeatwavesBarChart,compareAreaChart,compareYearChart,compareStationChart,dailyChart,dailyDeviationChart,dailyAllYearsChart,extremeCumulativeChart,yearlyExtremeChart,yearlyMaxChart,heatmapChart]
      .filter(Boolean).forEach(chart=>chart.resize());
  },50);
}

function populatePeriodSelect(select, defaultValue){
  select.innerHTML="";
  const groups={};
  PERIOD_OPTIONS.forEach(item=>{
    if(!groups[item.group]){
      groups[item.group]=document.createElement("optgroup");
      groups[item.group].label=item.group;
      select.appendChild(groups[item.group]);
    }
    const option=document.createElement("option");
    option.value=item.value;
    option.textContent=item.label;
    groups[item.group].appendChild(option);
  });
  select.value=defaultValue;
}

document.querySelectorAll(".period-select").forEach(select=>populatePeriodSelect(select,"07"));

function normalizeMonthly(raw){
  if(Array.isArray(raw)){
    return raw.map(item=>({
      area:item.area || "Deutschland",
      date:item.date,
      rain:item.rain ?? null,
      temp:item.temp ?? null,
      sun:item.sun ?? null
    }));
  }
  throw new Error("data.json besitzt kein unterstütztes Format.");
}

function availableAreas(){
  const found=[...new Set(monthlyData.map(item=>item.area))];
  return found.sort((a,b)=>{
    const ai=AREA_ORDER.indexOf(a);
    const bi=AREA_ORDER.indexOf(b);
    if(ai===-1 && bi===-1) return a.localeCompare(b,"de");
    if(ai===-1) return 1;
    if(bi===-1) return -1;
    return ai-bi;
  });
}

function fillAreaSelectors(){
  const areas=availableAreas();
  ["monthlyAreaSelect","indexAreaSelect","accAreaSelect"].forEach(id=>{
    const select=document.getElementById(id);
    const previous=select.value;
    select.innerHTML="";
    areas.forEach(area=>{
      const option=document.createElement("option");
      option.value=area;
      option.textContent=area;
      select.appendChild(option);
    });
    select.value=areas.includes(previous)?previous:(areas.includes("Deutschland")?"Deutschland":areas[0]);
  });
}

function synchronizeArea(sourceId){
  const value=document.getElementById(sourceId).value;
  ["monthlyAreaSelect","indexAreaSelect","accAreaSelect"].forEach(id=>{
    if(id!==sourceId && [...document.getElementById(id).options].some(o=>o.value===value)){
      document.getElementById(id).value=value;
    }
  });
}

function areaRows(area){
  return monthlyData.filter(item=>item.area===area);
}

function daysInMonth(year,month){
  return new Date(year,month,0).getDate();
}

function periodKeys(year,selection){
  const y=Number(year);
  if(/^\d{2}$/.test(selection)) return [{year:y,month:Number(selection)}];
  if(selection==="spring") return [3,4,5].map(month=>({year:y,month}));
  if(selection==="summer") return [6,7,8].map(month=>({year:y,month}));
  if(selection==="autumn") return [9,10,11].map(month=>({year:y,month}));
  if(selection==="winter") return [{year:y-1,month:12},{year:y,month:1},{year:y,month:2}];
  return Array.from({length:12},(_,index)=>({year:y,month:index+1}));
}

function aggregatePeriod(rows,year,selection,param){
  const byDate=new Map(rows.map(item=>[item.date,item]));
  const keys=periodKeys(year,selection);
  const entries=keys.map(key=>byDate.get(`${key.year}-${String(key.month).padStart(2,"0")}`));
  if(entries.some(entry=>!entry || entry[param]===null || entry[param]===undefined)) return null;

  if(param==="temp"){
    let weighted=0;
    let totalDays=0;
    entries.forEach((entry,index)=>{
      const key=keys[index];
      const days=daysInMonth(key.year,key.month);
      weighted+=entry.temp*days;
      totalDays+=days;
    });
    return weighted/totalDays;
  }
  return entries.reduce((sum,entry)=>sum+entry[param],0);
}

function seriesFor(area,selection,param){
  const rows=areaRows(area);
  const years=[...new Set(rows.map(item=>Number(item.date.slice(0,4))))].sort((a,b)=>a-b);
  return years.map(year=>({year,value:aggregatePeriod(rows,year,selection,param)}))
    .filter(item=>item.value!==null && Number.isFinite(item.value));
}

function mean(values){
  if(!values.length) return null;
  return values.reduce((sum,value)=>sum+value,0)/values.length;
}

function monthlyReferencePeriod(){
  const select=document.getElementById("monthlyReferenceSelect");
  let start=1991;
  let end=2020;
  if(select?.value==="custom"){
    start=Math.round(Number(document.getElementById("monthlyReferenceStart")?.value));
    if(!Number.isFinite(start)) start=1951;
    start=Math.max(1881,Math.min(1997,start));
    end=start+29;
  }else if(select?.value && /^\d{4}-\d{4}$/.test(select.value)){
    [start,end]=select.value.split("-").map(Number);
  }
  return {start,end,label:`${start}–${end}`};
}

function monthlyReferenceMean(series,reference=monthlyReferencePeriod()){
  const values=series.filter(item=>item.year>=reference.start && item.year<=reference.end && Number.isFinite(item.value));
  // Eine 30-jährige Referenz sollte praktisch vollständig sein. 29 Werte werden toleriert,
  // damit z. B. der Winter 1881 wegen des fehlenden Dezember 1880 nicht die gesamte Periode sperrt.
  return values.length>=29?mean(values.map(item=>item.value)):null;
}

function monthlyReferenceMeanForPeriod(byDate,period,param,reference=monthlyReferencePeriod()){
  const values=[];
  for(let year=reference.start;year<=reference.end;year++){
    const value=aggregatePeriodFromMap(byDate,year,period,param);
    if(Number.isFinite(value)) values.push(value);
  }
  return values.length>=29?mean(values):null;
}

function updateMonthlyReferenceUi(){
  const reference=monthlyReferencePeriod();
  const custom=document.getElementById("monthlyReferenceCustomGroup");
  if(custom) custom.hidden=document.getElementById("monthlyReferenceSelect")?.value!=="custom";
  const meanTitle=document.getElementById("monthlyClimateMeanTitle");
  const anomalyTitle=document.getElementById("monthlyAnomalyTitle");
  const absoluteTitle=document.getElementById("monthlyAbsoluteAnomalyTitle");
  if(meanTitle) meanTitle.textContent=`Mittel ${reference.label}`;
  if(anomalyTitle) anomalyTitle.textContent=`Abweichungstabelle ${reference.label}`;
  if(absoluteTitle) absoluteTitle.textContent=`Absolute Abweichung ${reference.label}`;
  return reference;
}

function monthlyRollingWindow(){
  const select=document.getElementById("monthlyRollingSelect");
  if(!select || select.value==="0") return 0;
  if(select.value==="custom"){
    let years=Math.round(Number(document.getElementById("monthlyRollingYears")?.value));
    if(!Number.isFinite(years)) years=15;
    return Math.max(2,Math.min(60,years));
  }
  const years=Number(select.value);
  return Number.isFinite(years)?years:0;
}

function updateMonthlyRollingUi(){
  const custom=document.getElementById("monthlyRollingCustomGroup");
  if(custom) custom.hidden=document.getElementById("monthlyRollingSelect")?.value!=="custom";
  return monthlyRollingWindow();
}

function monthlyRollingSeries(values,windowYears){
  if(!windowYears) return values.map(()=>null);
  const byYear=new Map(values.map(item=>[Number(item.year),item.value]));
  return values.map(item=>{
    const endYear=Number(item.year);
    const window=[];
    for(let year=endYear-windowYears+1;year<=endYear;year++){
      const value=byYear.get(year);
      if(!Number.isFinite(value)) return null;
      window.push(value);
    }
    return mean(window);
  });
}

function monthlyRollingColor(param){
  if(param==="rain") return "#2f6f44";
  if(param==="sun") return "#a86b00";
  return "#245b7a";
}

function stdDev(values){
  if(values.length<2) return null;
  const avg=mean(values);
  return Math.sqrt(values.reduce((sum,value)=>sum+(value-avg)**2,0)/(values.length-1));
}

function percentile(values,p){
  if(!values.length) return null;
  const sorted=[...values].sort((a,b)=>a-b);
  const position=(sorted.length-1)*p;
  const lower=Math.floor(position);
  const upper=Math.ceil(position);
  if(lower===upper) return sorted[lower];
  return sorted[lower]+(sorted[upper]-sorted[lower])*(position-lower);
}

function periodLabel(selection){
  return PERIOD_OPTIONS.find(item=>item.value===selection)?.label || selection;
}

function formatValue(value,param,withUnit=true){
  if(value===null || !Number.isFinite(value)) return "–";
  const meta=PARAM_META[param];
  const text=value.toLocaleString("de-DE",{minimumFractionDigits:meta.decimals,maximumFractionDigits:meta.decimals});
  return withUnit?`${text} ${meta.unit}`:text;
}

function primaryBarColor(param,value,climate){
  if(climate===null) return "rgba(100,100,100,.65)";
  if(param==="temp") return value>=climate?"rgba(190,55,35,.72)":"rgba(44,104,160,.72)";
  if(param==="rain") return value>=climate?"rgba(56,135,72,.72)":"rgba(145,91,40,.72)";
  return value>=climate?"rgba(230,170,30,.75)":"rgba(105,115,130,.65)";
}

function deviationColor(param,value){
  if(param==="temp") return value>=0?"rgba(200,45,32,.78)":"rgba(38,103,170,.78)";
  if(param==="rain") return value>=0?"rgba(51,145,73,.78)":"rgba(156,92,38,.78)";
  return value>=0?"rgba(226,165,25,.8)":"rgba(96,108,127,.72)";
}

