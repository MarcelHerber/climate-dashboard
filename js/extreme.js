/* extreme.js – Tageshöchstwerte, Rekorde, Deutschland-Kenntage
   Aus index.html ausgelagert (Schritt 2b). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= TAGESDATEN =================
// DASHBOARD_LAZY_LOADING_V1
let dailyDashboardLoading=null;
let extremeDashboardInitialized=false;

function renderLoadedDailyDashboardForActiveTab(){
  const active=document.querySelector(".tab-content.active")?.id||"";
  if(active==="daily"){
    updateDaily();
    return;
  }
  if(active==="extremes"){
    if(!extremeDashboardInitialized){
      buildExtremeCharts();
      extremeDashboardInitialized=true;
    }else{
      updateExtremeDashboard();
    }
    return;
  }
  if(active==="compare"){
    initializeCompareYearControls();
    updateCompareYears();
  }
}

function ensureDailyDashboardLoaded(){
  if(dailyData.length){
    renderLoadedDailyDashboardForActiveTab();
    return Promise.resolve(dailyData);
  }
  if(dailyDashboardLoading) return dailyDashboardLoading;

  dailyDashboardLoading=dashboardFetch("daily_tmax_1881_2026.json",{cache:"no-store"})
    .then(response=>{
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data=>{
      dailyData=data;
      initializeDailyControls();
      initializeCompareYearControls();
      renderLoadedDailyDashboardForActiveTab();
      return data;
    })
    .catch(error=>{
      showError(`Tagesdaten konnten nicht geladen werden: ${error.message}`);
      throw error;
    })
    .finally(()=>{dailyDashboardLoading=null;});

  return dailyDashboardLoading;
}

function initializeDailyControls(){
  const years=[...new Set(dailyData.map(item=>item.date.slice(0,4)))];
  const select=document.getElementById("yearSelect");
  select.innerHTML="";
  years.forEach(year=>{
    const option=document.createElement("option");
    option.value=year;
    option.textContent=year;
    select.appendChild(option);
  });
  select.value=years[years.length-1];
}

function dailyPeriodFilter(year,range){
  const seasonMap={winter:["12","01","02"],spring:["03","04","05"],summer:["06","07","08"],autumn:["09","10","11"]};
  let filtered=dailyData.filter(item=>item.date.startsWith(year));
  if(range==="winter"){
    const previous=String(Number(year)-1);
    filtered=dailyData.filter(item=>{
      const itemYear=item.date.slice(0,4);
      const month=item.date.slice(5,7);
      return (itemYear===previous && month==="12") || (itemYear===year && ["01","02"].includes(month));
    });
  }else if(range!=="year"){
    if(seasonMap[range]) filtered=filtered.filter(item=>seasonMap[range].includes(item.date.slice(5,7)));
    else filtered=filtered.filter(item=>item.date.slice(5,7)===range);
  }
  return filtered;
}

const DAILY_RANGE_LABELS={
  year:"Gesamtjahr",
  winter:"Winter",
  spring:"Frühling",
  summer:"Sommer",
  autumn:"Herbst",
  "01":"Januar",
  "02":"Februar",
  "03":"März",
  "04":"April",
  "05":"Mai",
  "06":"Juni",
  "07":"Juli",
  "08":"August",
  "09":"September",
  "10":"Oktober",
  "11":"November",
  "12":"Dezember"
};

function dailyRangeLabel(range){
  return DAILY_RANGE_LABELS[range]||range;
}

function dailyCalendarKey(dateString){
  return String(dateString||"").slice(5,10);
}

function dailyGermanDate(dateString,withYear=true){
  if(!dateString) return "–";
  const date=new Date(`${dateString}T00:00:00`);
  if(Number.isNaN(date.getTime())) return dateString;
  return date.toLocaleDateString("de-DE",withYear
    ?{day:"2-digit",month:"long",year:"numeric"}
    :{day:"2-digit",month:"long"}
  );
}

function dailyNumber(value){
  if(value===null || value===undefined || value==="") return null;
  const number=Number(value);
  return Number.isFinite(number)?number:null;
}

function dailyAverage(values){
  const valid=values.filter(Number.isFinite);
  return valid.length?valid.reduce((sum,value)=>sum+value,0)/valid.length:null;
}

function dailySigned(value,digits=1){
  if(!Number.isFinite(value)) return "–";
  const sign=value>0?"+":"";
  return `${sign}${value.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits})} °C`;
}

function dailyHistoricalRecordValues(filtered,excludedYear){
  const recordByDay=new Map();
  dailyData.forEach(item=>{
    if(excludedYear && item.date.slice(0,4)===String(excludedYear)) return;
    const value=dailyNumber(item.tmax);
    if(!Number.isFinite(value)) return;
    const key=dailyCalendarKey(item.date);
    const previous=recordByDay.get(key);
    if(previous===undefined || value>previous) recordByDay.set(key,value);
  });
  return filtered.map(item=>recordByDay.get(dailyCalendarKey(item.date))??null);
}

function dailyHistoricalRank(year,range,filtered){
  const selectedKeys=[...new Set(filtered
    .filter(item=>Number.isFinite(dailyNumber(item.tmax)))
    .map(item=>dailyCalendarKey(item.date)))];
  if(!selectedKeys.length) return null;
  const selectedKeySet=new Set(selectedKeys);
  const minimumCount=Math.max(1,Math.ceil(selectedKeys.length*.95));
  const years=[...new Set(dailyData.map(item=>item.date.slice(0,4)))];
  const rows=[];

  years.forEach(itemYear=>{
    const values=dailyPeriodFilter(itemYear,range)
      .filter(item=>selectedKeySet.has(dailyCalendarKey(item.date)))
      .map(item=>dailyNumber(item.tmax))
      .filter(Number.isFinite);
    if(values.length<minimumCount) return;
    rows.push({year:itemYear,mean:dailyAverage(values),count:values.length});
  });

  rows.sort((a,b)=>b.mean-a.mean || Number(b.year)-Number(a.year));
  const index=rows.findIndex(item=>item.year===String(year));
  if(index<0) return null;
  return {rank:index+1,total:rows.length,mean:rows[index].mean,count:rows[index].count};
}

function updateDaily(){
  if(!dailyData.length) return;
  const year=document.getElementById("yearSelect").value;
  const range=document.getElementById("rangeSelect").value;
  const periodLabel=dailyRangeLabel(range);
  const filtered=dailyPeriodFilter(year,range);
  const labels=filtered.map(item=>item.date);
  const values=filtered.map(item=>dailyNumber(item.tmax));
  const climate=filtered.map(item=>dailyNumber(item.climate_mean));
  const deviation=filtered.map((item,index)=>
    Number.isFinite(values[index])&&Number.isFinite(climate[index])?values[index]-climate[index]:null
  );
  const historicalRecord=dailyHistoricalRecordValues(filtered,year);

  const validItems=filtered.filter(item=>Number.isFinite(dailyNumber(item.tmax)));
  const maxItem=validItems.length
    ?validItems.reduce((best,item)=>dailyNumber(item.tmax)>dailyNumber(best.tmax)?item:best)
    :null;
  const validDeviation=deviation.filter(Number.isFinite);
  const meanDeviation=dailyAverage(validDeviation);
  const aboveClimate=validDeviation.filter(value=>value>0).length;
  const belowClimate=validDeviation.filter(value=>value<0).length;
  const rank=dailyHistoricalRank(year,range,filtered);

  document.getElementById("dailyMaxStat").textContent=maxItem
    ?`${dailyNumber(maxItem.tmax).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`
    :"–";
  document.getElementById("dailyMaxDetail").textContent=maxItem
    ?`${periodLabel} ${year}`
    :"keine gültigen Tageswerte";
  document.getElementById("dailyMaxDateStat").textContent=maxItem
    ?dailyGermanDate(maxItem.date,false)
    :"–";
  document.getElementById("dailyMeanDeviationStat").textContent=dailySigned(meanDeviation,1);
  document.getElementById("dailyRankStat").textContent=rank
    ?`${rank.rank}. von ${rank.total}`
    :"–";
  document.getElementById("dailyRankDetail").textContent=rank
    ?`Vergleich über ${rank.count} Kalendertage`
    :"zu wenige vergleichbare Jahre";

  const meanTmax=dailyAverage(values);
  const strongestPositive=validDeviation.length?Math.max(...validDeviation):null;
  const strongestNegative=validDeviation.length?Math.min(...validDeviation):null;
  document.getElementById("dailySummary").innerHTML=
    `<strong>${periodLabel} ${year}:</strong> ${validItems.length} ausgewertete Tageswerte`+
    `${Number.isFinite(meanTmax)?`, mittleres Tagesmaximum ${meanTmax.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:""}. `+
    `${aboveClimate} Tage lagen über und ${belowClimate} Tage unter dem kalendarischen Mittel 1991–2020. `+
    `${Number.isFinite(strongestPositive)?`Größte positive Abweichung ${dailySigned(strongestPositive,1)}`:""}`+
    `${Number.isFinite(strongestNegative)?`, größte negative Abweichung ${dailySigned(strongestNegative,1)}`:""}.`;

  const firstYear=[...new Set(dailyData.map(item=>item.date.slice(0,4)))].sort()[0];
  const latestDate=dailyData.reduce((latest,item)=>item.date>latest?item.date:latest,"");
  document.getElementById("dailyMethodNote").innerHTML=
    `<strong>Methodik:</strong> Dargestellt ist je Kalendertag der höchste verfügbare Tageshöchstwert aller ausgewerteten DWD-Stationen; `+
    `die Reihe ist kein flächengewichtetes Deutschlandmittel. Das Klimamittel bezieht sich auf 1991–2020. `+
    `Die historische Tagesrekordlinie zeigt das höchste Tagesmaximum des jeweiligen Kalendertags seit ${firstYear}, wobei das ausgewählte Jahr ${year} immer ausgeschlossen wird. `+
    `Aktuelle Werte können vorläufig sein. <strong>Datenstand:</strong> ${dailyGermanDate(latestDate,true)}.`;

  const mainTitle=`Tageshöchsttemperatur in Deutschland – ${periodLabel} ${year}`;
  const deviationTitle=`Abweichung vom Tagesmittel 1991–2020 – ${periodLabel} ${year}`;
  const comparisonTitle=`${year} im Vergleich mit allen Jahren seit ${firstYear} – ${periodLabel}`;

  if(dailyChart) dailyChart.destroy();
  dailyChart=new Chart(document.getElementById("dailyChart"),{
    type:"line",
    data:{labels,datasets:[
      {
        label:`Tageswert ${year}`,
        data:values,
        borderColor:"#d7191c",
        backgroundColor:"rgba(215,25,28,.08)",
        borderWidth:2.2,
        pointRadius:0,
        tension:0,
        spanGaps:false
      },
      {
        label:"Mittel 1991–2020",
        data:climate,
        borderColor:"#111",
        borderDash:[7,5],
        borderWidth:1.8,
        pointRadius:0,
        tension:0
      },
      {
        label:`Bisheriger Tagesrekord ohne ${year}`,
        data:historicalRecord,
        borderColor:"#7f0000",
        borderDash:[2,4],
        borderWidth:1.5,
        pointRadius:0,
        tension:0
      }
    ]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        title:{display:true,text:mainTitle,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{
          display:true,
          text:`Höchster an einer DWD-Station gemessener Tageswert; gepunktet: bisheriger Kalendertagsrekord ohne ${year}`,
          color:"#666",
          font:{size:12},
          padding:{bottom:12}
        },
        datalabels:{display:false},
        tooltip:{callbacks:{
          title:items=>items.length?dailyGermanDate(labels[items[0].dataIndex],true):"",
          label:context=>`${context.dataset.label}: ${Number(context.parsed.y).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`
        }}
      },
      scales:{
        x:{ticks:{maxTicksLimit:14,maxRotation:0}},
        y:{title:{display:true,text:"Tageshöchsttemperatur (°C)"}}
      }
    }
  });

  if(dailyDeviationChart) dailyDeviationChart.destroy();
  dailyDeviationChart=new Chart(document.getElementById("dailyDeviationChart"),{
    type:"line",
    data:{labels,datasets:[{
      label:"Abweichung (°C)",
      data:deviation,
      fill:"origin",
      pointRadius:0,
      borderWidth:1.8,
      tension:0,
      segment:{
        borderColor:context=>(context.p0.parsed.y+context.p1.parsed.y)/2>=0?"#d7191c":"#2166ac",
        backgroundColor:context=>(context.p0.parsed.y+context.p1.parsed.y)/2>=0?"rgba(215,25,28,.25)":"rgba(33,102,172,.24)"
      }
    }]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        title:{display:true,text:deviationTitle,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{
          display:true,
          text:"Rot: über dem kalendarischen Mittel · Blau: unter dem kalendarischen Mittel",
          color:"#666",
          font:{size:12},
          padding:{bottom:12}
        },
        datalabels:{display:false},
        tooltip:{callbacks:{
          title:items=>items.length?dailyGermanDate(labels[items[0].dataIndex],true):"",
          label:context=>`Abweichung: ${dailySigned(context.parsed.y,1)}`
        }}
      },
      scales:{
        x:{ticks:{maxTicksLimit:14,maxRotation:0}},
        y:{
          title:{display:true,text:"Abweichung (°C)"},
          grid:{color:context=>context.tick.value===0?"rgba(0,0,0,.65)":"rgba(0,0,0,.09)",lineWidth:context=>context.tick.value===0?1.4:1}
        }
      }
    }
  });

  const allYears=[...new Set(dailyData.map(item=>item.date.slice(0,4)))];
  const datasets=allYears.map(itemYear=>{
    const data=dailyPeriodFilter(itemYear,range);
    return {
      label:itemYear,
      data:data.map(item=>dailyNumber(item.tmax)),
      borderColor:itemYear===year?"#d7191c":"rgba(46,92,150,.07)",
      borderWidth:itemYear===year?2.5:1,
      pointRadius:0,
      tension:0
    };
  });
  datasets.push({
    label:"Mittel 1991–2020",
    data:climate,
    borderColor:"#111",
    borderDash:[7,5],
    borderWidth:2.4,
    pointRadius:0,
    tension:0
  });
  datasets.push({
    label:`Bisheriger Tagesrekord ohne ${year}`,
    data:historicalRecord,
    borderColor:"#7f0000",
    borderDash:[2,4],
    borderWidth:1.5,
    pointRadius:0,
    tension:0
  });

  if(dailyAllYearsChart) dailyAllYearsChart.destroy();
  dailyAllYearsChart=new Chart(document.getElementById("dailyAllYearsChart"),{
    type:"line",
    data:{labels,datasets},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        title:{display:true,text:comparisonTitle,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{
          display:true,
          text:`Alle verfügbaren Jahre in Grau-Blau; ${year} rot hervorgehoben · gepunktet: bisheriger Kalendertagsrekord ohne ${year}`,
          color:"#666",
          font:{size:12},
          padding:{bottom:12}
        },
        legend:{display:false},
        datalabels:{display:false},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}}
      },
      scales:{
        x:{ticks:{maxTicksLimit:14,maxRotation:0}},
        y:{title:{display:true,text:"Tageshöchsttemperatur (°C)"}}
      }
    }
  });
}
function resetAllYearsZoom(){if(dailyAllYearsChart) dailyAllYearsChart.resetZoom();}
document.getElementById("yearSelect").addEventListener("change",updateDaily);
document.getElementById("rangeSelect").addEventListener("change",updateDaily);

// ================= DEUTSCHLAND-KENNTAGE =================
const EXTREME_METRICS={
  summer:{id:"summer",label:"Sommertage",threshold:25,color:"#f6a623",dark:"#a65d00"},
  hot:{id:"hot",label:"Hitzetage",threshold:30,color:"#ef5b2a",dark:"#a82010"},
  veryHot:{id:"veryHot",label:"Wüstentage",threshold:35,color:"#c62828",dark:"#750000"},
  extremeHot:{id:"extremeHot",label:"Extrem heiße Tage",threshold:40,color:"#6d0012",dark:"#330008"}
};

function extremeDateKeys(range){
  const ranges={
    year:["2001-01-01","2001-12-31"],
    winter:["2000-12-01","2001-02-28"],
    spring:["2001-03-01","2001-05-31"],
    summer:["2001-06-01","2001-08-31"],
    autumn:["2001-09-01","2001-11-30"]
  };
  let start,end;
  if(ranges[range]) [start,end]=ranges[range];
  else{
    const month=String(range).padStart(2,"0");
    const lastDay=new Date(Date.UTC(2001,Number(month),0)).getUTCDate();
    start=`2001-${month}-01`;
    end=`2001-${month}-${String(lastDay).padStart(2,"0")}`;
  }
  const keys=[];
  for(let cursor=new Date(`${start}T00:00:00Z`),stop=new Date(`${end}T00:00:00Z`);cursor<=stop;cursor.setUTCDate(cursor.getUTCDate()+1)){
    keys.push(`${String(cursor.getUTCMonth()+1).padStart(2,"0")}-${String(cursor.getUTCDate()).padStart(2,"0")}`);
  }
  return keys;
}

function extremeKeyLabel(key){
  const [month,day]=key.split("-");
  return `${day}.${month}.`;
}

function extremeMetric(){
  return EXTREME_METRICS[document.getElementById("extremeMetricSelect")?.value]||EXTREME_METRICS.hot;
}

function extremePeriod(){
  return document.getElementById("extremePeriodSelect")?.value||"year";
}

function extremeYearData(year,metric,range,keys=extremeDateKeys(range)){
  const values=dailyPeriodFilter(String(year),range)
    .filter(item=>dailyCalendarKey(item.date)!=="02-29")
    .sort((a,b)=>a.date.localeCompare(b.date));
  const keySet=new Set(keys);
  const scopedValues=values.filter(item=>keySet.has(dailyCalendarKey(item.date)));
  const byKey=new Map(values.map(item=>[dailyCalendarKey(item.date),item]));
  const valid=keys.map(key=>byKey.get(key)).filter(item=>Number.isFinite(dailyNumber(item?.tmax)));
  const events=scopedValues.filter(item=>Number.isFinite(dailyNumber(item.tmax))&&dailyNumber(item.tmax)>=metric.threshold);
  return {
    year:String(year),
    count:events.length,
    validDays:valid.length,
    expectedDays:keys.length,
    completeness:keys.length?valid.length/keys.length:0,
    first:events.length?events[0].date:null,
    last:events.length?events[events.length-1].date:null,
    maxTmax:valid.length?Math.max(...valid.map(item=>dailyNumber(item.tmax))):null,
    byKey
  };
}

function extremeCumulative(yearData,metric,keys,cutoffIndex=keys.length-1){
  let running=0;
  return keys.map((key,index)=>{
    if(index>cutoffIndex) return null;
    const item=yearData.byKey.get(key);
    const value=dailyNumber(item?.tmax);
    if(Number.isFinite(value)&&value>=metric.threshold) running++;
    return running;
  });
}

function extremeMovingAverage(rows,windowSize=30){
  return rows.map((row,index)=>{
    if(index<windowSize-1) return null;
    const values=rows.slice(index-windowSize+1,index+1).map(item=>item.count).filter(Number.isFinite);
    return values.length===windowSize?dailyAverage(values):null;
  });
}

function extremeMonthCounts(year,metric){
  const counts=Array(12).fill(0);
  dailyData.forEach(item=>{
    if(item.date.slice(0,4)!==String(year)) return;
    const value=dailyNumber(item.tmax);
    if(Number.isFinite(value)&&value>=metric.threshold) counts[Number(item.date.slice(5,7))-1]++;
  });
  return counts;
}

function extremeHeatColor(value,maxValue){
  if(!Number.isFinite(value)||value<=0) return "rgba(247,248,249,1)";
  const ratio=Math.min(1,value/Math.max(1,maxValue));
  const light=94-ratio*63;
  return `hsl(${30-ratio*28} 88% ${light}%)`;
}

function buildExtremeCharts(){
  const periodSelect=document.getElementById("extremePeriodSelect");
  if(periodSelect&&!periodSelect.dataset.extremeInitialized){
    populatePeriodSelect(periodSelect,"year");
    periodSelect.dataset.extremeInitialized="true";
  }
  updateExtremeDashboard();
}

function updateExtremeDashboard(){
  if(!dailyData.length) return;
  const metric=extremeMetric();
  const range=extremePeriod();
  const periodLabel=dailyRangeLabel(range);
  const years=[...new Set(dailyData.map(item=>item.date.slice(0,4)))].sort();
  const currentYear=years[years.length-1];
  const keys=extremeDateKeys(range);
  const current=extremeYearData(currentYear,metric,range,keys);
  const availableIndices=keys.map((key,index)=>Number.isFinite(dailyNumber(current.byKey.get(key)?.tmax))?index:-1).filter(index=>index>=0);
  const cutoffIndex=availableIndices.length?Math.max(...availableIndices):-1;
  const comparableKeys=cutoffIndex>=0?keys.slice(0,cutoffIndex+1):[];
  const currentComparable=extremeYearData(currentYear,metric,range,comparableKeys);

  const comparableRows=years.map(year=>extremeYearData(year,metric,range,comparableKeys))
    .filter(row=>row.year===currentYear || (comparableKeys.length&&row.completeness>=.95));
  const ranked=[...comparableRows].sort((a,b)=>b.count-a.count||Number(b.year)-Number(a.year));
  const currentRank=ranked.findIndex(row=>row.year===currentYear);
  const climateComparable=comparableRows.filter(row=>Number(row.year)>=1991&&Number(row.year)<=2020);
  const climateComparableMean=dailyAverage(climateComparable.map(row=>row.count));
  const comparableRecord=ranked.length?ranked[0]:null;

  document.getElementById("extremeCurrentHeading").textContent=`${metric.label} ${currentYear}`;
  document.getElementById("extremeCurrentStat").textContent=cutoffIndex>=0?String(currentComparable.count):"–";
  document.getElementById("extremeCurrentDetail").textContent=cutoffIndex>=0
    ?`${periodLabel}, Daten bis ${dailyGermanDate([...current.byKey.values()].sort((a,b)=>a.date.localeCompare(b.date)).at(-1)?.date,false)}`
    :`${periodLabel} noch ohne Daten`;
  document.getElementById("extremeRankStat").textContent=currentRank>=0?`${currentRank+1}. von ${ranked.length}`:"–";
  document.getElementById("extremeRankDetail").textContent=comparableKeys.length?`gleiche ${comparableKeys.length} Kalendertage`:"Zeitraum noch nicht begonnen";
  document.getElementById("extremeMeanStat").textContent=Number.isFinite(climateComparableMean)
    ?climateComparableMean.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})
    :"–";
  document.getElementById("extremeMeanDetail").textContent="1991–2020, bis zum gleichen Kalendertag";
  document.getElementById("extremeRecordStat").textContent=comparableRecord?String(comparableRecord.count):"–";
  document.getElementById("extremeRecordDetail").textContent=comparableRecord?`${comparableRecord.year}, vergleichbarer Zeitraum`:"kein Vergleich möglich";

  const difference=Number.isFinite(climateComparableMean)?currentComparable.count-climateComparableMean:null;
  const incomplete=cutoffIndex>=0&&cutoffIndex<keys.length-1;
  document.getElementById("extremeSummary").innerHTML=
    `<strong>${metric.label} · ${periodLabel} ${currentYear}:</strong> ${cutoffIndex>=0?currentComparable.count:"keine"} Deutschlandtage mit Tmax ≥ ${metric.threshold.toFixed(0)} °C. `+
    `${Number.isFinite(difference)?`Das sind ${difference>=0?"+":""}${difference.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} Tage gegenüber dem Mittel 1991–2020 bis zum gleichen Kalendertag. `:""}`+
    `${incomplete?"Der aktuelle Zeitraum ist noch nicht abgeschlossen und wird deshalb nur mit denselben Kalendertagen früherer Jahre verglichen.":"Der gewählte Zeitraum ist für das aktuelle Jahr vollständig verfügbar."}`;

  // Akkumulierter Verlauf
  const historicalRows=years.filter(year=>year!==currentYear).map(year=>extremeYearData(year,metric,range,keys))
    .filter(row=>row.completeness>=.98);
  const historicalSeries=historicalRows.map(row=>extremeCumulative(row,metric,keys));
  const climateSeries=historicalRows.filter(row=>Number(row.year)>=1991&&Number(row.year)<=2020)
    .map(row=>extremeCumulative(row,metric,keys));
  const climateMean=keys.map((_,index)=>dailyAverage(climateSeries.map(series=>series[index]).filter(Number.isFinite)));
  const historicalMin=keys.map((_,index)=>{
    const values=historicalSeries.map(series=>series[index]).filter(Number.isFinite);
    return values.length?Math.min(...values):null;
  });
  const historicalMax=keys.map((_,index)=>{
    const values=historicalSeries.map(series=>series[index]).filter(Number.isFinite);
    return values.length?Math.max(...values):null;
  });
  const currentCumulative=extremeCumulative(current,metric,keys,cutoffIndex);
  const cumulativeLabels=keys.map(extremeKeyLabel);

  if(extremeCumulativeChart) extremeCumulativeChart.destroy();
  extremeCumulativeChart=new Chart(document.getElementById("extremeCumulativeChart"),{
    type:"line",
    data:{labels:cumulativeLabels,datasets:[
      {label:"Historisches Maximum",data:historicalMax,borderColor:"rgba(100,100,100,.35)",backgroundColor:"rgba(130,130,130,.18)",borderWidth:1,pointRadius:0,fill:"+1",tension:0},
      {label:"Historisches Minimum",data:historicalMin,borderColor:"rgba(100,100,100,.35)",borderWidth:1,pointRadius:0,fill:false,tension:0},
      {label:`Mittel ${hyrasReferenceDisplay()}`,data:climateMean,borderColor:"#111",borderDash:[7,5],borderWidth:2,pointRadius:0,tension:0},
      {label:String(currentYear),data:currentCumulative,borderColor:metric.color,backgroundColor:metric.color,borderWidth:3,pointRadius:0,tension:0,spanGaps:false}
    ]},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{
        title:{display:true,text:`Akkumulierte ${metric.label} – ${periodLabel} ${currentYear}`,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{display:true,text:"Aktuelles Jahr, Mittel 1991–2020 und historischer Min-Max-Spannbereich",color:"#666",font:{size:12},padding:{bottom:12}},
        datalabels:{display:false},
        tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${Number(context.parsed.y).toLocaleString("de-DE",{maximumFractionDigits:1})} Tage`}}
      },
      scales:{x:{ticks:{maxTicksLimit:14,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:"Akkumulierte Anzahl"},ticks:{precision:0}}}
    }
  });

  // Jahres- und Saisonwerte
  const fullRows=years.map(year=>extremeYearData(year,metric,range,keys))
    .filter(row=>row.year===currentYear || row.completeness>=.98);
  const completedRows=fullRows.filter(row=>row.year!==currentYear || row.completeness>=.98);
  const climateFullMean=dailyAverage(completedRows.filter(row=>Number(row.year)>=1991&&Number(row.year)<=2020).map(row=>row.count));
  const recordCount=completedRows.length?Math.max(...completedRows.map(row=>row.count)):null;
  const moving=extremeMovingAverage(fullRows,30);
  const barColors=fullRows.map(row=>row.year===currentYear?metric.color:(row.count===recordCount?metric.dark:"rgba(223,132,75,.62)"));

  if(yearlyExtremeChart) yearlyExtremeChart.destroy();
  yearlyExtremeChart=new Chart(document.getElementById("yearlyExtremeChart"),{
    type:"bar",
    data:{labels:fullRows.map(row=>row.year),datasets:[
      {type:"bar",label:metric.label,data:fullRows.map(row=>row.count),backgroundColor:barColors,borderColor:barColors,borderWidth:0},
      {type:"line",label:"Mittel 1991–2020",data:fullRows.map(()=>climateFullMean),borderColor:"#111",borderDash:[8,5],borderWidth:2,pointRadius:0,spanGaps:true},
      {type:"line",label:"30-jähriges gleitendes Mittel",data:moving,borderColor:metric.dark,borderDash:[2,5],borderWidth:2.2,pointRadius:0,spanGaps:false}
    ]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        title:{display:true,text:`${metric.label} in Deutschland – ${periodLabel} seit ${fullRows[0]?.year||years[0]}`,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{display:true,text:`Ein Tag zählt, sobald mindestens eine DWD-Station Tmax ≥ ${metric.threshold.toFixed(0)} °C erreicht`,color:"#666",font:{size:12},padding:{bottom:12}},
        datalabels:{display:false},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}},
        tooltip:{callbacks:{afterLabel:context=>{
          const row=fullRows[context.dataIndex];
          return row.year===currentYear&&row.completeness<.98?"aktueller Zeitraum noch unvollständig":`${Math.round(row.completeness*100)} % Datenvollständigkeit`;
        }}}
      },
      scales:{x:{ticks:{maxTicksLimit:18,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:"Anzahl der Deutschlandtage"},ticks:{precision:0}}}
    }
  });

  // Jahr-Monat-Heatmap
  const heatYears=years.filter(year=>dailyData.some(item=>item.date.startsWith(year)&&Number.isFinite(dailyNumber(item.tmax))));
  const monthRows=heatYears.flatMap(year=>extremeMonthCounts(year,metric).map((value,index)=>({x:MONTH_SHORT[index],y:year,v:value})));
  const heatMax=Math.max(1,...monthRows.map(item=>item.v));
  if(heatmapChart) heatmapChart.destroy();
  heatmapChart=new Chart(document.getElementById("heatmapChart"),{
    type:"matrix",
    data:{datasets:[{
      label:metric.label,
      data:monthRows,
      backgroundColor:context=>extremeHeatColor(context.raw?.v,heatMax),
      borderColor:"rgba(255,255,255,.72)",
      borderWidth:.6,
      width:context=>{
        const area=context.chart.chartArea;
        return area?Math.max(3,area.width/12-1):20;
      },
      height:context=>{
        const area=context.chart.chartArea;
        return area?Math.max(3,area.height/heatYears.length-1):5;
      }
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        title:{display:true,text:`Jahr-Monat-Heatmap der ${metric.label}`,font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{display:true,text:`Zahl der Deutschlandtage mit Tmax ≥ ${metric.threshold.toFixed(0)} °C je Monat`,color:"#666",font:{size:12},padding:{bottom:12}},
        legend:{display:false},datalabels:{display:false},
        tooltip:{callbacks:{title:items=>items.length?`${items[0].raw.y} · ${items[0].raw.x}`:"",label:context=>`${context.raw.v} ${metric.label}`}}
      },
      scales:{
        x:{type:"category",labels:MONTH_SHORT,offset:true,grid:{display:false},ticks:{maxRotation:0}},
        y:{type:"category",labels:[...heatYears].reverse(),offset:true,grid:{display:false},ticks:{autoSkip:false,callback:(value,index)=>{
          const year=[...heatYears].reverse()[index];
          return year===currentYear||Number(year)%10===0?year:"";
        }}}
      }
    }
  });

  // Jahreshöchstwerte
  const maxRows=years.map(year=>{
    const items=dailyData.filter(item=>item.date.startsWith(year)).filter(item=>Number.isFinite(dailyNumber(item.tmax)));
    if(!items.length) return {year,value:null,date:null};
    const maxItem=items.reduce((best,item)=>dailyNumber(item.tmax)>dailyNumber(best.tmax)?item:best);
    return {year,value:dailyNumber(maxItem.tmax),date:maxItem.date};
  }).filter(row=>Number.isFinite(row.value));
  const absoluteMax=Math.max(...maxRows.map(row=>row.value));
  if(yearlyMaxChart) yearlyMaxChart.destroy();
  yearlyMaxChart=new Chart(document.getElementById("yearlyMaxChart"),{
    type:"bar",
    data:{labels:maxRows.map(row=>row.year),datasets:[{
      label:"Jahreshöchstwert",
      data:maxRows.map(row=>row.value),
      backgroundColor:maxRows.map(row=>row.year===currentYear?"#f57c00":row.value===absoluteMax?"#7f0000":"rgba(215,25,28,.58)")
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        title:{display:true,text:"Höchste in Deutschland gemessene Temperatur jedes Jahres",font:{size:18,weight:"bold"},padding:{bottom:4}},
        subtitle:{display:true,text:"Höchster verfügbarer Tageshöchstwert einer ausgewerteten DWD-Station",color:"#666",font:{size:12},padding:{bottom:12}},
        datalabels:{display:false},
        tooltip:{callbacks:{afterLabel:context=>`Datum: ${dailyGermanDate(maxRows[context.dataIndex].date,true)}`}},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}}
      },
      scales:{x:{ticks:{maxTicksLimit:18,maxRotation:0}},y:{type:"linear",beginAtZero:false,min:28,ticks:{stepSize:2},title:{display:true,text:"°C"}}}
    }
  });

  // Top-10-Rekordjahre
  const topRows=[...fullRows].filter(row=>row.year!==currentYear||row.validDays>0)
    .sort((a,b)=>b.count-a.count||Number(b.year)-Number(a.year)).slice(0,10);
  document.getElementById("extremeRecordHeading").textContent=`Top 10 Jahre: ${metric.label} · ${periodLabel}`;
  document.getElementById("extremeRecordNote").textContent=`Rangfolge nach der Zahl der Tage mit Tmax ≥ ${metric.threshold.toFixed(0)} °C. Historische Zeiträume benötigen mindestens 98 % Datenvollständigkeit.`;
  document.querySelector("#extremeRecordTable tbody").innerHTML=topRows.map((row,index)=>`<tr>
    <td>${index+1}</td>
    <td>${row.year}</td>
    <td class="record-value">${row.count}</td>
    <td>${row.first?dailyGermanDate(row.first,false):"–"}</td>
    <td>${row.last?dailyGermanDate(row.last,false):"–"}</td>
    <td>${Number.isFinite(row.maxTmax)?`${row.maxTmax.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–"}</td>
    <td><span class="record-badge ${row.year===currentYear&&row.completeness<.98?"preliminary":"checked"}">${row.year===currentYear&&row.completeness<.98?"vorläufig":"vollständig"}</span></td>
  </tr>`).join("")||'<tr><td colspan="7">Keine ausreichend vollständigen Zeiträume vorhanden.</td></tr>';

  const top30=[...dailyData].filter(item=>Number.isFinite(dailyNumber(item.tmax))).sort((a,b)=>dailyNumber(b.tmax)-dailyNumber(a.tmax)).slice(0,30);
  document.querySelector("#topHotDaysTable tbody").innerHTML=top30.map((item,index)=>
    `<tr><td>${index+1}</td><td>${dailyGermanDate(item.date,true)}</td><td class="record-value">${dailyNumber(item.tmax).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C</td></tr>`
  ).join("");

  const latestDate=dailyData.reduce((latest,item)=>item.date>latest?item.date:latest,"");
  document.getElementById("extremeMethodNote").innerHTML=
    `<strong>Definitionen:</strong> Sommertag Tmax ≥ 25 °C · Hitzetag Tmax ≥ 30 °C · Wüstentag Tmax ≥ 35 °C · extrem heißer Tag Tmax ≥ 40 °C. `+
    `Der 29. Februar wird in den jahresübergreifenden Vergleichen ausgelassen. Historische Balken und Spannbereiche verwenden nur Zeiträume mit mindestens 98 % Datenvollständigkeit. `+
    `Aktuelle Werte können vorläufig sein. <strong>Datenstand:</strong> ${dailyGermanDate(latestDate,true)}.`;
}

function resetExtremeYearZoom(){if(yearlyExtremeChart) yearlyExtremeChart.resetZoom();}
function resetYearlyMaxZoom(){if(yearlyMaxChart) yearlyMaxChart.resetZoom();}
document.getElementById("extremeMetricSelect").addEventListener("change",updateExtremeDashboard);
document.getElementById("extremePeriodSelect").addEventListener("change",updateExtremeDashboard);





