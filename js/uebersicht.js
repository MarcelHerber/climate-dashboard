/* uebersicht.js – Farbtabelle, Datenstand, Navigation, Übersicht, laufender Monat
   Aus index.html ausgelagert (Schritt 2a). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= FARBIGE ABWEICHUNGSTABELLE =================
const ANOMALY_TABLE_PERIODS=[
  ...Array.from({length:12},(_,index)=>({value:String(index+1).padStart(2,"0"),label:MONTH_SHORT[index]})),
  {value:"winter",label:"Winter",separator:true},
  {value:"spring",label:"Frühling"},
  {value:"summer",label:"Sommer"},
  {value:"autumn",label:"Herbst"},
  {value:"year",label:"Jahr",separator:true}
];

const ANOMALY_COLOR_STOPS={
  temp:[
    {value:-5,color:"#3b0f70"},{value:-3,color:"#6a51a3"},{value:-1,color:"#cbc9e2"},
    {value:0,color:"#f7f7f7"},{value:1,color:"#fcbba1"},{value:3,color:"#ef3b2c"},{value:5,color:"#99000d"}
  ],
  rain:[
    {value:-80,color:"#4d2600"},{value:-50,color:"#8c510a"},{value:-25,color:"#d8b365"},
    {value:0,color:"#f7f7f7"},{value:25,color:"#92c5de"},{value:50,color:"#4393c3"},{value:100,color:"#053061"}
  ],
  sun:[
    {value:-50,color:"#3f3f3f"},{value:-25,color:"#969696"},{value:0,color:"#f7f7f7"},
    {value:20,color:"#fdbb84"},{value:40,color:"#e34a33"},{value:70,color:"#8c2d04"}
  ]
};

const ANOMALY_LEGEND_VALUES={
  temp:[-4,-2,0,2,4],
  rain:[-60,-30,0,30,60],
  sun:[-40,-20,0,20,40]
};

function parseHexColor(hex){
  const clean=hex.replace("#","");
  return {
    r:parseInt(clean.slice(0,2),16),
    g:parseInt(clean.slice(2,4),16),
    b:parseInt(clean.slice(4,6),16)
  };
}

function interpolateAnomalyColor(param,value){
  const stops=ANOMALY_COLOR_STOPS[param];
  if(value<=stops[0].value) return stops[0].color;
  if(value>=stops[stops.length-1].value) return stops[stops.length-1].color;
  for(let index=0;index<stops.length-1;index++){
    const left=stops[index];
    const right=stops[index+1];
    if(value>=left.value && value<=right.value){
      const fraction=(value-left.value)/(right.value-left.value);
      const a=parseHexColor(left.color);
      const b=parseHexColor(right.color);
      const r=Math.round(a.r+(b.r-a.r)*fraction);
      const g=Math.round(a.g+(b.g-a.g)*fraction);
      const blue=Math.round(a.b+(b.b-a.b)*fraction);
      return `rgb(${r},${g},${blue})`;
    }
  }
  return "#f7f7f7";
}

function readableTextColor(background){
  const match=background.match(/\d+/g);
  let rgb;
  if(match && match.length>=3){
    rgb={r:Number(match[0]),g:Number(match[1]),b:Number(match[2])};
  }else{
    rgb=parseHexColor(background);
  }
  const luminance=(0.2126*rgb.r+0.7152*rgb.g+0.0722*rgb.b)/255;
  return luminance<0.52?"#fff":"#171717";
}

function aggregatePeriodFromMap(byDate,year,selection,param){
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

function tableAnomaly(value,climate,param){
  if(value===null || climate===null || !Number.isFinite(value) || !Number.isFinite(climate)) return null;
  if(param==="temp") return value-climate;
  if(climate===0) return null;
  return (value/climate-1)*100;
}

function formatTableAnomaly(value,param){
  if(value===null || !Number.isFinite(value)) return "–";
  const sign=value>0?"+":"";
  if(param==="temp") return `${sign}${value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})}`;
  return `${sign}${value.toLocaleString("de-DE",{maximumFractionDigits:0})} %`;
}

function formatTableAbsolute(value,param){
  return formatValue(value,param);
}

function anomalyLegendLabel(value,param){
  if(value===0) return "0";
  const sign=value>0?"+":"";
  return param==="temp"?`${sign}${value} °C`:`${sign}${value} %`;
}

function formatAbsoluteTableDeviation(value,param){
  if(value===null || !Number.isFinite(value)) return "–";
  const sign=value>0?"+":"";
  const formatted=value.toLocaleString("de-DE",{minimumFractionDigits:0,maximumFractionDigits:1});
  return param==="rain"?`${sign}${formatted} l/m²`:`${sign}${formatted} h`;
}

function niceAbsoluteLegendMax(value,param){
  if(!Number.isFinite(value) || value<=0) return param==="rain"?100:50;
  const target=value;
  const exponent=Math.floor(Math.log10(target));
  const base=Math.pow(10,exponent);
  const fraction=target/base;
  let niceFraction;
  if(fraction<=1) niceFraction=1;
  else if(fraction<=2) niceFraction=2;
  else if(fraction<=2.5) niceFraction=2.5;
  else if(fraction<=5) niceFraction=5;
  else niceFraction=10;
  return niceFraction*base;
}

function absoluteLegendValues(maxValue){
  return [-maxValue,-maxValue/2,0,maxValue/2,maxValue];
}

function absoluteColorValue(value,param,maxValue){
  if(!Number.isFinite(value) || !Number.isFinite(maxValue) || maxValue<=0) return 0;
  const colorExtent=param==="rain"?60:40;
  return Math.max(-colorExtent,Math.min(colorExtent,(value/maxValue)*colorExtent));
}

function absoluteLegendLabel(value,param){
  if(value===0) return "0";
  const sign=value>0?"+":"";
  const maximum=Math.abs(value)>=100?0:1;
  const formatted=value.toLocaleString("de-DE",{minimumFractionDigits:0,maximumFractionDigits:maximum});
  return param==="rain"?`${sign}${formatted} l/m²`:`${sign}${formatted} h`;
}

function updateMonthlyAbsoluteAnomalyTable(){
  if(!document.getElementById("monthly")?.classList.contains("active")) return;
  if(!monthlyData.length) return;
  const card=document.getElementById("monthlyAbsoluteAnomalyCard");
  const area=document.getElementById("monthlyAreaSelect").value;
  const param=document.getElementById("paramSelect").value;

  // Die Temperaturtabelle zeigt bereits absolute Abweichungen in °C.
  if(param==="temp"){
    card.hidden=true;
    return;
  }
  card.hidden=false;

  const rows=areaRows(area);
  const byDate=new Map(rows.map(item=>[item.date,item]));
  const allYears=[...new Set(rows.map(item=>Number(item.date.slice(0,4))))].sort((a,b)=>a-b);

  const reference=updateMonthlyReferenceUi();
  const climateByPeriod=new Map();
  ANOMALY_TABLE_PERIODS.forEach(period=>{
    climateByPeriod.set(period.value,monthlyReferenceMeanForPeriod(byDate,period.value,param,reference));
  });

  const tableYears=allYears.filter(year=>
    ANOMALY_TABLE_PERIODS.some(period=>Number.isFinite(aggregatePeriodFromMap(byDate,year,period.value,param)))
  ).sort((a,b)=>b-a);

  // Für die absolute Tabelle wird auch die Farbskala in der absoluten Einheit dargestellt.
  // Eine gemeinsame dynamische Skala gilt für alle Zellen der aktuell sichtbaren Tabelle.
  const absoluteAnomalies=[];
  tableYears.forEach(year=>{
    ANOMALY_TABLE_PERIODS.forEach(period=>{
      const absolute=aggregatePeriodFromMap(byDate,year,period.value,param);
      const climate=climateByPeriod.get(period.value);
      if(Number.isFinite(absolute) && Number.isFinite(climate)) absoluteAnomalies.push(absolute-climate);
    });
  });
  const rawMaximum=absoluteAnomalies.length?Math.max(...absoluteAnomalies.map(value=>Math.abs(value))):0;
  const absoluteLegendMax=niceAbsoluteLegendMax(rawMaximum,param);

  const table=document.getElementById("monthlyAbsoluteAnomalyTable");
  const thead=table.querySelector("thead");
  const tbody=table.querySelector("tbody");
  thead.innerHTML=`<tr><th class="year-cell">Jahr</th>${ANOMALY_TABLE_PERIODS.map(period=>
    `<th class="${period.separator?"period-separator":""}" title="${periodLabel(period.value)}">${period.label}</th>`
  ).join("")}</tr>`;

  const latestYear=Math.max(...tableYears);
  tbody.innerHTML=tableYears.map(year=>{
    const cells=ANOMALY_TABLE_PERIODS.map(period=>{
      const absolute=aggregatePeriodFromMap(byDate,year,period.value,param);
      const climate=climateByPeriod.get(period.value);
      const relativeAnomaly=tableAnomaly(absolute,climate,param);
      const absoluteAnomaly=(Number.isFinite(absolute) && Number.isFinite(climate))?absolute-climate:null;
      const separator=period.separator?" period-separator":"";
      if(absoluteAnomaly===null || relativeAnomaly===null){
        return `<td class="no-value${separator}" title="Für ${periodLabel(period.value)} ${year} liegt kein vollständiger Wert vor.">–</td>`;
      }
      // Farbe folgt in dieser Tabelle bewusst der absoluten Abweichung (l/m² bzw. Stunden).
      const background=interpolateAnomalyColor(param,absoluteColorValue(absoluteAnomaly,param,absoluteLegendMax));
      const foreground=readableTextColor(background);
      const absoluteText=formatAbsoluteTableDeviation(absoluteAnomaly,param);
      const relativeText=formatTableAnomaly(relativeAnomaly,param);
      const tooltip=[
        `${year} · ${periodLabel(period.value)}`,
        `Wert: ${formatTableAbsolute(absolute,param)}`,
        `Mittel ${reference.label}: ${formatTableAbsolute(climate,param)}`,
        `Absolute Abweichung: ${absoluteText}`,
        `Relative Abweichung: ${relativeText}`
      ].join("\n");
      return `<td class="${separator.trim()}" style="background:${background};color:${foreground}" title="${tooltip}">${absoluteText}</td>`;
    }).join("");
    return `<tr class="${year===latestYear?"current-year":""}"><td class="year-cell">${year}</td>${cells}</tr>`;
  }).join("");

  const unit=param==="rain"?"l/m²":"Stunden";
  document.getElementById("monthlyAbsoluteAnomalyTableSubtitle").textContent=
    `${area} · ${PARAM_META[param].label} · absolute Differenz in ${unit}`;

  const legend=document.getElementById("monthlyAbsoluteAnomalyLegend");
  legend.innerHTML=absoluteLegendValues(absoluteLegendMax).map(value=>{
    const background=interpolateAnomalyColor(param,absoluteColorValue(value,param,absoluteLegendMax));
    return `<span class="anomaly-legend-item"><span class="anomaly-legend-swatch" style="background:${background}"></span>${absoluteLegendLabel(value,param)}</span>`;
  }).join("");

  const colorDescription=param==="rain"
    ?"Braun kennzeichnet trockene, Blau nasse Abweichungen."
    :"Grau kennzeichnet sonnenarme, Orange bis Dunkelrot sonnenreiche Abweichungen.";
  document.getElementById("monthlyAbsoluteAnomalyTableNote").textContent=
    `${colorDescription} Zahlen und Farbskala zeigen die absolute Differenz zum Mittel ${reference.label} in ${param==="rain"?"l/m² (1 mm Niederschlag = 1 l/m²)":"Stunden"}. Die Skala wird automatisch an den größten absoluten Wert der dargestellten Tabelle angepasst. Winter ${latestYear} umfasst Dezember ${latestYear-1} sowie Januar und Februar ${latestYear}. Unvollständige Zeiträume bleiben leer.`;
}

function updateMonthlyAnomalyTable(){
  if(!document.getElementById("monthly")?.classList.contains("active")) return;
  if(!monthlyData.length) return;
  const area=document.getElementById("monthlyAreaSelect").value;
  const param=document.getElementById("paramSelect").value;
  const rows=areaRows(area);
  const byDate=new Map(rows.map(item=>[item.date,item]));
  const allYears=[...new Set(rows.map(item=>Number(item.date.slice(0,4))))].sort((a,b)=>a-b);

  const reference=updateMonthlyReferenceUi();
  const climateByPeriod=new Map();
  ANOMALY_TABLE_PERIODS.forEach(period=>{
    climateByPeriod.set(period.value,monthlyReferenceMeanForPeriod(byDate,period.value,param,reference));
  });

  const tableYears=allYears.filter(year=>
    ANOMALY_TABLE_PERIODS.some(period=>Number.isFinite(aggregatePeriodFromMap(byDate,year,period.value,param)))
  ).sort((a,b)=>b-a);

  const table=document.getElementById("monthlyAnomalyTable");
  const thead=table.querySelector("thead");
  const tbody=table.querySelector("tbody");
  thead.innerHTML=`<tr><th class="year-cell">Jahr</th>${ANOMALY_TABLE_PERIODS.map(period=>
    `<th class="${period.separator?"period-separator":""}" title="${periodLabel(period.value)}">${period.label}</th>`
  ).join("")}</tr>`;

  const latestYear=Math.max(...tableYears);
  tbody.innerHTML=tableYears.map(year=>{
    const cells=ANOMALY_TABLE_PERIODS.map(period=>{
      const absolute=aggregatePeriodFromMap(byDate,year,period.value,param);
      const climate=climateByPeriod.get(period.value);
      const anomaly=tableAnomaly(absolute,climate,param);
      const separator=period.separator?" period-separator":"";
      if(anomaly===null){
        return `<td class="no-value${separator}" title="Für ${periodLabel(period.value)} ${year} liegt kein vollständiger Wert vor.">–</td>`;
      }
      const background=interpolateAnomalyColor(param,anomaly);
      const foreground=readableTextColor(background);
      const anomalyText=formatTableAnomaly(anomaly,param);
      const unitText=param==="temp"?"°C":"%";
      const tooltip=[
        `${year} · ${periodLabel(period.value)}`,
        `Wert: ${formatTableAbsolute(absolute,param)}`,
        `Mittel ${reference.label}: ${formatTableAbsolute(climate,param)}`,
        `Abweichung: ${anomalyText}${param==="temp"?` ${unitText}`:""}`
      ].join("\n");
      return `<td class="${separator.trim()}" style="background:${background};color:${foreground}" title="${tooltip}">${anomalyText}</td>`;
    }).join("");
    return `<tr class="${year===latestYear?"current-year":""}"><td class="year-cell">${year}</td>${cells}</tr>`;
  }).join("");

  document.getElementById("monthlyAnomalyTableSubtitle").textContent=
    `${area} · ${PARAM_META[param].label} · ${param==="temp"?"Abweichung in °C":"relative Abweichung in %"}`;

  const legend=document.getElementById("monthlyAnomalyLegend");
  legend.innerHTML=ANOMALY_LEGEND_VALUES[param].map(value=>{
    const background=interpolateAnomalyColor(param,value);
    return `<span class="anomaly-legend-item"><span class="anomaly-legend-swatch" style="background:${background}"></span>${anomalyLegendLabel(value,param)}</span>`;
  }).join("");

  const colorDescription=param==="temp"
    ?"Lila kennzeichnet kalte, Rot warme Abweichungen."
    :param==="rain"
      ?"Braun kennzeichnet trockene, Blau nasse Abweichungen."
      :"Grau kennzeichnet sonnenarme, Orange bis Dunkelrot sonnenreiche Abweichungen.";
  document.getElementById("monthlyAnomalyTableNote").textContent=
    `${colorDescription} Temperatur wird als Differenz in °C dargestellt; Niederschlag und Sonnenscheindauer als prozentuale Abweichung vom jeweiligen Mittel ${reference.label}. Winter ${latestYear} umfasst Dezember ${latestYear-1} sowie Januar und Februar ${latestYear}. Unvollständige Zeiträume bleiben leer.`;

  updateMonthlyAbsoluteAnomalyTable();
}

// ================= DATENSTAND =================
const DASHBOARD_RAW_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/";
const DASHBOARD_RAW_PREFIXES=[
  "station_records_years/",
  "station_precip_climate/",
  "station_precip_current/",
  "station_snow_height_index.json",
  "station_snow_height_current_index.json",
  "station_snow_height_profiles/",
  "station_snow_height_years/",
  "station_snow_height_current/",
  "station_snow_height_additional_index.json",
  "station_snow_height_additional_profiles/",
  "station_snow_height_additional_years/",
  "station_snow_height_additional_current/",
  "station_climate_days_profiles/",
  "station_climate_days_current/",
  "station_heatwaves_profiles/",
  "station_observations_index.json",
  "station_observations_current/"
];
function dashboardDataUrl(resource){
  if(typeof resource!=="string") return resource;
  const clean=resource.replace(/^\.\//,"").replace(/^\//,"");
  return DASHBOARD_RAW_PREFIXES.some(prefix=>clean.startsWith(prefix))
    ?`${DASHBOARD_RAW_BASE}${clean}`
    :resource;
}
function dashboardFetch(resource,options){
  return window.fetch(dashboardDataUrl(resource),options);
}



// ================= 17.0 NAVIGATION + ÜBERSICHT =================
function initializePrimaryNavigation(){
  document.querySelectorAll(".nav-dropdown-toggle").forEach(toggle=>{
    toggle.addEventListener("click",event=>{
      event.stopPropagation();
      const dropdown=toggle.closest(".nav-dropdown");
      const open=!dropdown.classList.contains("open");
      closeNavigationDropdowns();
      dropdown.classList.toggle("open",open);
      toggle.setAttribute("aria-expanded",open?"true":"false");
    });
  });
  document.addEventListener("click",event=>{
    if(!event.target.closest(".nav-dropdown")) closeNavigationDropdowns();
    if(!event.target.closest("#headerStatusWrap")) closeDashboardStatus();
  });
  document.addEventListener("keydown",event=>{
    if(event.key==="Escape"){closeNavigationDropdowns();closeDashboardStatus();}
  });
}
function toggleDashboardStatus(event){
  event?.stopPropagation?.();
  const wrap=document.getElementById("headerStatusWrap");
  if(!wrap)return;
  const open=!wrap.classList.contains("open");
  wrap.classList.toggle("open",open);
  document.getElementById("dataStatusButton")?.setAttribute("aria-expanded",open?"true":"false");
}
function closeDashboardStatus(){
  const wrap=document.getElementById("headerStatusWrap");
  if(!wrap)return;
  wrap.classList.remove("open");
  document.getElementById("dataStatusButton")?.setAttribute("aria-expanded","false");
}
function overviewSetText(id,value){
  const el=document.getElementById(id);
  if(el)el.textContent=value;
}
function overviewGermanNumber(value,decimals=1,{sign=false}={}){
  if(!Number.isFinite(value))return "–";
  const prefix=sign&&value>0?"+":"";
  return prefix+value.toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}
function overviewHasMonthlyValue(value){
  return value!==null && value!==undefined && value!=="" && Number.isFinite(Number(value));
}
function overviewLatestGermanyRow(){
  if(!monthlyData.length)return null;
  return currentMonthRow("Deutschland");

}
function overviewReferenceValue(area,param,date){
  if(!date)return null;
  const month=String(date).slice(5,7);
  const values=monthlyData
    .filter(row=>row.area===area && String(row.date).slice(5,7)===month)
    .filter(row=>{
      const year=Number(String(row.date).slice(0,4));
      return year>=1991&&year<=2020&&overviewHasMonthlyValue(row[param]);
    })
    .map(row=>Number(row[param]));
  return values.length>=27?mean(values):null;
}
function overviewMonthLabel(date){
  if(!date)return "aktuellster verfügbarer Monat";
  const [year,month]=String(date).split("-").map(Number);
  return `${MONTH_NAMES[(month||1)-1]||""} ${year}`;
}
function overviewSeriesExtremes(param,month){
  const series=seriesFor("Deutschland",month,param).filter(item=>Number.isFinite(item.value));
  if(!series.length)return {series,high:null,low:null};
  const high=[...series].sort((a,b)=>b.value-a.value||a.year-b.year)[0];
  const low=[...series].sort((a,b)=>a.value-b.value||a.year-b.year)[0];
  return {series,high,low};
}
function overviewRankForCurrent(series,year){
  const target=series.find(item=>item.year===year);
  if(!target)return null;
  const sorted=[...series].sort((a,b)=>b.value-a.value||a.year-b.year);
  return {rank:sorted.findIndex(item=>item.year===year)+1,total:sorted.length,value:target.value};
}
function overviewRecordText(item,param){
  if(!item)return "–";
  return `${item.year} · ${formatValue(item.value,param)}`;
}
function updateOverviewSummary(){
  if(!monthlyData.length)return;
  updateOverviewSeason();
  const latest=overviewLatestGermanyRow();
  if(!latest)return;
  const month=String(latest.date).slice(5,7);
  const year=Number(String(latest.date).slice(0,4));
  const label=overviewMonthLabel(latest.date);
  const provisional=Object.values(latest.provisional||{}).some(Boolean);
  overviewSetText("overviewCurrentTitle",`Deutschland aktuell (${label}${provisional?" · vorläufig":""})`);
  const titleNode=document.getElementById("overviewCurrentTitle");
  if(titleNode)titleNode.title=["temp","rain","sun"].map(p=>PARAM_META[p].label+": "+(latest.provisional?.[p]?liveMonthlyLabel(latest.provisional[p]):overviewHasMonthlyValue(latest[p])?"DWD bestätigt":"noch keine Daten")).join(" · ");
  const sourceNote=p=>latest.provisional?.[p]?liveMonthlyLabel(latest.provisional[p]):overviewHasMonthlyValue(latest[p])?"DWD bestätigt":"noch keine Daten";
  for(const [p,id] of [["temp","overviewTempAnomaly"],["rain","overviewRainPercent"]]){
    const note=document.getElementById(id)?.parentElement?.querySelector(".overview-kpi-detail");
    if(note)note.textContent=sourceNote(p)+(latest.provisional?.[p]&&!latest.provisional[p].complete?" · Vergleich voller Klimamonat":"");
  }

  const refTemp=overviewReferenceValue("Deutschland","temp",latest.date);
  const refRain=overviewReferenceValue("Deutschland","rain",latest.date);
  const refSun=overviewReferenceValue("Deutschland","sun",latest.date);
  const temp=overviewHasMonthlyValue(latest.temp)?Number(latest.temp):null;
  const rain=overviewHasMonthlyValue(latest.rain)?Number(latest.rain):null;
  const sun=overviewHasMonthlyValue(latest.sun)?Number(latest.sun):null;
  const tempAnom=Number.isFinite(temp)&&Number.isFinite(refTemp)?temp-refTemp:null;
  const rainPct=Number.isFinite(rain)&&Number.isFinite(refRain)&&refRain!==0?100*rain/refRain:null;
  const sunPct=Number.isFinite(sun)&&Number.isFinite(refSun)&&refSun!==0?100*sun/refSun:null;
  overviewSetText("overviewTempAnomaly",Number.isFinite(tempAnom)?`${overviewGermanNumber(tempAnom,1,{sign:true})} °C`:"–");
  overviewSetText("overviewRainPercent",Number.isFinite(rainPct)?`${overviewGermanNumber(rainPct,0)} %`:"–");
  overviewSetText("overviewSunPercent",Number.isFinite(sunPct)?`${overviewGermanNumber(sunPct,0)} %`:"–");
  overviewSetText("overviewSunDetail",Number.isFinite(sunPct)?`${sourceNote("sun")} · Anteil am vollen Klimamonat 1991–2020` : sourceNote("sun"));

  const tempExt=overviewSeriesExtremes("temp",month);
  const rank=latest.provisional?.temp?.complete?overviewRankForCurrent([...tempExt.series.filter(x=>x.year!==year),{year,value:temp}],year):overviewRankForCurrent(tempExt.series,year);
  overviewSetText("overviewTempRank",rank?`${rank.rank} / ${rank.total}`:"–");
  overviewSetText("overviewTempRankDetail",rank?`${label} · ${latest.provisional?.temp?"vorläufiger ":""}Rang der wärmsten Vergleichsmonate`:"historischer Rang nicht verfügbar");

  const years=tempExt.series.map(item=>item.year);
  const first=years.length?Math.min(...years):null,last=years.length?Math.max(...years):null;
  overviewSetText("overviewSeriesRange",first&&last?`${first}–${last}`:"–");
  overviewSetText("overviewSeriesRangeDetail",first&&last?`${years.length} auswertbare Jahre für ${MONTH_NAMES[Number(month)-1]}`:"DWD-Gebietsmittel Deutschland");

  const rainExt=overviewSeriesExtremes("rain",month);
  const sunExt=overviewSeriesExtremes("sun",month);
  overviewSetText("overviewWarmRecord",overviewRecordText(tempExt.high,"temp"));
  overviewSetText("overviewColdRecord",overviewRecordText(tempExt.low,"temp"));
  overviewSetText("overviewWetRecord",overviewRecordText(rainExt.high,"rain"));
  overviewSetText("overviewDryRecord",overviewRecordText(rainExt.low,"rain"));
  overviewSetText("overviewSunRecord",overviewRecordText(sunExt.high,"sun"));
  overviewSetText("overviewStatsFoot",`Historischer Vergleich für ${MONTH_NAMES[Number(month)-1]} · bestätigte Monatswerte. Aktuell: ${["temp","rain","sun"].map(p=>PARAM_META[p].label+": "+(latest.provisional?.[p]?liveMonthlyLabel(latest.provisional[p]):overviewHasMonthlyValue(latest[p])?"DWD bestätigt":"noch keine Daten")).join(" · ")}. Teilmonate im Verhältnis zum vollen Klimamonat.`);
}
function overviewStatusLabel(value){
  if(!value)return "nicht verfügbar";
  const text=String(value);
  const d=/^\d{4}-\d{2}-\d{2}$/.test(text)?new Date(`${text}T12:00:00`):null;
  return d&&!Number.isNaN(d.getTime())?`bis ${d.toLocaleDateString("de-DE")}`:text;
}
function updateOverviewStatus(status){
  overviewStatusPayload=status||{};
  const updated=status?.updated_at?new Date(status.updated_at):null;
  overviewSetText("overviewTimestamp",updated&&!Number.isNaN(updated.getTime())
    ?`Datenstand: ${updated.toLocaleString("de-DE",{timeZone:"Europe/Berlin",dateStyle:"short",timeStyle:"short"})}`
    :"Datenstand nicht verfügbar");
  const setStatus=(dotId,textId,value,labelFormatter=overviewStatusLabel)=>{
    const dot=document.getElementById(dotId),text=document.getElementById(textId);
    const ok=Boolean(value);
    if(dot)dot.className=`overview-source-dot ${ok?"ok":"warn"}`;
    if(text)text.textContent=ok?labelFormatter(value):"nicht verfügbar";
  };
  setStatus("overviewDotMonthly","overviewStatusMonthly",status?.monthly?.latest_complete_month,v=>`bis ${String(v).split("-").reverse().join("/")}`);
  setStatus("overviewDotDaily","overviewStatusDaily",status?.daily?.latest_date);
  const stationThrough=status?.station_records?.data_through||status?.station_climate_days?.data_through||status?.station_precip?.data_through;
  setStatus("overviewDotStations","overviewStatusStations",stationThrough);
}
function overviewMapScale(values,param){
  const finite=values.filter(Number.isFinite);
  if(!finite.length)return {color:()=>"#e5e7eb",legend:[]};
  if(param==="temp"){
    const abs=Math.max(.5,...finite.map(v=>Math.abs(v)));
    const stops=[-abs,-abs*.66,-abs*.33,0,abs*.33,abs*.66,abs];
    const colors=["#2b5c9a","#79a8d5","#d8e7f3","#f5f5f3","#f6b19b","#e76b55","#b9212f"];
    const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
    return {color,legend:stops.map((value,i)=>({value,color:colors[i]}))};
  }
  if(param==="rain"){
    const stops=[50,75,90,100,110,125,150];
    const colors=["#9a6b35","#c89c63","#e7d7bd","#f4f4f1","#cfe0ee","#76a8cf","#2f6fa6"];
    const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
    return {color,legend:stops.map((value,i)=>({value,color:colors[i]}))};
  }
  const stops=[70,85,95,100,105,115,130];
  const colors=["#58708e","#8ba0b5","#d3d9df","#f1f1ed","#f2d38d","#e7a63e","#c97b14"];
  const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
  return {color,legend:stops.map((value,i)=>({value,color:colors[i]}))};
}
function overviewMetric(area,param,date){
  const row=date===liveCalendarMonth()?currentMonthRow(area):monthlyData.find(item=>item.area===area&&item.date===date);
  if(!row||!overviewHasMonthlyValue(row[param]))return null;
  const ref=overviewReferenceValue(area,param,date);
  if(!Number.isFinite(ref))return null;
  const value=Number(row[param]);
  return param==="temp"?value-ref:(ref!==0?100*value/ref:null);
}
function overviewMetricText(value,param){
  if(!Number.isFinite(value))return "keine Daten";
  return param==="temp"?`${overviewGermanNumber(value,1,{sign:true})} °C`:`${overviewGermanNumber(value,0)} %`;
}
function renderOverviewMap(){
  const container=document.getElementById("overviewMap");
  if(!container||!container.clientWidth||!container.clientHeight||!monthlyData.length||typeof L==="undefined")return;
  const latest=overviewLatestGermanyRow();
  if(!latest)return;
  const param=overviewMapParam;
  const label=overviewMonthLabel(latest.date);
  overviewSetText("overviewMapTitle",`${PARAM_META[param].label}${param==="temp"?"abweichung":""} – ${label}`);
  overviewSetText("overviewMapSubtitle",`${param==="temp"?"Abweichung":"Anteil"} gegenüber 1991–2020 · Deutschland und Bundesländer${latest.provisional?.[param]?" · vorläufig ("+liveMonthlyLabel(latest.provisional[param])+")":""}`);

  const states=Object.keys(REGIONAL_MAP_STATE_AREA);
  const valuesByState=new Map(states.map(name=>[name,overviewMetric(REGIONAL_MAP_STATE_AREA[name],param,latest.date)]));
  const scale=overviewMapScale([...valuesByState.values()],param);
  const legend=document.getElementById("overviewMapLegend");
  if(legend){
    const chosen=scale.legend.length>4?[scale.legend[0],scale.legend[Math.floor(scale.legend.length/2)],scale.legend.at(-1)]:scale.legend;
    legend.innerHTML=chosen.map(item=>`<span class="overview-map-legend-swatch" style="background:${item.color}"></span><span>${overviewMetricText(item.value,param)}</span>`).join("");
  }
  document.querySelectorAll("[data-overview-param]").forEach(button=>button.classList.toggle("active",button.dataset.overviewParam===param));

  regionalMapLoadGeoJson().then(geo=>{
    if(!container.isConnected||!container.clientWidth||!container.clientHeight)return;
    if(!overviewMap){
      container.innerHTML="";
      overviewMap=L.map(container,{
        zoomControl:false,attributionControl:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,
        keyboard:false,dragging:false,touchZoom:false
      }).setView([51.15,10.3],6);
    }else overviewMap.invalidateSize({animate:false,pan:false});
    if(overviewMapLayer)overviewMap.removeLayer(overviewMapLayer);
    overviewMapLayer=L.geoJSON(geo,{
      style:feature=>{
        const name=feature?.properties?.name;
        const value=valuesByState.get(name);
        return {color:"#ffffff",weight:1.25,fillColor:scale.color(value),fillOpacity:Number.isFinite(value)?.94:.38};
      },
      onEachFeature:(feature,layer)=>{
        const name=feature?.properties?.name||"Bundesland";
        const area=REGIONAL_MAP_STATE_AREA[name]||name;
        const value=valuesByState.get(name);
        layer.bindTooltip(`<div class="overview-tooltip"><strong>${name}</strong><br>${overviewMetricText(value,param)}<br><span style="color:#6b7280">${area!==name?`DWD-Gebiet: ${area}<br>`:""}Referenz 1991–2020</span></div>`,{sticky:true,direction:"top"});
        layer.on({
          mouseover:e=>e.target.setStyle({weight:2,color:"#344454",fillOpacity:1}),
          mouseout:e=>e.target.setStyle({color:"#ffffff",weight:1.25,fillColor:scale.color(value),fillOpacity:Number.isFinite(value)?.94:.38}),
          click:()=>{switchTab("monthly");const areaSelect=document.getElementById("monthlyAreaSelect");if(areaSelect&&[...areaSelect.options].some(o=>o.value===area)){areaSelect.value=area;areaSelect.dispatchEvent(new Event("change",{bubbles:true}));}}
        });
      }
    }).addTo(overviewMap);
    const bounds=overviewMapLayer.getBounds();
    if(bounds.isValid())overviewMap.fitBounds(bounds,{padding:[5,5],animate:false});
  }).catch(error=>{
    console.warn("Übersichtskarte:",error);
    container.innerHTML=`<div style="padding:24px;color:#64748b;font-size:12px">Deutschlandkarte konnte nicht geladen werden.</div>`;
  });
}
function renderOverview(){
  updateOverviewSummary();
  if(document.getElementById("overview")?.classList.contains("active"))renderOverviewMap();
  if(overviewStatusPayload)updateOverviewStatus(overviewStatusPayload);
}
function initializeOverviewControls(){
  if(typeof L==="undefined"){
    document.getElementById("dashboardLeafletScript")?.addEventListener("load",()=>{
      if(document.getElementById("overview")?.classList.contains("active"))renderOverviewMap();
    },{once:true});
  }
  document.querySelectorAll("[data-overview-param]").forEach(button=>{
    button.addEventListener("click",()=>{
      overviewMapParam=button.dataset.overviewParam||"temp";
      renderOverviewMap();
    });
  });
}
initializePrimaryNavigation();
initializeOverviewControls();


// ================= VORLÄUFIGER LAUFENDER MONAT · HYRAS-BEOBACHTUNGEN =================
// These observations are intentionally separate from the final DWD monthly series.
// Keep the last observed monthly snapshots until the published DWD monthly
// regional averages arrive; the normal DWD series always takes precedence.
let monthlyObservedHistory=[];
let monthlyObservedSelectionTouched=false;
let monthlyObservedChangingSelection=false;
document.getElementById("monthSelect")?.addEventListener("change",()=>{
  if(!monthlyObservedChangingSelection)monthlyObservedSelectionTouched=true;
});
function validObservedSnapshot(data){
  return !!data && data.schema===1 && data.forecast===false
    && /^\d{4}-\d{2}$/.test(data.month)
    && /^\d{4}-\d{2}-\d{2}$/.test(data.data_through)
    && data.month===data.data_through.slice(0,7)
    && data.areas && typeof data.areas==="object";
}
async function loadMonthlyObservedLive(){
  const currentMonth=liveCalendarMonth();
  void loadCurrentMonthOutlook();
  const files=[
    "./monthly_provisional_history.json",
    HYRAS_DATA_BASE+"/monthly_provisional_history.json",
    "./monthly_current_provisional.json",
    HYRAS_DATA_BASE+"/monthly_current_provisional.json"
  ];
  const snapshots=await Promise.all(files.map(async url=>{
    try{
      const response=await fetch(url+(url.includes("?")?"&":"?")+"t="+Math.floor(Date.now()/300000),{cache:"no-store"});
      if(!response.ok)return [];
      const payload=await response.json();
      return Array.isArray(payload.months)?payload.months:[payload];
    }catch(error){
      console.warn("HYRAS-Monatsarchiv nicht geladen:",url,error);
      return [];
    }
  }));
  const byMonth=new Map();
  for(const data of snapshots.flat()){
    if(!validObservedSnapshot(data)||data.month>currentMonth)continue;
    const previous=byMonth.get(data.month);
    if(!previous || data.data_through>previous.data_through
      || data.data_through===previous.data_through
      && Object.values(data.areas).reduce((n,values)=>n+Object.keys(values||{}).length,0)
       >Object.values(previous.areas).reduce((n,values)=>n+Object.keys(values||{}).length,0)){
      byMonth.set(data.month,data);
    }
  }
  monthlyObservedHistory=[...byMonth.values()].sort((a,b)=>a.month.localeCompare(b.month));
  // Choose the latest actually observed calendar month on the initial load.
  // On 1 December with no December HYRAS data, November remains visible.
  // Never override a period the visitor has selected manually.
  const selector=document.getElementById("monthSelect");
  if(selector&&!monthlyObservedSelectionTouched){
    const latest=currentMonth.slice(5);
    if(selector.value!==latest && [...selector.options].some(option=>option.value===latest)){
      monthlyObservedChangingSelection=true;
      try{
        selector.value=latest;
        selector.dispatchEvent(new Event("change",{bubbles:true}));
      }finally{
        monthlyObservedChangingSelection=false;
      }
    }
  }
  // Only the historical Chart.js chart receives provisional values.
  // Official DWD values in monthlyData are never overwritten.
  if(monthlyData.length){updateMonthly();renderOverview();window.refreshGebietsmittelArchive?.();}
}
function observedMonthlyBar(area,selection,param,historicalValues){
  const month=liveCalendarMonth(),year=Number(month.slice(0,4));
  const season=seasonForMonth(month);
  if(selection===season.selection&&!historicalValues.some(item=>item.year===season.year)){
    const r=liveSeasonValue(area,season.year,selection,param);
    if(r)return {...r,year:season.year};
  }
  if(selection===month.slice(5)&&!historicalValues.some(item=>item.year===year)){
    const live=liveMonthlyValue(area,month,param);
    if(live)return {...live,year};
  }
  const matches=monthlyObservedHistory
    .filter(data=>selection===data.month.slice(5) && typeof data.areas?.[area]?.[param]==="number")
    .sort((a,b)=>b.month.localeCompare(a.month));
  for(const data of matches){
    const value=data.areas[area][param],year=Number(data.month.slice(0,4));
    if(!Number.isFinite(value))continue;
    // The official DWD value is authoritative as soon as its parameter exists.
    if(historicalValues.some(item=>item.year===year))continue;
    return {year,value,through:data.data_through,source:param==="sun"?"DWD":"HYRAS",mode:"observed",complete:data.data_through.endsWith("-"+String(data.days_in_month).padStart(2,"0"))};
  }
  return null;
}
function observedMonthlyHatch(ctx){
  const tile=document.createElement("canvas");
  tile.width=14;tile.height=14;
  const pen=tile.getContext("2d");
  pen.fillStyle="rgba(74,133,177,.30)";
  pen.fillRect(0,0,14,14);
  pen.strokeStyle="#27658f";pen.lineWidth=3;
  pen.beginPath();pen.moveTo(-5,14);pen.lineTo(14,-5);
  pen.moveTo(6,17);pen.lineTo(17,6);pen.stroke();
  return ctx.createPattern(tile,"repeat")||"rgba(44,106,152,.6)";
}


const currentMonthOutlookDocs={};
function monthlyOutlookValue(doc,area,key,month,today){
 const end=month+"-"+String(new Date(Number(month.slice(0,4)),Number(month.slice(5)),0).getDate()).padStart(2,"0");
 if(!doc||`${doc.year}-${String(doc.month).padStart(2,"0")}`!==month)return null;
 const dates=key==="temp"?(doc.periods?.month?.dates||doc.dates):doc.dates;
 const base=doc.regions?.[area],r=key==="temp"?(base?.periods?.month||base):base;
 if(!r||!Array.isArray(dates)||dates[0]!==month+"-01"||dates.at(-1)!==end||dates.length!==Number(end.slice(8)))return null;
 if(!dates.every((d,i)=>d===month+"-"+String(i+1).padStart(2,"0")))return null;
 const through=r.observed_through||doc.observation_data_through,idx=dates.indexOf(through);
 const finite=v=>typeof v==="number"&&Number.isFinite(v);
 if(idx<0||through>today.slice(0,10)||!dates.slice(0,idx+1).every((_,i)=>finite(r.observed_running?.[i])))return null;
 const observed=r.observed_running[idx];
 const source=key==="sun"?"DUETT":"HYRAS";
 if(through===end)return {value:observed,through,mode:"observed",complete:true,source};
 const m=r.models?.gefs, run=Date.parse(m?.run||m?.retrieved_at||"");
 const age=Date.parse(today)-run;
 if(m?.forecast_through>=end&&m.forecast_from<=dates[idx+1]&&Number.isFinite(age)&&age>=-3600000&&age<=48*3600000&&dates.slice(idx+1).every((_,i)=>finite(m.stats?.mean?.[idx+1+i])))return {value:m.stats.mean.at(-1),through,mode:"forecast",complete:true,source,run:m.run||m.retrieved_at};
 return {value:observed,through,mode:"observed",complete:false,source};
}
function liveCalendarMonth(){const parts=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit"}).formatToParts(new Date());return parts.find(x=>x.type==="year").value+"-"+parts.find(x=>x.type==="month").value;}
function liveMonthlyValue(area,month,key){
  const current=liveCalendarMonth();
  if(month>current)return null;
  const today=new Date().toISOString();
  const data=monthlyObservedHistory.find(d=>d.month===month);
  const a=data?.areas?.[area],v=a?.[key],cut=a?.data_through?.[key]||data?.data_through;
  const end=month+"-"+String(new Date(Number(month.slice(0,4)),Number(month.slice(5)),0).getDate()).padStart(2,"0");
  const obs=Number.isFinite(v)&&cut?.startsWith(month)&&cut<=today.slice(0,10)?{value:v,through:cut,mode:"observed",complete:cut===end,source:key==="sun"?"DWD":"HYRAS"}:null;
  if(month!==current)return obs?.complete?obs:null;
  const d=currentMonthOutlookDocs[key];
  const groups={"Brandenburg/Berlin":[["Brandenburg",29654],["Berlin",892]],"Niedersachsen/Hamburg/Bremen":[["Niedersachsen",47710],["Hamburg",755],["Bremen",420]],"Thüringen/Sachsen-Anhalt":[["Thüringen",16202],["Sachsen-Anhalt",20452]]};
  let candidate=monthlyOutlookValue(d,area,key,month,today);
  if(!candidate&&groups[area]){
    const parts=groups[area].map(([name,w])=>({r:monthlyOutlookValue(d,name,key,month,today),w}));
    if(parts.every(({r})=>r&&r.through===parts[0].r.through&&r.mode===parts[0].r.mode&&r.run===parts[0].r.run)){
      candidate={...parts[0].r,value:parts.reduce((s,{r,w})=>s+r.value*w,0)/parts.reduce((s,{w})=>s+w,0),approximate:true};
    }
  }
  if(obs&&(!candidate||obs.through>candidate.through||obs.complete))return obs;
  return candidate||obs;
}
function liveMonthlyLabel(r){
  if(!r)return "keine aktuellen Daten";
  if(r.season)return "Vorläufig · "+(r.mode==="forecast"?"inkl. GEFS-Mittel":"DWD/HYRAS/DUETT")+" bis "+r.through.slice(8)+"."+r.through.slice(5,7)+"."+(r.complete?"":" · Teiljahreszeit")+(r.approximate?" · flächengewichtete Näherung":"");
  return (r.mode==="forecast"?r.source+" + GEFS-Mittel bis Monatsende":r.source+" bis "+r.through.slice(8)+"."+r.through.slice(5,7)+".")+(r.approximate?" · flächengewichtet (Näherung)":"")+(r.complete?"":" · Teilmonat");
}
async function loadCurrentMonthOutlook(){
  const base="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/";
  const products={temp:"state-monthly-ensemble/state_monthly_ensemble.json",rain:"state-monthly-precip/state_monthly_precip.json",sun:"state-monthly-sun/state_monthly_sun.json"};
  await Promise.all(Object.entries(products).map(async ([key,path])=>{
    try{
      const response=await fetch(base+path+"?t="+Math.floor(Date.now()/300000),{cache:"no-store",signal:AbortSignal.timeout(20000)});
      if(response.ok)currentMonthOutlookDocs[key]=await response.json();
    }catch(e){console.warn("Monatsausblick Gebietsmittel",key,e);}
    if(typeof monthlyData!=="undefined"&&monthlyData.length){
      renderOverview();updateMonthly();window.refreshGebietsmittelArchive?.();
    }
  }));
}
function currentMonthRow(area){
  const date=liveCalendarMonth(),official=monthlyData.find(r=>r.area===area&&r.date===date);
  const row={area,date,provisional:{}};
  for(const key of ["temp","rain","sun"]){
    if(overviewHasMonthlyValue(official?.[key]))row[key]=Number(official[key]);
    else{const r=liveMonthlyValue(area,date,key);row[key]=r?.value??null;row.provisional[key]=r;}
  }
  return row;
}

function seasonForMonth(month){
  const y=Number(month.slice(0,4)),m=Number(month.slice(5));
  return m===12?{year:y+1,selection:"winter"}:m<=2?{year:y,selection:"winter"}:m<=5?{year:y,selection:"spring"}:m<=8?{year:y,selection:"summer"}:{year:y,selection:"autumn"};
}
function combineSeason(months,currentMonth,param,readOfficial,readLive){
  const finite=v=>typeof v==="number"&&Number.isFinite(v);
  let sum=0,days=0,through=null,forecast=false,provisional=false,approximate=false;
  const details=[];
  for(const month of months){
    if(month>currentMonth)break;
    const endDay=new Date(Number(month.slice(0,4)),Number(month.slice(5)),0).getDate();
    const end=month+"-"+String(endDay).padStart(2,"0");
    const official=readOfficial(month);
    if(finite(official)){
      sum+=param==="temp"?official*endDay:official;days+=endDay;through=end;
      details.push(month+": DWD bestätigt");continue;
    }
    const r=readLive(month);
    if(!r||!finite(r.value)){
      if(month<currentMonth)return null;
      break;
    }
    if(!r.complete&&month<currentMonth)return null;
    if(!r.through?.startsWith(month)||!/^\d{4}-\d{2}-\d{2}$/.test(r.through))return null;
    const used=r.complete?endDay:Number(r.through.slice(8));
    if(!Number.isInteger(used)||used<1||used>endDay)return null;
    sum+=param==="temp"?r.value*used:r.value;days+=used;
    through=r.complete?end:r.through;
    forecast ||= r.mode==="forecast";provisional=true;approximate ||= !!r.approximate;
    details.push(month+": "+r.source+(r.mode==="forecast"?" + GEFS bis Monatsende":" bis "+r.through));
  }
  if(!days)return null;
  const last=months.at(-1),lastEnd=last+"-"+String(new Date(Number(last.slice(0,4)),Number(last.slice(5)),0).getDate()).padStart(2,"0");
  return {value:param==="temp"?sum/days:sum,through,complete:through===lastEnd,mode:forecast?"forecast":"observed",source:"DWD-Monatswerte + "+(param==="sun"?"DUETT":"HYRAS"),approximate,season:true,days,details,provisional:provisional||through!==lastEnd};
}
function liveSeasonValue(area,year,selection,param){
  const current=liveCalendarMonth(),active=seasonForMonth(current);
  if(year!==active.year||selection!==active.selection)return null;
  const months=periodKeys(year,selection).map(k=>k.year+"-"+String(k.month).padStart(2,"0"));
  const rows=areaRows(area);
  const byDate=new Map(rows.filter(r=>months.includes(r.date)).map(r=>[r.date,r]));
  const r=combineSeason(months,current,param,m=>byDate.get(m)?.[param],m=>liveMonthlyValue(area,m,param));
  return r?.provisional?r:null;
}
function updateOverviewSeason(){
  const node=document.getElementById("overviewSeasonTitle");if(!node||!monthlyData.length)return;
  const {year,selection}=seasonForMonth(liveCalendarMonth());
  const labels={winter:"Winter",spring:"Frühling",summer:"Sommer",autumn:"Herbst"};
  node.textContent=labels[selection]+" "+(selection==="winter"?(year-1)+"/"+String(year).slice(-2):year);
  for(const [param,id] of [["temp","overviewSeasonTemp"],["rain","overviewSeasonRain"],["sun","overviewSeasonSun"]]){
    const live=liveSeasonValue("Deutschland",year,selection,param);
    const series=seriesFor("Deutschland",selection,param);
    const official=series.find(x=>x.year===year)?.value;
    const value=Number.isFinite(official)?official:live?.value;
    const normalValues=series.filter(x=>x.year>=1991&&x.year<=2020).map(x=>x.value);
    const normal=normalValues.length>=29?mean(normalValues):null;
    const complete=Number.isFinite(official)||live?.complete;
    let label=Number.isFinite(value)?formatValue(value,param):"–";
    if(complete&&Number.isFinite(value)&&Number.isFinite(normal)){
      if(param==="temp")label+=" · "+overviewGermanNumber(value-normal,1,{sign:true})+" K";
      else if(normal>0)label+=" · "+overviewGermanNumber(100*value/normal,0)+" %";
    }
    overviewSetText(id,label);
    overviewSetText(id+"Note",Number.isFinite(official)?"DWD bestätigt":live?liveMonthlyLabel(live):"noch keine vollständigen Daten");
    const el=document.getElementById(id);if(el)el.title=live?.details.join(" · ")||"";
  }
}
