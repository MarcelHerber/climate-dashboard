/* stationen-kenntage.js – Stations-Kenntage
   Aus index.html ausgelagert (Schritt 2b). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= STATIONS-KENNTAGE =================
function stationClimateDaysDateLabel(monthDay){
  const [month,day]=monthDay.split("-");
  return `${day}.${month}.`;
}

function stationClimateDaysMetric(){
  const id=document.getElementById("stationClimateDaySelect").value;
  return (stationClimateDaysIndex?.climate_days||[]).find(item=>item.id===id) || null;
}

function stationClimateDaysPeriod(){
  const id=document.getElementById("stationClimateDaysPeriodSelect").value;
  return (stationClimateDaysIndex?.periods||[]).find(item=>item.id===id) || {id:"year",label:"Gesamtjahr",expected_days:365};
}

function ensureStationClimateDaysLoaded(){
  if(stationClimateDaysIndex){
    updateStationClimateDays();
    return Promise.resolve(stationClimateDaysIndex);
  }
  if(stationClimateDaysLoading) return stationClimateDaysLoading;
  const loading=document.getElementById("stationClimateDaysLoading");
  loading.textContent="Stations-Kenntage werden geladen …";
  stationClimateDaysLoading=dashboardFetch("station_climate_days_index.json",{cache:"no-store"})
    .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(data=>{
      if(!data.ready) throw new Error(data.message || "Die Stations-Kenntage wurden noch nicht aufgebaut.");
      stationClimateDaysIndex=data;
      initializeStationClimateDaysControls();
      initializeStationClimateRecordOverview();
      loading.hidden=true;
      document.getElementById("stationClimateDaysContent").hidden=false;
      document.getElementById("stationClimateDaysSourceNote").textContent=[data.source_note,data.leap_day_rule].filter(Boolean).join(" ");
      return updateStationClimateDays().then(()=>data);
    })
    .catch(error=>{
      loading.textContent=`Stations-Kenntage konnten nicht geladen werden: ${error.message}`;
      loading.style.color="#7a1010";
      throw error;
    });
  return stationClimateDaysLoading;
}

function initializeStationClimateDaysControls(){
  const stateSelect=document.getElementById("stationClimateDaysStateSelect");
  stateSelect.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  (stationClimateDaysIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });
  stateSelect.value="Deutschland";

  const metricSelect=document.getElementById("stationClimateDaySelect");
  metricSelect.innerHTML="";
  (stationClimateDaysIndex.climate_days||[]).forEach(metric=>{
    const option=document.createElement("option");
    option.value=metric.id;
    option.textContent=`${metric.label} (${metric.definition})`;
    metricSelect.appendChild(option);
  });
  if((stationClimateDaysIndex.climate_days||[]).some(item=>item.id==="summer")) metricSelect.value="summer";

  const periodSelect=document.getElementById("stationClimateDaysPeriodSelect");
  periodSelect.innerHTML="";
  (stationClimateDaysIndex.periods||[]).forEach(period=>{
    const option=document.createElement("option");
    option.value=period.id;
    option.textContent=period.label;
    periodSelect.appendChild(option);
  });
  periodSelect.value="year";

  stateSelect.addEventListener("change",()=>{
    populateStationClimateDaysStations();
    updateStationClimateDays();
  });
  document.getElementById("stationClimateDaysSearch").addEventListener("input",()=>{
    populateStationClimateDaysStations();
    updateStationClimateDays();
  });
  document.getElementById("stationClimateDaysStationSelect").addEventListener("change",updateStationClimateDays);
  metricSelect.addEventListener("change",updateStationClimateDays);
  periodSelect.addEventListener("change",updateStationClimateDays);
  populateStationClimateDaysStations();
}

function filteredStationClimateDaysStations(){
  const state=document.getElementById("stationClimateDaysStateSelect").value;
  const search=document.getElementById("stationClimateDaysSearch").value.trim().toLocaleLowerCase("de-DE");
  return (stationClimateDaysIndex.stations||[]).filter(station=>{
    if(state!=="Deutschland" && station.state!==state) return false;
    if(!search) return true;
    return `${station.name} ${station.id}`.toLocaleLowerCase("de-DE").includes(search);
  });
}

function populateStationClimateDaysStations(){
  const select=document.getElementById("stationClimateDaysStationSelect");
  const previous=select.value;
  const stations=filteredStationClimateDaysStations();
  select.innerHTML="";
  stations.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    option.textContent=`${station.name} (${station.id})`;
    select.appendChild(option);
  });
  if(stations.some(station=>station.id===previous)) select.value=previous;
  else if(stations.length) select.value=stations[0].id;
}

async function loadStationClimateDaysCurrentMonths(){
  const files=stationClimateDaysIndex.current_files||[];
  await Promise.all(files.map(async file=>{
    if(stationClimateDaysMonthCache.has(file)) return;
    const response=await dashboardFetch(file,{cache:"no-store"});
    if(!response.ok) throw new Error(`${file} konnte nicht geladen werden (HTTP ${response.status}).`);
    stationClimateDaysMonthCache.set(file,await response.json());
  }));
}

function stationClimateDaysMonthPayload(year,month){
  for(const payload of stationClimateDaysMonthCache.values()){
    if(Number(payload.year)===Number(year) && Number(payload.month)===Number(month)) return payload;
  }
  return null;
}

function stationClimateDaysPair(stationId,isoDate){
  const [yearText,monthText,dayText]=isoDate.split("-");
  const payload=stationClimateDaysMonthPayload(Number(yearText),Number(monthText));
  const values=payload?.stations?.[stationId];
  const day=Number(dayText);
  return values && day<=values.length ? values[day-1] : null;
}

function stationClimateDaysUtcDates(startIso,endIso){
  const result=[];
  let cursor=new Date(`${startIso}T00:00:00Z`);
  const end=new Date(`${endIso}T00:00:00Z`);
  while(cursor<=end){
    const iso=cursor.toISOString().slice(0,10);
    if(iso.slice(5)!=="02-29") result.push(iso);
    cursor.setUTCDate(cursor.getUTCDate()+1);
  }
  return result;
}

function stationClimateDaysPeriodDates(periodId,year){
  if(periodId==="winter") return stationClimateDaysUtcDates(`${year-1}-12-01`,`${year}-02-28`);
  if(periodId==="spring") return stationClimateDaysUtcDates(`${year}-03-01`,`${year}-05-31`);
  if(periodId==="summer") return stationClimateDaysUtcDates(`${year}-06-01`,`${year}-08-31`);
  if(periodId==="autumn") return stationClimateDaysUtcDates(`${year}-09-01`,`${year}-11-30`);
  return stationClimateDaysUtcDates(`${year}-01-01`,`${year}-12-31`);
}

function stationClimateDaysCurrentPeriod(stationId,metric,periodId){
  const year=Number(stationClimateDaysIndex.current_year);
  const dataThrough=stationClimateDaysIndex.data_through;
  const bit=1<<Number(metric.bit);
  const dates=stationClimateDaysPeriodDates(periodId,year);
  let count=0, validDays=0;
  const missingDates=[];
  const elapsedDates=[];
  dates.forEach(iso=>{
    if(iso>dataThrough) return;
    elapsedDates.push(iso);
    const pair=stationClimateDaysPair(stationId,iso);
    if(!pair || !(Number(pair[1])&bit)){
      missingDates.push(iso);
      return;
    }
    validDays++;
    if(Number(pair[0])&bit) count++;
  });
  const periodFinished=dates.length>0 && dataThrough>=dates[dates.length-1];
  return {count,validDays,missingDates,elapsedDays:elapsedDates.length,periodFinished,dates};
}

function stationClimateDaysCurrentCumulative(stationId,metric){
  const year=Number(stationClimateDaysIndex.current_year);
  const dataThrough=stationClimateDaysIndex.data_through;
  const bit=1<<Number(metric.bit);
  let total=0;
  const missingDates=[];
  const result=(stationClimateDaysIndex.labels||[]).map(label=>{
    const iso=`${year}-${label}`;
    if(iso>dataThrough) return null;
    const pair=stationClimateDaysPair(stationId,iso);
    if(!pair || !(Number(pair[1])&bit)){
      missingDates.push(iso);
      return null;
    }
    if(Number(pair[0])&bit) total++;
    return total;
  });
  result.missingDates=missingDates;
  result.count=total;
  return result;
}

function stationClimateDaysDailyClimate(profile,metricId){
  const cumulative=profile?.climate_mean_cumulative?.[metricId]||[];
  return cumulative.map((value,index)=>{
    if(value===null || value===undefined) return null;
    const previous=index>0?cumulative[index-1]:0;
    if(previous===null || previous===undefined) return null;
    return Number(value)-Number(previous);
  });
}

function stationClimateDaysNonLeapIndex(monthDay){
  return (stationClimateDaysIndex.labels||[]).indexOf(monthDay);
}

function stationClimateDaysClimateMeanToDate(profile,metricId,periodId,dataThrough){
  const year=Number(stationClimateDaysIndex.current_year);
  const daily=stationClimateDaysDailyClimate(profile,metricId);
  let total=0;
  stationClimateDaysPeriodDates(periodId,year).forEach(iso=>{
    if(iso>dataThrough) return;
    const index=stationClimateDaysNonLeapIndex(iso.slice(5));
    const value=index>=0?daily[index]:null;
    if(value!==null && value!==undefined && Number.isFinite(Number(value))) total+=Number(value);
  });
  return total;
}

function stationClimateDaysHistoricalEntries(profile,metricId,periodId){
  return (profile?.counts?.[metricId]?.[periodId]||[]).map(item=>({
    year:Number(item[0]),
    count:Number(item[1]),
    validDays:Number(item[2])
  }));
}

function stationClimateDaysFormat(value,decimals=0){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function stationClimateDaysHexToRgba(hex,alpha){
  const value=String(hex||"#c43d2f").replace("#","");
  const normalized=value.length===3?value.split("").map(char=>char+char).join(""):value;
  const number=parseInt(normalized,16);
  return `rgba(${(number>>16)&255},${(number>>8)&255},${number&255},${alpha})`;
}

function stationClimateDaysHistoricalCumulative(profile,metricId){
  const encoded=profile?.historical_event_days?.[metricId]||[];
  const length=(stationClimateDaysIndex?.labels||[]).length||365;
  return encoded.map(item=>{
    const year=String(item?.[0]??"");
    const eventDays=new Set((item?.[1]||[]).map(value=>Number(value)));
    let total=0;
    const data=Array.from({length},(_,index)=>{
      if(eventDays.has(index)) total+=1;
      return total;
    });
    return {year,data};
  }).filter(item=>item.year);
}


const STATION_CLIMATE_VALUE_META={
  tmax:{label:"Tmax-Mittel",unit:"°C",pairIndex:2,aggregation:"mean",colorParam:"temp",high:"wärmster",low:"kältester"},
  tmin:{label:"Tmin-Mittel",unit:"°C",pairIndex:3,aggregation:"mean",colorParam:"temp",high:"wärmster",low:"kältester"},
  tmean:{label:"Tmed-Mittel",unit:"°C",pairIndex:4,aggregation:"mean",colorParam:"temp",high:"wärmster",low:"kältester"},
  rain:{label:"Niederschlag",unit:"mm",pairIndex:5,aggregation:"sum",colorParam:"rain",high:"nassester",low:"trockenster"},
  sun:{label:"Sonnenscheindauer",unit:"h",pairIndex:6,aggregation:"sum",colorParam:"sun",high:"sonnigster",low:"sonnenärmster"}
};
const STATION_CLIMATE_PERIODS=[
  ...["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"].map((label,index)=>({key:`month-${index+1}`,kind:"months",index,label})),
  {key:"winter",kind:"seasons",index:0,label:"Winter (DJF)",separator:true},
  {key:"spring",kind:"seasons",index:1,label:"Frühling (MAM)"},
  {key:"summer",kind:"seasons",index:2,label:"Sommer (JJA)"},
  {key:"autumn",kind:"seasons",index:3,label:"Herbst (SON)"},
  {key:"year",kind:"annual",index:0,label:"Jahr",separator:true,annual:true}
];

function stationClimateReferenceFromValue(value){
  const normalized=String(value||"1991-2020");
  const match=normalized.match(/^(\d{4})-(\d{4})$/);
  if(!match) return {start:1991,end:2020,label:"1991–2020"};
  return {start:Number(match[1]),end:Number(match[2]),label:`${match[1]}–${match[2]}`};
}
function stationClimateProfileReference(){
  return stationClimateReferenceFromValue(document.getElementById("stationProfileReferenceSelect")?.value);
}
function stationClimateDaysTableReference(){
  return stationClimateReferenceFromValue(document.getElementById("stationClimateValuesReference")?.value);
}
function stationClimateValueIso(year,month,day){
  return `${year}-${String(month).padStart(2,"0")}-${String(day).padStart(2,"0")}`;
}
function stationClimateValueMonthEnd(year,month){
  return new Date(Date.UTC(year,month,0)).getUTCDate();
}
function stationClimateValueAggregateCurrentStats(stationId,startIso,endIso,meta,coverage){
  const dataThrough=String(stationClimateDaysIndex?.data_through||"");
  if(!dataThrough || dataThrough<endIso) return {value:null,valid:0,expected:0};
  const start=new Date(`${startIso}T00:00:00Z`);
  const end=new Date(`${endIso}T00:00:00Z`);
  let expected=0,valid=0,total=0;
  for(let cursor=new Date(start);cursor<=end;cursor.setUTCDate(cursor.getUTCDate()+1)){
    expected++;
    const iso=cursor.toISOString().slice(0,10);
    const pair=stationClimateDaysPair(stationId,iso);
    const raw=pair?.[meta.pairIndex];
    if(raw===null || raw===undefined || !Number.isFinite(Number(raw))) continue;
    valid++;
    total+=Number(raw)/10;
  }
  const required=Math.ceil(expected*Number(coverage||1));
  const value=valid>=required&&valid
    ?Math.round((meta.aggregation==="mean"?total/valid:total)*10)/10
    :null;
  return {value,valid,expected};
}
function stationClimateValueCurrentRow(stationId,block,meta){
  const year=Number(stationClimateDaysIndex?.current_year);
  if(!Number.isFinite(year)) return null;
  const coverage=Number(block?.coverage ?? (meta.aggregation==="sum"?1:.98));
  const monthStats=Array.from({length:12},(_,index)=>{
    const month=index+1;
    return stationClimateValueAggregateCurrentStats(
      stationId,
      stationClimateValueIso(year,month,1),
      stationClimateValueIso(year,month,stationClimateValueMonthEnd(year,month)),
      meta,coverage
    );
  });
  const seasonRanges=[
    [`${year-1}-12-01`,stationClimateValueIso(year,2,stationClimateValueMonthEnd(year,2))],
    [`${year}-03-01`,`${year}-05-31`],
    [`${year}-06-01`,`${year}-08-31`],
    [`${year}-09-01`,`${year}-11-30`]
  ];
  const seasonStats=seasonRanges.map(([start,end])=>stationClimateValueAggregateCurrentStats(stationId,start,end,meta,coverage));
  const annualStats=stationClimateValueAggregateCurrentStats(stationId,`${year}-01-01`,`${year}-12-31`,meta,coverage);
  const row={
    year,current:true,
    months:monthStats.map(item=>item.value),
    seasons:seasonStats.map(item=>item.value),
    annual:annualStats.value,
    monthQuality:monthStats.map(item=>[item.valid,item.expected]),
    seasonQuality:seasonStats.map(item=>[item.valid,item.expected]),
    annualQuality:[annualStats.valid,annualStats.expected]
  };
  if(![...row.months,...row.seasons,row.annual].some(value=>Number.isFinite(Number(value)))) return null;
  return row;
}
function stationClimateValueHistoricalRows(block){
  return (block?.years||[]).map(raw=>({
    year:Number(raw?.[0]),current:false,
    months:raw?.[1]||[],seasons:raw?.[2]||[],annual:raw?.[3]??null,
    monthQuality:raw?.[4]||[],seasonQuality:raw?.[5]||[],annualQuality:raw?.[6]||null
  })).filter(row=>Number.isFinite(row.year));
}
function stationClimateValueRows(block,stationId,meta,{includeCurrent=true}={}){
  const rows=stationClimateValueHistoricalRows(block);
  if(includeCurrent){
    const current=stationClimateValueCurrentRow(stationId,block,meta);
    if(current) rows.push(current);
  }
  return rows.sort((a,b)=>b.year-a.year);
}
function stationClimateValueColumns(view){
  const months=STATION_CLIMATE_PERIODS.filter(item=>item.kind==="months");
  const seasons=STATION_CLIMATE_PERIODS.filter(item=>item.kind==="seasons");
  const annual=STATION_CLIMATE_PERIODS.find(item=>item.kind==="annual");
  if(view==="months") return [...months,annual];
  if(view==="seasons") return [...seasons,annual];
  return [...months,...seasons,annual];
}
function stationClimateValuePeriodByKey(key){
  return STATION_CLIMATE_PERIODS.find(item=>item.key===key)||STATION_CLIMATE_PERIODS.at(-1);
}
function stationClimateValueFromRow(row,column){
  if(column.kind==="months") return row?.months?.[column.index] ?? null;
  if(column.kind==="seasons") return row?.seasons?.[column.index] ?? null;
  return row?.annual ?? null;
}
function stationClimateValueQualityFromRow(row,column){
  if(column.kind==="months") return row?.monthQuality?.[column.index] ?? null;
  if(column.kind==="seasons") return row?.seasonQuality?.[column.index] ?? null;
  return row?.annualQuality ?? null;
}
function stationClimateValueReferenceStats(block,column,reference){
  const values=stationClimateValueHistoricalRows(block)
    .filter(row=>row.year>=reference.start&&row.year<=reference.end)
    .map(row=>stationClimateValueFromRow(row,column))
    .filter(value=>Number.isFinite(Number(value)))
    .map(Number);
  return {value:values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null,count:values.length};
}
function stationClimateValueReference(block,column,reference=stationClimateProfileReference()){
  return stationClimateValueReferenceStats(block,column,reference).value;
}
function stationClimateValueFormat(value,meta){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return `${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} ${meta.unit}`;
}
function stationClimateValueAnomaly(value,reference,meta){
  value=Number(value);reference=Number(reference);
  if(!Number.isFinite(value)||!Number.isFinite(reference)) return null;
  if(meta.colorParam==="temp") return value-reference;
  if(reference===0) return null;
  return (value/reference-1)*100;
}
function stationClimateValueAnomalyText(anomaly,meta){
  if(!Number.isFinite(anomaly)) return "";
  const sign=anomaly>0?"+":"";
  if(meta.colorParam==="temp") return `${sign}${anomaly.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} K`;
  return `${sign}${anomaly.toLocaleString("de-DE",{maximumFractionDigits:0})} %`;
}
function stationClimateValueQualityText(quality){
  if(!Array.isArray(quality)||quality.length<2) return "";
  const valid=Number(quality[0]),expected=Number(quality[1]);
  if(!Number.isFinite(valid)||!Number.isFinite(expected)||expected<=0) return "";
  return `${(valid/expected*100).toLocaleString("de-DE",{maximumFractionDigits:1})} % (${valid}/${expected} Tage)`;
}
function stationClimateValueRankInfo(rows,column,value,meta){
  const available=rows.map(row=>({year:row.year,value:Number(stationClimateValueFromRow(row,column))}))
    .filter(item=>Number.isFinite(item.value));
  if(!available.length||!Number.isFinite(Number(value))) return null;
  const sortedHigh=[...available].sort((a,b)=>b.value-a.value||a.year-b.year);
  const sortedLow=[...available].sort((a,b)=>a.value-b.value||a.year-b.year);
  const highRank=1+sortedHigh.filter(item=>item.value>Number(value)).length;
  const lowRank=1+sortedLow.filter(item=>item.value<Number(value)).length;
  const highYears=sortedHigh.filter(item=>item.value===sortedHigh[0].value).map(item=>item.year);
  const lowYears=sortedLow.filter(item=>item.value===sortedLow[0].value).map(item=>item.year);
  return {highRank,lowRank,total:available.length,highYears,lowYears,highValue:sortedHigh[0].value,lowValue:sortedLow[0].value,
    recordHigh:Math.abs(Number(value)-sortedHigh[0].value)<1e-9,recordLow:Math.abs(Number(value)-sortedLow[0].value)<1e-9,
    highLabel:meta.high,lowLabel:meta.low};
}
function stationClimateValueCell(row,column,block,meta,reference,allRows){
  const value=stationClimateValueFromRow(row,column);
  const quality=stationClimateValueQualityFromRow(row,column);
  const exactQualityText=stationClimateValueQualityText(quality);
  const qualityText=exactQualityText || (meta.aggregation==="mean"?"≥98 %":"100 %");
  if(value===null||value===undefined||!Number.isFinite(Number(value))){
    const title=qualityText?`Datenabdeckung: ${qualityText} · Periode nicht ausreichend vollständig`:"Keine ausreichenden Daten";
    return `<td class="${column.separator?"period-separator ":""}${column.annual?"annual-cell ":""}no-value" title="${title}">–${qualityText?`<span class="station-climate-quality">${qualityText.split(" ")[0]}%</span>`:""}</td>`;
  }
  const ref=stationClimateValueReference(block,column,reference);
  const anomaly=stationClimateValueAnomaly(value,ref,meta);
  const rank=stationClimateValueRankInfo(allRows,column,value,meta);
  let style="",parts=[];
  if(Number.isFinite(anomaly)){
    const background=interpolateAnomalyColor(meta.colorParam,anomaly);
    style=`background:${background};color:${readableTextColor(background)}`;
    parts.push(`Mittel ${reference.label}: ${stationClimateValueFormat(ref,meta)}`,`Abweichung: ${stationClimateValueAnomalyText(anomaly,meta)}`);
  }
  if(rank) parts.push(`Rang hoch: ${rank.highRank}/${rank.total} (${rank.highLabel})`,`Rang niedrig: ${rank.lowRank}/${rank.total} (${rank.lowLabel})`);
  if(qualityText) parts.push(`Datenabdeckung: ${qualityText}`);
  const recordLabel=rank?.recordHigh?rank.highLabel:rank?.recordLow?rank.lowLabel:"";
  const metaText=rank?`R${rank.highRank}/${rank.total}`:"";
  return `<td class="${column.separator?"period-separator ":""}${column.annual?"annual-cell":""}" style="${style}" title="${parts.join(" · ")}"><span class="station-climate-cell-main">${stationClimateValueFormat(value,meta)}</span><span class="station-climate-cell-meta">${metaText}${qualityText?`<span class="station-climate-quality">${qualityText.split(" ")[0]}%</span>`:""}${recordLabel?`<span class="station-climate-record">${recordLabel}</span>`:""}</span></td>`;
}
function stationClimateValuesLegend(meta,containerId="stationClimateValuesLegend"){
  const container=document.getElementById(containerId);if(!container)return;
  const values=meta.colorParam==="temp"?[-3,-1,0,1,3]:[-50,-25,0,25,50];
  container.innerHTML=values.map(value=>{
    const background=interpolateAnomalyColor(meta.colorParam,value);
    const label=meta.colorParam==="temp"?`${value>0?"+":""}${value} K`:`${value>0?"+":""}${value} %`;
    return `<span class="anomaly-legend-item"><span class="anomaly-legend-swatch" style="background:${background}"></span>${label}</span>`;
  }).join("");
}
function stationClimateValueHeader(columns,clickable=false){
  return `<tr><th class="year-cell">Jahr</th>${columns.map(column=>`<th class="${column.separator?"period-separator ":""}${column.annual?"annual-cell":""}" ${clickable?`data-climate-period="${column.key}" onclick="stationProfileSelectClimateTrendPeriod('${column.key}')"`:""}>${column.label}</th>`).join("")}</tr>`;
}
function stationClimateValueReferenceRow(block,columns,meta,reference){
  return columns.map(column=>{
    const stats=stationClimateValueReferenceStats(block,column,reference);
    const title=stats.count?`${stats.count} auswertbare Jahre im Referenzzeitraum`:"Keine auswertbaren Referenzjahre";
    return `<td class="${column.separator?"period-separator ":""}${column.annual?"annual-cell":""}" title="${title}"><span class="station-climate-cell-main">${stationClimateValueFormat(stats.value,meta)}</span><span class="station-climate-cell-meta">n=${stats.count}</span></td>`;
  }).join("");
}
function stationClimateValuePeriodLabel(column){return column?.label||"Zeitraum";}
function stationClimateValueExtremeRows(block,column){
  const rows=stationClimateValueHistoricalRows(block).map(row=>({year:row.year,value:Number(stationClimateValueFromRow(row,column))})).filter(item=>Number.isFinite(item.value));
  if(!rows.length)return null;
  const max=Math.max(...rows.map(item=>item.value)),min=Math.min(...rows.map(item=>item.value));
  return {max,min,maxYears:rows.filter(item=>item.value===max).map(item=>item.year),minYears:rows.filter(item=>item.value===min).map(item=>item.year),count:rows.length};
}
function stationProfileClimateNormalRender(block,meta,reference,columns){
  const table=document.getElementById("stationProfileClimateNormalTable"),head=document.getElementById("stationProfileClimateNormalHead"),body=document.getElementById("stationProfileClimateNormalBody");
  if(!table||!head||!body)return;
  table.dataset.view=document.getElementById("stationProfileClimateValuesView")?.value||"all";
  head.innerHTML=stationClimateValueHeader(columns,false);
  body.innerHTML=`<tr><td class="year-cell">${reference.label}</td>${stationClimateValueReferenceRow(block,columns,meta,reference)}</tr>`;
  const title=document.getElementById("stationProfileClimateNormalTitle");if(title)title.textContent=`Klimanormalwerte ${reference.label}`;
}
function stationProfileClimateRecordsRender(block,meta){
  const body=document.querySelector("#stationProfileClimateRecordsTable tbody");if(!body)return;
  body.innerHTML=STATION_CLIMATE_PERIODS.map(column=>{
    const ex=stationClimateValueExtremeRows(block,column);
    if(!ex)return `<tr><td>${column.label}</td><td colspan="4">–</td></tr>`;
    return `<tr><td>${column.label}</td><td>${stationClimateValueFormat(ex.max,meta)}</td><td>${ex.maxYears.join(", ")}</td><td>${stationClimateValueFormat(ex.min,meta)}</td><td>${ex.minYears.join(", ")}</td></tr>`;
  }).join("");
}
function stationProfileClimateSummaryText(stationId,reference){
  const year=Number(stationClimateDaysIndex?.current_year);
  const tmeta=STATION_CLIMATE_VALUE_META.tmean;
  const tblock=stationProfileProfile?.climate_value_tables?.tmean;
  if(!tblock)return "Die neue klimatologische Jahreszusammenfassung wird nach dem Profil-Neuaufbau verfügbar.";
  const trow=stationClimateValueCurrentRow(stationId,tblock,tmeta);
  if(!trow)return `${year}: Noch keine vollständig abgeschlossene Periode in der neuen Klimatabelle.`;
  let warmer=0,cooler=0,complete=0;
  STATION_CLIMATE_PERIODS.filter(c=>c.kind==="months").forEach(column=>{
    const value=stationClimateValueFromRow(trow,column),ref=stationClimateValueReference(tblock,column,reference);
    if(!Number.isFinite(Number(value))||!Number.isFinite(Number(ref)))return;
    complete++;if(value>ref)warmer++;else if(value<ref)cooler++;
  });
  const summer=stationClimateValuePeriodByKey("summer");
  const parts=[`${year}: ${warmer} von ${complete} abgeschlossenen Monaten wärmer als ${reference.label}${cooler?`, ${cooler} kühler`:""}.`];
  const descriptors=[
    ["tmean","Temperatur",(a)=>`${stationClimateValueAnomalyText(a,STATION_CLIMATE_VALUE_META.tmean)}`],
    ["rain","Niederschlag",(a)=>`${(100+a).toLocaleString("de-DE",{maximumFractionDigits:0})} % des Mittels`],
    ["sun","Sonnenschein",(a)=>`${(100+a).toLocaleString("de-DE",{maximumFractionDigits:0})} % des Mittels`]
  ];
  const summerBits=[];
  descriptors.forEach(([id,label,format])=>{
    const meta=STATION_CLIMATE_VALUE_META[id],block=stationProfileProfile?.climate_value_tables?.[id];
    if(!block)return;const row=stationClimateValueCurrentRow(stationId,block,meta);
    const value=stationClimateValueFromRow(row,summer),ref=stationClimateValueReference(block,summer,reference);
    const anomaly=stationClimateValueAnomaly(value,ref,meta);if(Number.isFinite(anomaly))summerBits.push(`${label}: ${format(anomaly)}`);
  });
  if(summerBits.length)parts.push(`Sommer (JJA): ${summerBits.join(" · ")}.`);
  return parts.join(" ");
}
function stationProfilePopulateClimateTrendPeriods(){
  const select=document.getElementById("stationProfileClimateTrendPeriod");if(!select)return;
  const previous=select.value||"year";
  select.innerHTML=STATION_CLIMATE_PERIODS.map(item=>`<option value="${item.key}">${item.label}</option>`).join("");
  select.value=STATION_CLIMATE_PERIODS.some(item=>item.key===previous)?previous:"year";
}
function stationProfileSelectClimateTrendPeriod(key){
  const select=document.getElementById("stationProfileClimateTrendPeriod");
  if(select&&STATION_CLIMATE_PERIODS.some(item=>item.key===key)){select.value=key;renderStationProfileClimateTrend();}
}
function stationClimateRollingSeries(points,windowYears){
  if(!windowYears)return points.map(()=>null);
  const byYear=new Map(points.map(p=>[p.year,p.value]));
  return points.map(point=>{
    const values=[];
    for(let year=point.year-windowYears+1;year<=point.year;year++){
      const value=byYear.get(year);if(!Number.isFinite(value))return null;values.push(value);
    }
    return values.reduce((sum,value)=>sum+value,0)/values.length;
  });
}
function stationClimateLinearTrend(points){
  const valid=points.filter(p=>Number.isFinite(p.value));
  if(valid.length<2)return {slope:null,data:points.map(()=>null)};
  const mx=valid.reduce((s,p)=>s+p.year,0)/valid.length,my=valid.reduce((s,p)=>s+p.value,0)/valid.length;
  const denom=valid.reduce((s,p)=>s+(p.year-mx)**2,0);
  if(!denom)return {slope:null,data:points.map(()=>null)};
  const slope=valid.reduce((s,p)=>s+(p.year-mx)*(p.value-my),0)/denom;
  const intercept=my-slope*mx;
  return {slope,data:points.map(p=>slope*p.year+intercept)};
}
async function renderStationProfileClimateTrend(){
  const canvas=document.getElementById("stationProfileClimateTrendChart");if(!canvas||!stationProfileProfile)return;
  const stationId=document.getElementById("stationProfileStationSelect")?.value||"";
  const station=(stationClimateDaysIndex?.stations||[]).find(item=>item.id===stationId);
  const parameter=document.getElementById("stationProfileClimateValuesParameter")?.value||"tmean";
  const meta=STATION_CLIMATE_VALUE_META[parameter],block=stationProfileProfile?.climate_value_tables?.[parameter];
  if(!block)return;
  const period=stationClimateValuePeriodByKey(document.getElementById("stationProfileClimateTrendPeriod")?.value||"year");
  const reference=stationClimateProfileReference();
  const from=Number(document.getElementById("stationProfileFromSelect")?.value||station?.start_year||0);
  const rows=stationClimateValueRows(block,stationId,meta).filter(row=>row.year>=from).sort((a,b)=>a.year-b.year);
  const points=rows.map(row=>({year:row.year,value:Number(stationClimateValueFromRow(row,period))})).filter(p=>Number.isFinite(p.value));
  const rollingYears=Number(document.getElementById("stationProfileRollingSelect")?.value)||0;
  const rolling=stationClimateRollingSeries(points,rollingYears);
  const trend=stationClimateLinearTrend(points);
  const ref=stationClimateValueReference(block,period,reference);
  const refData=points.map(()=>Number.isFinite(ref)?ref:null);
  if(stationProfileClimateTrendChart)stationProfileClimateTrendChart.destroy();
  stationProfileClimateTrendChart=new Chart(canvas,{
    type:"line",
    data:{labels:points.map(p=>String(p.year)),datasets:[
      {label:meta.label,data:points.map(p=>p.value),borderColor:"#4f6f8f",backgroundColor:"rgba(79,111,143,.12)",borderWidth:2,pointRadius:2,tension:.1},
      ...(rollingYears?[{label:`${rollingYears}-jähriges gleitendes Mittel`,data:rolling,borderColor:"#202020",borderWidth:2.4,pointRadius:0,tension:.15}]:[]),
      {label:`Mittel ${reference.label}`,data:refData,borderColor:"#777",borderDash:[7,5],borderWidth:1.6,pointRadius:0},
      {label:"Linearer Trend",data:trend.data,borderColor:"#b24a3a",borderDash:[3,4],borderWidth:1.8,pointRadius:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{
      title:{display:true,text:`${meta.label} · ${period.label} – ${station?.name||stationId}`},
      subtitle:{display:true,text:Number.isFinite(trend.slope)?`Linearer Trend seit ${from}: ${trend.slope>=0?"+":""}${(trend.slope*10).toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} ${meta.unit}/Dekade`:"Für einen linearen Trend liegen zu wenige Werte vor.",color:"#666"},
      datalabels:{display:false}
    },scales:{y:{title:{display:true,text:meta.unit}},x:{ticks:{maxTicksLimit:18,maxRotation:0}}}}
  });
  document.getElementById("stationProfileClimateTrendTitle").textContent=`${meta.label} · ${period.label}`;
  document.getElementById("stationProfileClimateTrendNote").textContent=`Messreihe ab ${from} · Referenz ${reference.label}${rollingYears?` · ${rollingYears}-jähriges gleitendes Mittel`:""}`;
  initializeChartExportButtons();
}
function stationProfilePopulateClimateCompare(){
  const select=document.getElementById("stationProfileClimateCompareStation");if(!select||!stationClimateDaysIndex)return;
  const currentId=document.getElementById("stationProfileStationSelect")?.value||"";
  const current=(stationClimateDaysIndex.stations||[]).find(item=>item.id===currentId);
  const previous=select.value;
  const stations=(stationClimateDaysIndex.stations||[]).filter(item=>item.id!==currentId).slice().sort((a,b)=>a.name.localeCompare(b.name,"de"));
  select.innerHTML=stations.map(item=>`<option value="${item.id}">${item.name} (${item.id})</option>`).join("");
  if(stations.some(item=>item.id===previous))select.value=previous;
  else{
    const nearest=stations.map(item=>({item,d:stationProfileDistanceKm(current,item)})).sort((a,b)=>a.d-b.d)[0]?.item;
    if(nearest)select.value=nearest.id;
  }
}
async function stationProfileClimateLoadProfile(stationId){
  if(!stationId)return null;
  if(stationProfileClimateCompareCache.has(stationId))return stationProfileClimateCompareCache.get(stationId);
  const station=(stationClimateDaysIndex?.stations||[]).find(item=>item.id===stationId);if(!station)return null;
  const promise=dashboardFetch(station.file,{cache:"no-store"}).then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();});
  stationProfileClimateCompareCache.set(stationId,promise);
  try{return await promise;}catch(error){stationProfileClimateCompareCache.delete(stationId);throw error;}
}
async function renderStationProfileClimateComparison(){
  const body=document.querySelector("#stationProfileClimateCompareTable tbody");if(!body||!stationProfileProfile)return;
  const currentId=document.getElementById("stationProfileStationSelect")?.value||"";
  const otherId=document.getElementById("stationProfileClimateCompareStation")?.value||"";
  const a=(stationClimateDaysIndex.stations||[]).find(item=>item.id===currentId),b=(stationClimateDaysIndex.stations||[]).find(item=>item.id===otherId);
  document.getElementById("stationProfileClimateCompareA").textContent=a?.name||"Station A";
  document.getElementById("stationProfileClimateCompareB").textContent=b?.name||"Station B";
  if(!otherId){body.innerHTML='<tr><td colspan="4">Keine Vergleichsstation ausgewählt.</td></tr>';return;}
  body.innerHTML='<tr><td colspan="4">Vergleich wird geladen …</td></tr>';
  try{
    const other=await stationProfileClimateLoadProfile(otherId);
    const parameter=document.getElementById("stationProfileClimateValuesParameter")?.value||"tmean";
    const meta=STATION_CLIMATE_VALUE_META[parameter],blockA=stationProfileProfile?.climate_value_tables?.[parameter],blockB=other?.climate_value_tables?.[parameter];
    const reference=stationClimateProfileReference();
    if(!blockA||!blockB){body.innerHTML='<tr><td colspan="4">Für mindestens eine Station fehlen die neuen Klimawertetabellen.</td></tr>';return;}
    body.innerHTML=STATION_CLIMATE_PERIODS.map(column=>{
      const va=stationClimateValueReference(blockA,column,reference),vb=stationClimateValueReference(blockB,column,reference);
      const diff=Number.isFinite(va)&&Number.isFinite(vb)?va-vb:null;
      return `<tr><td>${column.label}</td><td>${stationClimateValueFormat(va,meta)}</td><td>${stationClimateValueFormat(vb,meta)}</td><td>${Number.isFinite(diff)?`${diff>0?"+":""}${diff.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} ${meta.unit}`:"–"}</td></tr>`;
    }).join("");
    document.getElementById("stationProfileClimateCompareNote").textContent=`Klimanormalwerte ${reference.label} · ${meta.label}`;
  }catch(error){body.innerHTML=`<tr><td colspan="4">Vergleich konnte nicht geladen werden: ${error.message}</td></tr>`;}
}
function stationProfileClimateCsvRows(){
  const parameter=document.getElementById("stationProfileClimateValuesParameter")?.value||"tmean";
  const meta=STATION_CLIMATE_VALUE_META[parameter],block=stationProfileProfile?.climate_value_tables?.[parameter];
  const stationId=document.getElementById("stationProfileStationSelect")?.value||"";
  const view=document.getElementById("stationProfileClimateValuesView")?.value||"all",columns=stationClimateValueColumns(view);
  if(!block)return {headers:[],rows:[]};
  const rows=stationClimateValueRows(block,stationId,meta);
  return {
    headers:["Jahr",...columns.map(c=>c.label)],
    rows:rows.map(row=>[row.year,...columns.map(column=>stationClimateValueFromRow(row,column)??"")])
  };
}
async function exportStationProfileClimateValues(format){
  try{
    const parameter=document.getElementById("stationProfileClimateValuesParameter")?.value||"tmean";
    const stationId=document.getElementById("stationProfileStationSelect")?.value||"";
    const station=(stationClimateDaysIndex?.stations||[]).find(item=>item.id===stationId);
    const title=`Stationsklima_${station?.name||stationId}_${STATION_CLIMATE_VALUE_META[parameter].label}`;
    if(format==="csv"){
      const {headers,rows}=stationProfileClimateCsvRows();if(!headers.length)throw new Error("Noch keine Klimatabellendaten verfügbar.");
      const content="\ufeff"+[headers,...rows].map(row=>row.map(csvEscape).join(";")).join("\r\n");
      const blob=new Blob([content],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob),link=document.createElement("a");
      link.href=url;link.download=safeExportFilename(title,"csv");document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);return;
    }
    const area=document.getElementById("stationProfileClimateValuesExportArea");if(!area||typeof html2canvas!=="function")throw new Error("Exportbibliothek konnte nicht geladen werden.");
    const canvas=await window.captureDashboardWithWhiteBackground(area,{
      scale:2.5,backgroundColor:"#ffffff",useCORS:true,logging:false,
      onclone(clone){
        const tableArea=clone.getElementById(area.id);if(!tableArea)return;
        Object.assign(tableArea.style,{width:`${area.scrollWidth}px`,height:"auto",maxHeight:"none",maxWidth:"none",overflow:"visible"});
        tableArea.scrollTop=0;tableArea.scrollLeft=0;
      }
    });
    if(format==="png"){triggerDataUrlDownload(canvas.toDataURL("image/png",1),safeExportFilename(title,"png"));return;}
    const {jsPDF}=window.jspdf||{};if(!jsPDF)throw new Error("PDF-Bibliothek konnte nicht geladen werden.");
    const pdf=new jsPDF({orientation:"landscape",unit:"mm",format:"a4",compress:true}),w=pdf.internal.pageSize.getWidth(),h=pdf.internal.pageSize.getHeight(),margin=8;
    pdf.setFont("helvetica","bold");pdf.setFontSize(12);pdf.text(title,margin,margin+4);
    const maxW=w-margin*2,maxH=h-margin*2-10,ratio=Math.min(maxW/canvas.width,maxH/canvas.height),iw=canvas.width*ratio,ih=canvas.height*ratio;
    pdf.addImage(canvas.toDataURL("image/png"),"PNG",(w-iw)/2,margin+10,iw,ih,undefined,"FAST");pdf.save(safeExportFilename(title,"pdf"));
  }catch(error){console.error(error);alert(`Export nicht möglich: ${error.message}`);}
}
async function renderStationProfileClimateValuesTable(){
  const table=document.getElementById("stationProfileClimateValuesTable"),head=document.getElementById("stationProfileClimateValuesHead"),body=document.getElementById("stationProfileClimateValuesBody");
  if(!table||!head||!body||!stationProfileProfile||!stationClimateDaysIndex)return;
  await loadStationClimateDaysCurrentMonths();
  const stationId=document.getElementById("stationProfileStationSelect")?.value||"";
  const station=(stationClimateDaysIndex.stations||[]).find(item=>item.id===stationId);
  const parameter=document.getElementById("stationProfileClimateValuesParameter")?.value||"tmean",view=document.getElementById("stationProfileClimateValuesView")?.value||"all";
  const meta=STATION_CLIMATE_VALUE_META[parameter],block=stationProfileProfile?.climate_value_tables?.[parameter],reference=stationClimateProfileReference(),columns=stationClimateValueColumns(view);
  table.dataset.view=view;
  document.getElementById("stationProfileClimateValuesTitle").textContent=`${meta.label} · ${station?.name||stationId||"Station"}`;
  document.getElementById("stationProfileClimateValuesSubtitle").textContent=meta.aggregation==="mean"
    ?`Monats-, Jahreszeiten- und Jahresmittel · Farbe: Abweichung zu ${reference.label}.`
    :`Monats-, Jahreszeiten- und Jahressummen · Farbe: prozentuale Abweichung zu ${reference.label}.`;
  if(!block){
    head.innerHTML='<tr><th class="year-cell">Jahr</th><th>Daten</th></tr>';body.innerHTML='<tr><td colspan="2">Die neue Klimatabelle wird beim nächsten vollständigen Stationsprofil-Lauf aufgebaut.</td></tr>';
    stationClimateValuesLegend(meta,"stationProfileClimateValuesLegend");return;
  }
  const rows=stationClimateValueRows(block,stationId,meta),currentYear=Number(stationClimateDaysIndex.current_year);
  head.innerHTML=stationClimateValueHeader(columns,true);
  body.innerHTML=rows.map(row=>`<tr class="${row.year===currentYear?"current-year":""}"><td class="year-cell">${row.year}</td>${columns.map(column=>stationClimateValueCell(row,column,block,meta,reference,rows)).join("")}</tr>`).join("");
  stationClimateValuesLegend(meta,"stationProfileClimateValuesLegend");
  document.getElementById("stationProfileClimateValuesNote").textContent=`Winter (DJF) gehört zum Jahr von Januar/Februar. Temperaturmittel benötigen mindestens 98 % Tagesabdeckung; Niederschlag (RSK) und Sonnenscheindauer (SDK) eine vollständig vorliegende Periode. R = Rang vom höchsten Wert aus. Referenz: ${reference.label}.`;
  stationProfileClimateNormalRender(block,meta,reference,columns);
  stationProfileClimateRecordsRender(block,meta);
  document.getElementById("stationProfileClimateSummary").textContent=stationProfileClimateSummaryText(stationId,reference);
}
async function renderStationProfileClimateValuesSuite(){
  await renderStationProfileClimateValuesTable();
  stationProfilePopulateClimateTrendPeriods();
  await renderStationProfileClimateTrend();
  stationProfilePopulateClimateCompare();
  await renderStationProfileClimateComparison();
}
function renderStationClimateValuesTable(stationOverride=null){
  const table=document.getElementById("stationClimateValuesTable"),head=document.getElementById("stationClimateValuesHead"),body=document.getElementById("stationClimateValuesBody");
  if(!table||!head||!body||!stationClimateDaysProfile||!stationClimateDaysIndex)return;
  const stationId=document.getElementById("stationClimateDaysStationSelect")?.value||"";
  const station=stationOverride||(stationClimateDaysIndex.stations||[]).find(item=>item.id===stationId);
  const parameter=document.getElementById("stationClimateValuesParameter")?.value||"tmean",view=document.getElementById("stationClimateValuesView")?.value||"all";
  const meta=STATION_CLIMATE_VALUE_META[parameter],block=stationClimateDaysProfile?.climate_value_tables?.[parameter],reference=stationClimateDaysTableReference(),columns=stationClimateValueColumns(view);
  table.dataset.view=view;
  document.getElementById("stationClimateValuesTitle").textContent=`${meta.label} · ${station?.name||stationId||"Station"}`;
  document.getElementById("stationClimateValuesSubtitle").textContent=meta.aggregation==="mean"
    ?`Monats-, Jahreszeiten- und Jahresmittel · Farbe: Abweichung zu ${reference.label}.`
    :`Monats-, Jahreszeiten- und Jahressummen · Farbe: prozentuale Abweichung zu ${reference.label}.`;
  if(!block){head.innerHTML='<tr><th class="year-cell">Jahr</th><th>Daten</th></tr>';body.innerHTML='<tr><td colspan="2">Die neue Klimatabelle wird beim nächsten vollständigen Stationsprofil-Lauf aufgebaut.</td></tr>';stationClimateValuesLegend(meta);return;}
  const rows=stationClimateValueRows(block,stationId,meta),currentYear=Number(stationClimateDaysIndex.current_year);
  head.innerHTML=stationClimateValueHeader(columns,false);
  body.innerHTML=rows.map(row=>`<tr class="${row.year===currentYear?"current-year":""}"><td class="year-cell">${row.year}</td>${columns.map(column=>stationClimateValueCell(row,column,block,meta,reference,rows)).join("")}</tr>`).join("");
  stationClimateValuesLegend(meta);
  document.getElementById("stationClimateValuesNote").textContent=`Winter (DJF) gehört zum Jahr von Januar/Februar. R = Rang vom höchsten Wert aus. Referenz: ${reference.label}. Datenabdeckung wird je Periode ausgewiesen.`;
}

function stationClimateDaysFrequencyMode(){
  return document.getElementById("stationClimateDaysFrequencyMode")?.value||"percent";
}

function stationClimateDaysFrequencyRecordText(record){
  if(!record?.month_day) return "–";
  const [month,day]=record.month_day.split("-").map(Number);
  const label=new Date(Date.UTC(2001,month-1,day)).toLocaleDateString("de-DE",{day:"numeric",month:"long"});
  const years=(record.years||[]).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);
  if(!years.length) return label;
  const shown=years.slice(0,5).join(", ");
  return `${label} (${shown}${years.length>5?` +${years.length-5}`:""})`;
}

function stationClimateDaysFrequencySeries(block,key,mode){
  return mode==="count"?(block?.counts?.[key]||[]):(block?.percent?.[key]||[]);
}

function stationClimateDaysFrequencyTooltip(block,key,index,label){
  const count=Number(block?.counts?.[key]?.[index]);
  const valid=Number(block?.valid_years?.[index]);
  const percent=Number(block?.percent?.[key]?.[index]);
  if(!Number.isFinite(valid)||valid<=0) return `${label}: keine auswertbaren Jahre`;
  const pct=Number.isFinite(percent)?percent.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
  return `${label}: ${Number.isFinite(count)?count:0} von ${valid} Jahren (${pct} %)`;
}

function stationClimateDaysFrequencyCsvRows(block,thresholds,unit){
  const labels=stationClimateDaysIndex?.labels||[];
  const headers=["Kalendertag","Datum","Gültige Jahre"];
  thresholds.forEach(threshold=>{
    headers.push(`≥ ${threshold} ${unit} Anzahl`,`≥ ${threshold} ${unit} Prozent`);
  });
  const rows=labels.map((monthDay,index)=>{
    const row=[monthDay,stationClimateDaysDateLabel(monthDay),block?.valid_years?.[index]??""];
    thresholds.forEach(threshold=>{
      const key=String(threshold);
      row.push(block?.counts?.[key]?.[index]??"",block?.percent?.[key]?.[index]??"");
    });
    return row;
  });
  return {headers,rows};
}

async function stationClimateDaysFrequencyExportConfig(kind){
  if(kind==="temperature"){
    const stationId=document.getElementById("stationClimateDaysStationSelect")?.value||"";
    const station=(stationClimateDaysIndex?.stations||[]).find(item=>item.id===stationId);
    return {
      block:stationClimateDaysProfile?.calendar_frequency?.temperature||null,
      thresholds:[25,30,35],
      unit:"°C",
      title:`Kalenderhäufigkeit Temperatur – ${station?.name||stationId||"Station"}`
    };
  }
  const stationId=document.getElementById("stationClimateDaysSnowFrequencyStationSelect")?.value||"";
  const station=(stationClimateDaysSnowFrequencyIndex?.stations||[]).find(item=>item.id===stationId);
  const block=stationId?await stationClimateDaysLoadSnowFrequency(stationId):null;
  return {
    block,
    thresholds:[1,5,10],
    unit:"cm",
    title:`Kalenderhäufigkeit Schneehöhe – ${station?.name||stationId||"Station"}`
  };
}

async function runStationClimateDaysFrequencyCsvExport(button,kind){
  const original=button.textContent;
  button.disabled=true;
  button.textContent="…";
  try{
    await new Promise(resolve=>requestAnimationFrame(resolve));
    const config=await stationClimateDaysFrequencyExportConfig(kind);
    if(!config?.block) throw new Error("Die Häufigkeitsdaten sind noch nicht geladen.");
    const {headers,rows}=stationClimateDaysFrequencyCsvRows(config.block,config.thresholds,config.unit);
    const separator=";";
    const content="\ufeff"+[headers,...rows].map(row=>row.map(csvEscape).join(separator)).join("\r\n");
    const blob=new Blob([content],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url;
    link.download=safeExportFilename(config.title,"csv");
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }catch(error){
    console.error(error);
    alert(`CSV-Download nicht möglich: ${error.message}`);
  }finally{
    button.disabled=false;
    button.textContent=original;
  }
}

function stationClimateDaysFrequencyChart(canvasId,existing,block,thresholds,colors,title){
  const canvas=document.getElementById(canvasId);
  if(!canvas||!block) return null;
  if(existing) existing.destroy();
  const mode=stationClimateDaysFrequencyMode();
  const labels=(stationClimateDaysIndex?.labels||[]).map(stationClimateDaysDateLabel);
  const datasets=thresholds.map((threshold,index)=>{
    const key=String(threshold);
    const label=title.includes("Schnee")?`≥ ${threshold} cm`:`≥ ${threshold} °C`;
    return {
      label,
      frequencyKey:key,
      data:stationClimateDaysFrequencySeries(block,key,mode),
      borderColor:colors[index],
      backgroundColor:colors[index],
      borderWidth:2.5,
      pointRadius:0,
      pointHoverRadius:3,
      spanGaps:false,
      fill:false,
      tension:.12
    };
  });
  return new Chart(canvas,{
    type:"line",
    data:{labels,datasets},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:"nearest",intersect:false,axis:"xy"},
      plugins:{
        title:{display:true,text:title},
        subtitle:{display:true,text:mode==="count"?"Absolute Anzahl der Jahre; Tooltip zeigt zusätzlich den Prozentanteil.":"Anteil der Jahre in Prozent; Tooltip zeigt zusätzlich die absolute Anzahl.",color:"#666"},
        datalabels:{display:false},
        tooltip:{callbacks:{label:context=>stationClimateDaysFrequencyTooltip(block,context.dataset.frequencyKey,context.dataIndex,context.dataset.label)}},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
      },
      scales:{
        x:{ticks:{maxTicksLimit:14,maxRotation:0}},
        y:{beginAtZero:true,suggestedMax:mode==="percent"?100:undefined,ticks:{precision:mode==="count"?0:1},title:{display:true,text:mode==="count"?"Anzahl Jahre":"Anteil der Jahre (%)"}}
      }
    }
  });
}

async function stationClimateDaysLoadSnowFrequency(stationId){
  if(stationClimateDaysSnowFrequencyProfileCache.has(stationId)) return stationClimateDaysSnowFrequencyProfileCache.get(stationId);
  if(!stationClimateDaysSnowFrequencyIndex){
    const response=await dashboardFetch("station_snow_height_index.json",{cache:"no-store"});
    if(!response.ok) return null;
    stationClimateDaysSnowFrequencyIndex=await response.json();
  }
  const station=(stationClimateDaysSnowFrequencyIndex?.stations||[]).find(item=>item.id===stationId);
  if(!station){
    stationClimateDaysSnowFrequencyProfileCache.set(stationId,null);
    return null;
  }
  const response=await dashboardFetch(station.file||`station_snow_height_profiles/${stationId}.json`,{cache:"no-store"});
  if(!response.ok) return null;
  const profile=await response.json();
  const block=profile?.calendar_frequency||null;
  stationClimateDaysSnowFrequencyProfileCache.set(stationId,block);
  return block;
}

function stationClimateDaysPopulateSnowFrequencyStations(preferredStation){
  const select=document.getElementById("stationClimateDaysSnowFrequencyStationSelect");
  const stations=stationClimateDaysSnowFrequencyIndex?.stations||[];
  if(!select||!stations.length) return null;

  const previous=select.value;
  if(select.options.length!==stations.length){
    select.innerHTML="";
    stations
      .slice()
      .sort((a,b)=>`${a.state||""} ${a.name||""}`.localeCompare(`${b.state||""} ${b.name||""}`,"de"))
      .forEach(item=>{
        const option=document.createElement("option");
        option.value=item.id;
        option.textContent=`${item.name} (${item.id}) · ${item.state||""}`;
        select.appendChild(option);
      });
  }

  if(previous && stations.some(item=>item.id===previous)){
    select.value=previous;
  }else if(preferredStation && stations.some(item=>item.id===preferredStation.id)){
    select.value=preferredStation.id;
  }else{
    const sameState=preferredStation?stations.find(item=>item.state===preferredStation.state):null;
    select.value=(sameState||stations[0])?.id||"";
  }
  return stations.find(item=>item.id===select.value)||null;
}

async function renderStationClimateDaysFrequency(stationOverride=null){
  if(!stationClimateDaysIndex||!stationClimateDaysProfile) return;
  const requestId=++stationClimateDaysFrequencyRequest;
  const stationId=document.getElementById("stationClimateDaysStationSelect")?.value;
  const station=stationOverride||stationClimateDaysIndex.stations.find(item=>item.id===stationId);
  if(!station) return;

  const temperature=stationClimateDaysProfile?.calendar_frequency?.temperature||null;
  const tempBody=document.querySelector("#stationClimateDaysTemperatureFrequencyRecords tbody");
  const tempNote=document.getElementById("stationClimateDaysTemperatureFrequencyNote");
  if(temperature){
    stationClimateDaysTemperatureFrequencyChart=stationClimateDaysFrequencyChart(
      "stationClimateDaysTemperatureFrequencyChart",
      stationClimateDaysTemperatureFrequencyChart,
      temperature,
      [25,30,35],
      ["#e7a62b","#df6b2f","#c63d2f"],
      `Kalenderhäufigkeit Temperatur – ${station.name}`
    );
    if(tempBody){
      tempBody.innerHTML=[25,30,35].map(threshold=>{
        const record=temperature.records?.[String(threshold)]||{};
        return `<tr><td><strong>≥ ${threshold} °C</strong></td><td>${stationClimateDaysFrequencyRecordText(record.earliest)}</td><td>${stationClimateDaysFrequencyRecordText(record.latest)}</td></tr>`;
      }).join("");
    }
    if(tempNote) tempNote.textContent="Je Kalendertag werden nur Jahre mit gültigem DWD-Tagesmaximum TXK im Nenner berücksichtigt. Der laufende Jahrgang ist nicht Teil der historischen Häufigkeit.";
  }else{
    if(stationClimateDaysTemperatureFrequencyChart){stationClimateDaysTemperatureFrequencyChart.destroy();stationClimateDaysTemperatureFrequencyChart=null;}
    if(tempBody) tempBody.innerHTML='<tr><td colspan="3">Häufigkeitsdaten werden beim nächsten vollständigen Kenntage-Profillauf ergänzt.</td></tr>';
    if(tempNote) tempNote.textContent="Noch keine historischen Kalenderhäufigkeiten im Stationsprofil vorhanden.";
  }

  let snow=null;
  let snowStation=null;
  try{
    if(!stationClimateDaysSnowFrequencyIndex){
      const response=await dashboardFetch("station_snow_height_index.json",{cache:"no-store"});
      if(response.ok) stationClimateDaysSnowFrequencyIndex=await response.json();
    }
    snowStation=stationClimateDaysPopulateSnowFrequencyStations(station);
    if(snowStation) snow=await stationClimateDaysLoadSnowFrequency(snowStation.id);
  }catch(_error){snow=null;}
  if(requestId!==stationClimateDaysFrequencyRequest) return;
  const snowBody=document.querySelector("#stationClimateDaysSnowFrequencyRecords tbody");
  const snowNote=document.getElementById("stationClimateDaysSnowFrequencyNote");
  if(snow && snowStation){
    stationClimateDaysSnowFrequencyChart=stationClimateDaysFrequencyChart(
      "stationClimateDaysSnowFrequencyChart",
      stationClimateDaysSnowFrequencyChart,
      snow,
      [1,5,10],
      ["#8fc7e8","#4f8fc4","#24527a"],
      `Kalenderhäufigkeit Schneehöhe – ${snowStation.name}`
    );
    if(snowBody){
      snowBody.innerHTML=[1,5,10].map(threshold=>{
        const record=snow.records?.[String(threshold)]||{};
        return `<tr><td><strong>≥ ${threshold} cm</strong></td><td>${stationClimateDaysFrequencyRecordText(record.earliest_second_half)}</td><td>${stationClimateDaysFrequencyRecordText(record.latest_first_half)}</td></tr>`;
      }).join("");
    }
    if(snowNote){
      const separate=snowStation.id!==station.id
        ?`Für ${station.name} liegt kein qualifiziertes Schneehöhenprofil vor; ausgewählt ist ${snowStation.name} (${snowStation.id}). `
        :"";
      snowNote.textContent=separate+"Je Kalendertag werden nur akzeptierte historische Schneehöhenjahre mit gültigem DWD-Wert SHK_TAG berücksichtigt. Angezeigt wird Schneedecke/Schneehöhe, nicht zwingend Neuschneefall.";
    }
  }else{
    if(stationClimateDaysSnowFrequencyChart){stationClimateDaysSnowFrequencyChart.destroy();stationClimateDaysSnowFrequencyChart=null;}
    if(snowBody) snowBody.innerHTML='<tr><td colspan="3">Für die gewählte Schneestation sind keine Kalenderhäufigkeiten verfügbar.</td></tr>';
    if(snowNote) snowNote.textContent="Bitte eine andere Schneestation wählen. Es werden nur Stationen mit ausreichend langen und vollständigen SHK_TAG-Reihen angeboten.";
  }
  initializeChartExportButtons();
}

async function updateStationClimateDays(){
  if(!stationClimateDaysIndex) return;
  const stationId=document.getElementById("stationClimateDaysStationSelect").value;
  if(!stationId){
    document.getElementById("stationClimateDaysSummary").textContent="Für diese Auswahl wurde keine Station gefunden.";
    return;
  }
  const station=stationClimateDaysIndex.stations.find(item=>item.id===stationId);
  const metric=stationClimateDaysMetric();
  const period=stationClimateDaysPeriod();
  if(!station || !metric) return;
  document.getElementById("stationClimateDaysSummary").textContent=`${station.name}: Kenntage werden geladen …`;

  try{
    const [profileResponse]=await Promise.all([
      dashboardFetch(station.file,{cache:"no-store"}),
      loadStationClimateDaysCurrentMonths()
    ]);
    if(!profileResponse.ok) throw new Error(`Profildatei konnte nicht geladen werden (HTTP ${profileResponse.status}).`);
    stationClimateDaysProfile=await profileResponse.json();
    renderStationClimateValuesTable(station);
    renderStationClimateDaysFrequency(station);

    const currentPeriod=stationClimateDaysCurrentPeriod(stationId,metric,period.id);
    const currentCumulative=stationClimateDaysCurrentCumulative(stationId,metric);
    const climateCumulative=stationClimateDaysProfile.climate_mean_cumulative?.[metric.id]||[];
    const climateToDate=stationClimateDaysClimateMeanToDate(
      stationClimateDaysProfile,metric.id,period.id,stationClimateDaysIndex.data_through
    );
    const historical=stationClimateDaysHistoricalEntries(stationClimateDaysProfile,metric.id,period.id);
    const historicalCumulative=stationClimateDaysHistoricalCumulative(stationClimateDaysProfile,metric.id);
    const top10=[...historical].sort((a,b)=>b.count-a.count || a.year-b.year).slice(0,10);
    const record=top10[0]||null;
    const missing=currentPeriod.missingDates.length;
    const currentLabel=currentPeriod.periodFinished?String(stationClimateDaysIndex.current_year):`${stationClimateDaysIndex.current_year} (bis Datenstand)`;

    document.getElementById("stationClimateDaysCurrentStat").textContent=`${currentPeriod.count} ${currentPeriod.count===1?"Tag":"Tage"} · ${period.label}`;
    document.getElementById("stationClimateDaysMeanStat").textContent=`${stationClimateDaysFormat(climateToDate,1)} Tage bis zum gleichen Stand`;
    document.getElementById("stationClimateDaysRecordStat").textContent=record?`${record.count} Tage (${record.year})` : "–";
    document.getElementById("stationClimateDaysMissingStat").textContent=missing===0?"Keine bis zum Datenstand":`${missing} ${missing===1?"Tag":"Tage"}`;

    const dwdName=metric.dwd_name && metric.dwd_name!==metric.short_label?` · DWD: ${metric.dwd_name}`:"";
    const missingText=missing>0
      ? ` Bis zum Datenstand fehlen ${missing} auswertbare ${metric.field==="tx"?"Tmax":"Tmin"}-Tageswerte; fehlende Tage werden nicht als Kenntag gezählt.`
      : " Bis zum Datenstand liegen alle benötigten Temperaturwerte vor.";
    document.getElementById("stationClimateDaysSummary").textContent=[
      `${station.name} (${station.id})`,
      station.state||"Bundesland unbekannt",
      station.height===null||station.height===undefined?null:`${station.height} m ü. NHN`,
      `${metric.label}: ${metric.definition}${dwdName}`,
      `historische Auswertung ${station.start_year}–${station.end_year}`
    ].filter(Boolean).join(" · ")+`.${missingText}`;

    const historicalCumulativeDatasets=historicalCumulative.map(series=>({
      label:series.year,
      data:series.data,
      borderColor:"rgba(70,86,104,.16)",
      borderWidth:1,
      pointRadius:0,
      fill:false,
      tension:.08,
      isHistoricalYear:true
    }));

    if(stationClimateDaysCumulativeChart) stationClimateDaysCumulativeChart.destroy();
    stationClimateDaysCumulativeChart=new Chart(document.getElementById("stationClimateDaysCumulativeChart"),{
      type:"line",
      data:{
        labels:(stationClimateDaysIndex.labels||[]).map(stationClimateDaysDateLabel),
        datasets:[
          ...historicalCumulativeDatasets,
          {
            label:`Mittel ${hyrasReferenceDisplay()}`,
            data:climateCumulative,
            borderColor:"#202020",
            borderWidth:2.2,
            borderDash:[8,5],
            pointRadius:0,
            fill:false,
            tension:.1
          },
          {
            label:String(stationClimateDaysIndex.current_year),
            data:currentCumulative,
            borderColor:metric.color||"#c43d2f",
            backgroundColor:stationClimateDaysHexToRgba(metric.color,.12),
            borderWidth:3.2,
            pointRadius:0,
            spanGaps:true,
            fill:false,
            tension:.1
          }
        ]
      },
      options:{
        responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
        plugins:{
          title:{display:true,text:`${metric.label} im Jahresverlauf – ${station.name}`},
          subtitle:{
            display:true,
            text:historicalCumulative.length
              ?`${historicalCumulative.length} ausreichend vollständige historische Jahre in Grau · aktuelles Jahr farbig · Mittel 1991–2020 gestrichelt`
              :"Historische Jahresverläufe werden nach dem nächsten vollständigen Profilauf ergänzt.",
            color:"#666",
            font:{size:12},
            padding:{bottom:10}
          },
          legend:{
            labels:{filter:item=>item.text==="Mittel 1991–2020" || item.text===String(stationClimateDaysIndex.current_year)}
          },
          datalabels:{display:false},
          tooltip:{
            filter:context=>!context.dataset.isHistoricalYear,
            callbacks:{label:context=>`${context.dataset.label}: ${stationClimateDaysFormat(context.parsed.y,context.dataset.label==="Mittel 1991–2020"?1:0)} Tage`}
          },
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
        },
        scales:{
          x:{ticks:{maxTicksLimit:14,maxRotation:0}},
          y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Akkumulierte Anzahl"}}
        }
      }
    });

    const historicalByYear=new Map(historical.map(item=>[Number(item.year),item]));
    const historyStart=Number(station.start_year);
    const historyEnd=Number(station.end_year);
    const barRows=[];
    if(Number.isFinite(historyStart) && Number.isFinite(historyEnd) && historyEnd>=historyStart){
      for(let year=historyStart;year<=historyEnd;year++){
        const item=historicalByYear.get(year);
        barRows.push(item
          ?{year:String(year),count:item.count,validDays:item.validDays,current:false,noData:false}
          :{year:String(year),count:null,validDays:0,current:false,noData:true});
      }
    }else{
      historical.forEach(item=>barRows.push({year:String(item.year),count:item.count,validDays:item.validDays,current:false,noData:false}));
    }
    if(currentPeriod.elapsedDays>0){
      const currentHasData=currentPeriod.validDays>0;
      barRows.push({
        year:currentLabel,
        count:currentHasData?currentPeriod.count:null,
        validDays:currentPeriod.validDays,
        current:true,
        noData:!currentHasData
      });
    }
    const realCounts=barRows.filter(item=>!item.noData && Number.isFinite(Number(item.count))).map(item=>Number(item.count));
    const highestRealBar=realCounts.length?Math.max(...realCounts):0;
    const noDataHeight=highestRealBar>0?highestRealBar*0.5:1;
    const hasNoDataBars=barRows.some(item=>item.noData);

    if(stationClimateDaysBarChart) stationClimateDaysBarChart.destroy();
    stationClimateDaysBarChart=new Chart(document.getElementById("stationClimateDaysBarChart"),{
      type:"bar",
      data:{
        labels:barRows.map(item=>item.year),
        datasets:[
          {
            label:metric.label,
            data:barRows.map(item=>item.noData?null:item.count),
            backgroundColor:barRows.map(item=>item.current?(metric.color||"#c43d2f"):stationClimateDaysHexToRgba(metric.color,.58)),
            borderColor:barRows.map(item=>item.current?"#111":stationClimateDaysHexToRgba(metric.color,.85)),
            borderWidth:barRows.map(item=>item.current?2:0),
            grouped:false
          },
          {
            label:"Keine Daten",
            data:barRows.map(item=>item.noData?noDataHeight:null),
            backgroundColor:"rgba(145,145,145,.34)",
            borderColor:"#707070",
            borderWidth:2,
            borderDash:[6,4],
            borderSkipped:false,
            grouped:false,
            isNoDataDataset:true
          }
        ]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:`${metric.label} je ${period.label} – ${station.name}`},
          subtitle:{display:hasNoDataBars,text:"Grau gestrichelt: keine Daten vorhanden · Platzhalterhöhe = 50 % des höchsten Messwerts",color:"#666",font:{size:12},padding:{bottom:8}},
          legend:{labels:{filter:item=>item.text!=="Keine Daten"}},
          datalabels:{display:false},
          tooltip:{
            filter:context=>{
              const row=barRows[context.dataIndex];
              return context.dataset.isNoDataDataset?Boolean(row?.noData):!row?.noData;
            },
            callbacks:{
              label:context=>{
                const row=barRows[context.dataIndex];
                if(row?.noData) return "Keine Daten vorhanden";
                return `${metric.label}: ${row.count} ${row.count===1?"Tag":"Tage"}`;
              },
              afterLabel:context=>{
                const row=barRows[context.dataIndex];
                if(row?.noData) return "";
                return row.current?"Aktueller, gegebenenfalls noch unvollständiger Zeitraum":`${row.validDays} gültige Tageswerte`;
              }
            }
          },
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
        },
        scales:{
          x:{ticks:{maxTicksLimit:20,maxRotation:60,minRotation:0}},
          y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Anzahl der Kenntage"}}
        }
      }
    });

    document.getElementById("stationClimateDaysTopTitle").textContent=`Top 10 ${metric.label} – ${period.label}`;
    const tbody=document.querySelector("#stationClimateDaysTopTable tbody");
    tbody.innerHTML=top10.length?top10.map((item,index)=>{
      const expected=Number(period.expected_days||365);
      const coverage=expected>0?item.validDays/expected*100:100;
      return `<tr><td>${index+1}</td><td>${item.year}</td><td><strong>${item.count}</strong></td><td>${stationClimateDaysFormat(coverage,1)} %</td></tr>`;
    }).join(""):'<tr><td colspan="4">Keine ausreichend vollständigen historischen Zeiträume vorhanden.</td></tr>';
  }catch(error){
    document.getElementById("stationClimateDaysSummary").textContent=`Stations-Kenntage konnten nicht geladen werden: ${error.message}`;
  }
}


function stationClimateRecordRows(){
  if(!stationClimateDaysIndex) return [];
  const metrics=new Map((stationClimateDaysIndex.climate_days||[]).map(item=>[item.id,item]));
  const rows=[];
  (stationClimateDaysIndex.stations||[]).forEach(station=>{
    Object.entries(station.annual_records||{}).forEach(([metricId,record])=>{
      const metric=metrics.get(metricId);
      if(!metric || !record) return;
      const years=(record.years||[]).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);
      if(!years.length || !Number.isFinite(Number(record.count))) return;
      rows.push({
        stationId:station.id,
        stationName:station.name,
        state:station.state||"Bundesland unbekannt",
        startYear:Number(station.start_year),
        endYear:Number(station.end_year),
        metricId,
        metricLabel:metric.label,
        definition:metric.definition,
        recordCount:Number(record.count),
        recordYears:years,
        currentCount:Number(record.current_count||0),
        currentValidDays:Number(record.current_valid_days||0),
        status:record.status||"historical"
      });
    });
  });
  return rows;
}

function initializeStationClimateRecordOverview(){
  const metricSelect=document.getElementById("stationClimateRecordMetricSelect");
  if(!metricSelect || !stationClimateDaysIndex) return;

  metricSelect.innerHTML='<option value="all">Alle Kenntage</option>';
  (stationClimateDaysIndex.climate_days||[]).forEach(metric=>{
    const option=document.createElement("option");
    option.value=metric.id;
    option.textContent=`${metric.label} · ${metric.definition}`;
    metricSelect.appendChild(option);
  });

  const stateSelect=document.getElementById("stationClimateRecordStateSelect");
  stateSelect.innerHTML='<option value="all">Alle Bundesländer</option>';
  (stationClimateDaysIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });

  const yearSelect=document.getElementById("stationClimateRecordYearSelect");
  const years=[...new Set(stationClimateRecordRows().flatMap(row=>row.recordYears))].sort((a,b)=>b-a);
  yearSelect.innerHTML='<option value="all">Alle Rekordjahre</option>';
  years.forEach(year=>{
    const option=document.createElement("option");
    option.value=String(year);
    option.textContent=String(year);
    yearSelect.appendChild(option);
  });

  const currentYear=String(stationClimateDaysIndex.current_year);
  const currentOption=[...yearSelect.options].find(option=>option.value===currentYear);
  if(currentOption) currentOption.textContent=`${currentYear} · aktuelle Rekorde`;

  ["stationClimateRecordMetricSelect","stationClimateRecordYearSelect",
   "stationClimateRecordStateSelect","stationClimateRecordStatusSelect"]
    .forEach(id=>document.getElementById(id).addEventListener("change",renderStationClimateRecordOverview));
  document.getElementById("stationClimateRecordSearch")
    .addEventListener("input",renderStationClimateRecordOverview);

  document.getElementById("stationClimateRecordNewTitle").textContent=`Neue Rekorde ${currentYear}`;
  document.getElementById("stationClimateRecordTieTitle").textContent=`Eingestellt ${currentYear}`;
  document.getElementById("stationClimateRecordCurrentHeader").textContent=`Aktuell ${currentYear}`;

  renderStationClimateRecordOverview();
}

function renderStationClimateRecordOverview(){
  if(!stationClimateDaysIndex) return;
  const target=document.querySelector("#stationClimateRecordTable tbody");
  if(!target) return;

  const metric=document.getElementById("stationClimateRecordMetricSelect").value;
  const year=document.getElementById("stationClimateRecordYearSelect").value;
  const state=document.getElementById("stationClimateRecordStateSelect").value;
  const status=document.getElementById("stationClimateRecordStatusSelect").value;
  const search=document.getElementById("stationClimateRecordSearch").value.trim().toLocaleLowerCase("de-DE");
  const currentYear=Number(stationClimateDaysIndex.current_year);

  const rows=stationClimateRecordRows().filter(row=>{
    if(metric!=="all" && row.metricId!==metric) return false;
    if(year!=="all" && !row.recordYears.includes(Number(year))) return false;
    if(state!=="all" && row.state!==state) return false;
    if(status!=="all" && row.status!==status) return false;
    if(search && !`${row.stationName} ${row.stationId}`.toLocaleLowerCase("de-DE").includes(search)) return false;
    return true;
  });

  const statusRank={new_current:0,tied_current:1,historical:2};
  rows.sort((a,b)=>
    (statusRank[a.status]??9)-(statusRank[b.status]??9) ||
    b.recordCount-a.recordCount ||
    a.state.localeCompare(b.state,"de") ||
    a.stationName.localeCompare(b.stationName,"de")
  );

  const stationCount=new Set(rows.map(row=>row.stationId)).size;
  const newCount=rows.filter(row=>row.status==="new_current").length;
  const tiedCount=rows.filter(row=>row.status==="tied_current").length;

  document.getElementById("stationClimateRecordHits").textContent=rows.length.toLocaleString("de-DE");
  document.getElementById("stationClimateRecordStations").textContent=stationCount.toLocaleString("de-DE");
  document.getElementById("stationClimateRecordNew").textContent=newCount.toLocaleString("de-DE");
  document.getElementById("stationClimateRecordTied").textContent=tiedCount.toLocaleString("de-DE");

  const scope=[];
  if(metric!=="all"){
    const m=(stationClimateDaysIndex.climate_days||[]).find(item=>item.id===metric);
    if(m) scope.push(m.label);
  }
  if(year!=="all") scope.push(`Rekordjahr ${year}`);
  if(state!=="all") scope.push(state);

  document.getElementById("stationClimateRecordSummary").textContent=
    `${rows.length.toLocaleString("de-DE")} Rekordeinträge aus ${stationCount.toLocaleString("de-DE")} Stationen`+
    (scope.length?` · ${scope.join(" · ")}`:"")+
    ` · Datenstand ${dailyGermanDate(stationClimateDaysIndex.data_through,true)}.`;

  if(!rows.length){
    target.innerHTML='<tr><td colspan="8">Für die gewählten Filter wurden keine Stationsrekorde gefunden.</td></tr>';
    return;
  }

  target.innerHTML=rows.map(row=>{
    let statusText="Historischer Rekord";
    let badgeClass="checked";
    if(row.status==="new_current"){
      statusText=`Neuer Rekord ${currentYear}`;
      badgeClass="preliminary";
    }else if(row.status==="tied_current"){
      statusText=`Rekord ${currentYear} eingestellt`;
      badgeClass="preliminary";
    }

    return `<tr>
      <td><strong>${row.stationName}</strong><br><span class="note">${row.stationId}</span></td>
      <td>${row.state}</td>
      <td><strong>${row.metricLabel}</strong><br><span class="note">${row.definition}</span></td>
      <td class="record-value">${row.recordCount.toLocaleString("de-DE")} ${row.recordCount===1?"Tag":"Tage"}</td>
      <td>${row.recordYears.join(", ")}</td>
      <td>${row.currentCount.toLocaleString("de-DE")} ${row.currentCount===1?"Tag":"Tage"}<br><span class="note">${row.currentValidDays.toLocaleString("de-DE")} gültige Tage</span></td>
      <td><span class="record-badge ${badgeClass}">${statusText}</span></td>
      <td>${row.startYear}–${row.endYear}</td>
    </tr>`;
  }).join("");
}

function resetStationClimateDaysZoom(){
  if(stationClimateDaysCumulativeChart) stationClimateDaysCumulativeChart.resetZoom();
  if(stationClimateDaysBarChart) stationClimateDaysBarChart.resetZoom();
  if(stationClimateDaysTemperatureFrequencyChart) stationClimateDaysTemperatureFrequencyChart.resetZoom();
  if(stationClimateDaysSnowFrequencyChart) stationClimateDaysSnowFrequencyChart.resetZoom();
}

