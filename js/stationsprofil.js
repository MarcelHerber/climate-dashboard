/* stationsprofil.js – Stationsprofil (Grundgerüst, Kenntage, GTS, Wärme-/Kältesumme, Temperatur, Überblick)
   Aus index.html ausgelagert (Schritt 2c). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= VERSION 12.1: STATIONSPROFIL – GRUNDGERÜST =================
let stationProfileInitialized=false;
let stationProfileProfile=null;
let stationProfileRequestId=0;
let stationProfileSummerAnnualChart=null;
let stationProfileWinterAnnualChart=null;
let stationProfileTemperatureChart=null;
let stationProfileGtsChart=null;
let stationProfileWarmthChart=null;
let stationProfileColdSumChart=null;
let stationProfileClimateTrendChart=null;
const stationProfileClimateCompareCache=new Map();
let stationProfileMap=null;
let stationProfileMapLayer=null;
let stationProfilePrecipIndex=null;
let stationProfileHeatwaveIndex=null;
let stationProfileHeatwaveCurrent=null;

function stationProfileDistanceKm(a,b){
  if(!Number.isFinite(Number(a?.latitude))||!Number.isFinite(Number(a?.longitude))||!Number.isFinite(Number(b?.latitude))||!Number.isFinite(Number(b?.longitude))) return Infinity;
  const rad=value=>Number(value)*Math.PI/180;
  const dLat=rad(Number(b.latitude)-Number(a.latitude));
  const dLon=rad(Number(b.longitude)-Number(a.longitude));
  const lat1=rad(a.latitude),lat2=rad(b.latitude);
  const h=Math.sin(dLat/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLon/2)**2;
  return 6371*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h));
}
function stationProfileFilteredStations(){
  const state=document.getElementById("stationProfileStateSelect")?.value||"Deutschland";
  const search=(document.getElementById("stationProfileSearch")?.value||"").trim().toLocaleLowerCase("de-DE");
  return (stationClimateDaysIndex?.stations||[]).filter(station=>{
    if(state!=="Deutschland"&&station.state!==state) return false;
    return !search||`${station.name} ${station.id}`.toLocaleLowerCase("de-DE").includes(search);
  });
}
function populateStationProfileStations(preferred){
  const select=document.getElementById("stationProfileStationSelect");
  if(!select) return;
  const previous=preferred||select.value;
  const stations=stationProfileFilteredStations();
  select.innerHTML="";
  stations.forEach(station=>{const option=document.createElement("option");option.value=station.id;option.textContent=`${station.name} (${station.id})`;select.appendChild(option);});
  if(stations.some(station=>station.id===previous)) select.value=previous;
  else if(stations.length) select.value=stations[0].id;
}
function initializeStationProfileControls(){
  if(stationProfileInitialized) return;
  stationProfileInitialized=true;
  const state=document.getElementById("stationProfileStateSelect");
  state.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  (stationClimateDaysIndex?.states||[]).forEach(name=>{const option=document.createElement("option");option.value=name;option.textContent=name;state.appendChild(option);});
  state.value="Deutschland";
  state.addEventListener("change",()=>{populateStationProfileStations();updateStationProfileBase();});
  document.getElementById("stationProfileSearch")?.addEventListener("input",()=>{populateStationProfileStations();updateStationProfileBase();});
  document.getElementById("stationProfileStationSelect")?.addEventListener("change",updateStationProfileBase);
  ["stationProfileYearSelect","stationProfileReferenceSelect","stationProfileFromSelect","stationProfileRollingSelect"].forEach(id=>document.getElementById(id)?.addEventListener("change",()=>window.dispatchEvent(new CustomEvent("stationprofilechange"))));
  populateStationProfileStations();
}

function stationObservationMetricMeta(metricId){
  const fallback={
    temperature:{id:"temperature",label:"Temperatur 2 m",unit:"°C"},
    precipitation:{id:"precipitation",label:"Niederschlag",unit:"mm"},
    dewpoint:{id:"dewpoint",label:"Taupunkt",unit:"°C"}
  };
  return (stationObservationsIndex?.parameters||[]).find(item=>item.id===metricId)
    || fallback[metricId]
    || {id:metricId,label:metricId,unit:""};
}

function stationObservationMetricColumn(metricId){
  if(metricId==="temperature") return 1;
  if(metricId==="dewpoint") return 2;
  if(metricId==="precipitation") return 3;
  return -1;
}

function stationObservationDate(value){
  if(!value) return null;
  const normalized=/Z$/.test(value)?value:`${value}Z`;
  const date=new Date(normalized);
  return Number.isNaN(date.getTime())?null:date;
}

function stationObservationDateTimeLabel(value){
  const date=stationObservationDate(value);
  if(!date) return value||"–";
  return date.toLocaleString("de-DE",{
    day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",
    timeZone:"Europe/Berlin"
  });
}

function stationObservationLongDateTime(value){
  const date=stationObservationDate(value);
  if(!date) return value||"–";
  return date.toLocaleString("de-DE",{
    day:"2-digit",month:"2-digit",year:"numeric",
    hour:"2-digit",minute:"2-digit",
    timeZone:"Europe/Berlin"
  });
}

function stationObservationNumber(value,digits=1){
  return Number.isFinite(value)
    ?value.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits})
    :"–";
}

async function ensureStationObservationsLoaded(){
  if(stationObservationsIndex){
    document.getElementById("stationObservationsContent").hidden=false;
    document.getElementById("stationObservationsLoading").hidden=true;
    return;
  }
  if(stationObservationsIndexLoading) return stationObservationsIndexLoading;

  const loading=document.getElementById("stationObservationsLoading");
  loading.hidden=false;
  loading.style.color="";
  loading.textContent="Stations-Messwerte werden geladen …";

  stationObservationsIndexLoading=(async()=>{
    try{
      const response=await dashboardFetch("station_observations_index.json",{cache:"no-store"});
      if(!response.ok) throw new Error(
        response.status===404
          ?"Die Messwert-Dateien wurden noch nicht erzeugt. Bitte zuerst den Workflow „DWD Stations-Messwerte aktualisieren“ starten."
          :`HTTP ${response.status}`
      );
      const data=await response.json();
      if(!data?.ready || !Array.isArray(data.stations)) throw new Error("Ungültiger Messwert-Index.");

      stationObservationsIndex=data;
      initializeStationObservationsControls();
      document.getElementById("stationObservationsContent").hidden=false;
      loading.hidden=true;
      await loadSelectedStationObservations();
    }catch(error){
      loading.hidden=false;
      loading.style.color="#7a1010";
      loading.textContent=`Stations-Messwerte konnten nicht geladen werden: ${error.message}`;
      throw error;
    }finally{
      stationObservationsIndexLoading=null;
    }
  })();

  return stationObservationsIndexLoading;
}

function stationObservationFilteredStations(){
  if(!stationObservationsIndex) return [];
  const state=document.getElementById("stationObservationsStateSelect")?.value||"all";
  const search=(document.getElementById("stationObservationsSearch")?.value||"")
    .trim().toLocaleLowerCase("de-DE");

  return (stationObservationsIndex.stations||[]).filter(station=>{
    if(state!=="all" && station.state!==state) return false;
    if(search){
      const haystack=`${station.name} ${station.id}`.toLocaleLowerCase("de-DE");
      if(!haystack.includes(search)) return false;
    }
    return true;
  });
}

function populateStationObservationStations({keepSelection=true}={}){
  const select=document.getElementById("stationObservationsStationSelect");
  const previous=keepSelection?select.value:"";
  const stations=stationObservationFilteredStations();

  select.innerHTML="";
  stations.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    option.textContent=`${station.name} (${station.id})`;
    select.appendChild(option);
  });

  if(previous && stations.some(station=>station.id===previous)){
    select.value=previous;
  }else{
    const preferred=stations.find(station=>/Frankfurt\/Main/i.test(station.name))
      ||stations.find(station=>/Saarbrücken/i.test(station.name))
      ||stations[0];
    if(preferred) select.value=preferred.id;
  }

  if(!stations.length){
    const option=document.createElement("option");
    option.textContent="Keine Station gefunden";
    option.value="";
    select.appendChild(option);
  }

  return stations;
}

function populateStationObservationParameters(){
  const stationId=document.getElementById("stationObservationsStationSelect").value;
  const station=(stationObservationsIndex?.stations||[]).find(item=>item.id===stationId);
  const select=document.getElementById("stationObservationsParameterSelect");
  const previous=select.value;
  select.innerHTML="";

  const available=station?.available||[];
  (stationObservationsIndex?.parameters||[]).forEach(metric=>{
    if(!available.includes(metric.id)) return;
    const option=document.createElement("option");
    option.value=metric.id;
    option.textContent=metric.label;
    select.appendChild(option);
  });

  if([...select.options].some(option=>option.value===previous)){
    select.value=previous;
  }else if([...select.options].some(option=>option.value==="temperature")){
    select.value="temperature";
  }else if(select.options.length){
    select.selectedIndex=0;
  }
}

function initializeStationObservationsControls(){
  const stateSelect=document.getElementById("stationObservationsStateSelect");
  stateSelect.innerHTML='<option value="all">Alle Bundesländer</option>';
  (stationObservationsIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });

  populateStationObservationStations({keepSelection:false});
  populateStationObservationParameters();

  stateSelect.addEventListener("change",async()=>{
    populateStationObservationStations({keepSelection:false});
    populateStationObservationParameters();
    await loadSelectedStationObservations();
  });

  document.getElementById("stationObservationsSearch").addEventListener("input",async()=>{
    populateStationObservationStations({keepSelection:true});
    populateStationObservationParameters();
    await loadSelectedStationObservations();
  });

  document.getElementById("stationObservationsStationSelect").addEventListener("change",async()=>{
    populateStationObservationParameters();
    await loadSelectedStationObservations();
  });

  document.getElementById("stationObservationsParameterSelect").addEventListener("change",()=>{
    renderStationObservations();
  });

  document.getElementById("stationObservationsPeriodSelect").addEventListener("change",()=>{
    renderStationObservations();
  });

  document.getElementById("stationObservationsSourceNote").textContent=
    stationObservationSourceNoteForMetric("temperature");
}

async function loadSelectedStationObservations(){
  if(!stationObservationsIndex) return;
  const stationId=document.getElementById("stationObservationsStationSelect").value;
  if(!stationId){
    stationObservationsPayload=null;
    renderStationObservations();
    return;
  }

  const station=(stationObservationsIndex.stations||[]).find(item=>item.id===stationId);
  if(!station) return;

  const requestId=++stationObservationsRequestId;
  const summary=document.getElementById("stationObservationsSummary");
  summary.textContent=`${station.name}: Stundenwerte werden geladen …`;

  try{
    const response=await dashboardFetch(station.file,{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload=await response.json();
    if(requestId!==stationObservationsRequestId) return;
    stationObservationsPayload=payload;
    renderStationObservations();
  }catch(error){
    if(requestId!==stationObservationsRequestId) return;
    stationObservationsPayload=null;
    summary.textContent=`${station.name}: Messwerte konnten nicht geladen werden: ${error.message}`;
    if(stationObservationsChart){
      stationObservationsChart.destroy();
      stationObservationsChart=null;
    }
  }
}

function stationObservationRowsForPeriod(metricId,days){
  const payload=stationObservationsPayload;
  if(!payload?.rows?.length) return [];

  const column=stationObservationMetricColumn(metricId);
  if(column<0) return [];

  const valid=payload.rows
    .map(row=>({
      time:row[0],
      date:stationObservationDate(row[0]),
      value:Number.isFinite(Number(row[column]))?Number(row[column]):null
    }))
    .filter(item=>item.date && item.value!==null);

  if(!valid.length) return [];

  const latest=valid[valid.length-1].date;
  const cutoff=new Date(latest.getTime()-days*24*60*60*1000);

  return valid.filter(item=>item.date>=cutoff && item.date<=latest);
}

function setStationObservationStats(metricId,rows){
  const labels=[
    document.getElementById("stationObservationsStat1Label"),
    document.getElementById("stationObservationsStat2Label"),
    document.getElementById("stationObservationsStat3Label"),
    document.getElementById("stationObservationsStat4Label")
  ];
  const values=[
    document.getElementById("stationObservationsStat1"),
    document.getElementById("stationObservationsStat2"),
    document.getElementById("stationObservationsStat3"),
    document.getElementById("stationObservationsStat4")
  ];

  if(!rows.length){
    labels.forEach((label,index)=>label.textContent=["Aktuell","Minimum","Maximum","Mittel"][index]);
    values.forEach(value=>value.textContent="–");
    return;
  }

  const nums=rows.map(row=>row.value);
  const meta=stationObservationMetricMeta(metricId);

  if(metricId==="precipitation"){
    const total=nums.reduce((sum,value)=>sum+value,0);
    const max=Math.max(...nums);
    const wetHours=nums.filter(value=>value>0).length;
    const latest=nums[nums.length-1];

    labels[0].textContent="Summe";
    labels[1].textContent="Stärkste Stunde";
    labels[2].textContent="Niederschlagsstunden";
    labels[3].textContent="Letzte Stunde";

    values[0].textContent=`${stationObservationNumber(total,1)} mm`;
    values[1].textContent=`${stationObservationNumber(max,1)} mm`;
    values[2].textContent=wetHours.toLocaleString("de-DE");
    values[3].textContent=`${stationObservationNumber(latest,1)} mm`;
    return;
  }

  const latest=nums[nums.length-1];
  const min=Math.min(...nums);
  const max=Math.max(...nums);
  const mean=nums.reduce((sum,value)=>sum+value,0)/nums.length;

  labels[0].textContent="Letzter Stundenwert";
  labels[1].textContent="Minimum";
  labels[2].textContent="Maximum";
  labels[3].textContent="Mittel";

  values[0].textContent=`${stationObservationNumber(latest,1)} ${meta.unit}`;
  values[1].textContent=`${stationObservationNumber(min,1)} ${meta.unit}`;
  values[2].textContent=`${stationObservationNumber(max,1)} ${meta.unit}`;
  values[3].textContent=`${stationObservationNumber(mean,1)} ${meta.unit}`;
}


function stationObservationDayKey(value){
  const date=stationObservationDate(value);
  if(!date) return null;
  return date.toLocaleDateString("sv-SE",{timeZone:"Europe/Berlin"});
}

function stationObservationClimateDayCategory(tmin,tmax){
  if(!Number.isFinite(tmin) || !Number.isFinite(tmax)){
    return {id:"normal",label:"Kein Kenntag",color:"#4f6f8f"};
  }
  if(tmax<0){
    return {id:"ice",label:"Eistag (Tmax < 0 °C)",color:"#08519c"};
  }
  if(tmin<0){
    return {id:"frost",label:"Frosttag (Tmin < 0 °C)",color:"#3182bd"};
  }
  if(tmin>=20 && tmax>=30){
    return {id:"tropical_hot",label:"Tropennacht + Hitzetag",color:"#7a0177"};
  }
  if(tmin>=20){
    return {id:"tropical",label:"Tropennacht (Tmin ≥ 20 °C)",color:"#c51b8a"};
  }
  if(tmax>=30){
    return {id:"hot",label:"Hitzetag (Tmax ≥ 30 °C)",color:"#d7301f"};
  }
  if(tmax>=25){
    return {id:"summer",label:"Sommertag (Tmax ≥ 25 °C)",color:"#fc8d59"};
  }
  return {id:"normal",label:"Kein Kenntag",color:"#4f6f8f"};
}

function stationObservationAnalyzeDays(rows){
  const dayMap=new Map();

  rows.forEach((row,index)=>{
    const dayKey=stationObservationDayKey(row.time);
    if(!dayKey || !Number.isFinite(row.value)) return;

    let group=dayMap.get(dayKey);
    if(!group){
      group={
        key:dayKey,
        min:row.value,
        max:row.value,
        minIndex:index,
        maxIndex:index
      };
      dayMap.set(dayKey,group);
    }else{
      if(row.value<group.min){
        group.min=row.value;
        group.minIndex=index;
      }
      if(row.value>group.max){
        group.max=row.value;
        group.maxIndex=index;
      }
    }
  });

  const minIndices=new Set();
  const maxIndices=new Set();
  const dayCategoryByKey=new Map();

  dayMap.forEach(group=>{
    minIndices.add(group.minIndex);
    maxIndices.add(group.maxIndex);
    dayCategoryByKey.set(group.key,stationObservationClimateDayCategory(group.min,group.max));
  });

  return {dayMap,minIndices,maxIndices,dayCategoryByKey};
}

function stationObservationLineColor(metricId){
  if(metricId==="temperature") return "#4f6f8f";
  if(metricId==="dewpoint") return "#2c7fb8";
  return "#666";
}

function stationObservationSourceNoteForMetric(metricId){
  const base=stationObservationsIndex?.source_note || "Quelle: Deutscher Wetterdienst, Climate Data Center (CDC).";
  if(metricId!=="temperature") return base;
  return `${base} Linienfarbe nach Tages-Kenntag: dunkelblau = Eistag, blau = Frosttag, orange = Sommertag, rot = Hitzetag, magenta = Tropennacht, violett = Tropennacht + Hitzetag. Markiert werden jeweils nur Tagesminimum und Tagesmaximum.`;
}

function renderStationObservations(){
  const summary=document.getElementById("stationObservationsSummary");
  if(!stationObservationsPayload){
    summary.textContent="Keine Stationsdaten geladen.";
    setStationObservationStats("temperature",[]);
    return;
  }

  const metricId=document.getElementById("stationObservationsParameterSelect").value;
  const days=Number(document.getElementById("stationObservationsPeriodSelect").value)||7;
  const meta=stationObservationMetricMeta(metricId);
  const rows=stationObservationRowsForPeriod(metricId,days);

  document.getElementById("stationObservationsSourceNote").textContent=
    stationObservationSourceNoteForMetric(metricId);

  setStationObservationStats(metricId,rows);

  const station=(stationObservationsIndex?.stations||[])
    .find(item=>item.id===stationObservationsPayload.station_id);
  const locationParts=[];
  if(station?.state) locationParts.push(station.state);
  if(Number.isFinite(Number(station?.height))) locationParts.push(`${station.height} m`);

  const latest=rows.length?rows[rows.length-1].time:null;
  summary.textContent=
    `${stationObservationsPayload.name} (${stationObservationsPayload.station_id})`+
    (locationParts.length?` · ${locationParts.join(" · ")}`:"")+
    ` · ${meta.label} · letzte ${days} Tage`+
    (latest?` · letzter Wert ${stationObservationLongDateTime(latest)}`:" · keine gültigen Werte");

  if(stationObservationsChart){
    stationObservationsChart.destroy();
    stationObservationsChart=null;
  }

  const canvas=document.getElementById("stationObservationsChart");
  if(!rows.length){
    return;
  }

  const labels=rows.map(row=>stationObservationDateTimeLabel(row.time));

  if(metricId==="precipitation"){
    let cumulative=0;
    const cumulativeValues=rows.map(row=>{
      cumulative+=row.value;
      return Number(cumulative.toFixed(2));
    });

    stationObservationsChart=new Chart(canvas,{
      type:"bar",
      data:{
        labels,
        datasets:[
          {
            type:"bar",
            label:"Stundenniederschlag",
            data:rows.map(row=>row.value),
            yAxisID:"y"
          },
          {
            type:"line",
            label:"Kumuliert",
            data:cumulativeValues,
            yAxisID:"yCum",
            borderWidth:2,
            pointRadius:0,
            tension:0.12
          }
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        plugins:{
          legend:{display:true},
          tooltip:{
            callbacks:{
              label(context){
                return `${context.dataset.label}: ${stationObservationNumber(Number(context.parsed.y),1)} mm`;
              }
            }
          }
        },
        scales:{
          x:{
            ticks:{autoSkip:true,maxTicksLimit:days<=3?18:days<=7?14:12,maxRotation:0}
          },
          y:{
            beginAtZero:true,
            position:"left",
            title:{display:true,text:"Stundenniederschlag [mm]"}
          },
          yCum:{
            beginAtZero:true,
            position:"right",
            grid:{drawOnChartArea:false},
            title:{display:true,text:"Kumuliert [mm]"}
          }
        }
      }
    });
    return;
  }

  const dailyInfo=stationObservationAnalyzeDays(rows);
  const dayLabels=rows.map(row=>stationObservationDayKey(row.time));
  const baseLineColor=stationObservationLineColor(metricId);

  stationObservationsChart=new Chart(canvas,{
    type:"line",
    data:{
      labels,
      datasets:[
        {
          label:meta.label,
          data:rows.map(row=>row.value),
          borderWidth:2,
          pointRadius:0,
          pointHoverRadius:4,
          tension:0.18,
          spanGaps:false,
          borderColor:baseLineColor,
          segment: metricId==="temperature" ? {
            borderColor(context){
              const key=dayLabels[context.p0DataIndex];
              return dailyInfo.dayCategoryByKey.get(key)?.color || baseLineColor;
            }
          } : undefined
        },
        {
          type:"scatter",
          label:"Tagesminimum",
          data:rows.map((row,index)=>dailyInfo.minIndices.has(index)?row.value:null),
          pointRadius:4,
          pointHoverRadius:5,
          showLine:false,
          borderColor:"#2166ac",
          backgroundColor:"#2166ac"
        },
        {
          type:"scatter",
          label:"Tagesmaximum",
          data:rows.map((row,index)=>dailyInfo.maxIndices.has(index)?row.value:null),
          pointRadius:4,
          pointHoverRadius:5,
          showLine:false,
          borderColor:"#b2182b",
          backgroundColor:"#b2182b"
        }
      ]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        legend:{display:true},
        tooltip:{
          callbacks:{
            label(context){
              const value=Number(context.parsed.y);
              if(context.dataset.label==="Tagesminimum" || context.dataset.label==="Tagesmaximum"){
                return `${context.dataset.label}: ${stationObservationNumber(value,1)} ${meta.unit}`;
              }
              const dayKey=dayLabels[context.dataIndex];
              const category=dailyInfo.dayCategoryByKey.get(dayKey);
              const extra=metricId==="temperature" && category ? ` · ${category.label}` : "";
              return `${meta.label}: ${stationObservationNumber(value,1)} ${meta.unit}${extra}`;
            }
          }
        }
      },
      scales:{
        x:{
          ticks:{autoSkip:true,maxTicksLimit:days<=3?18:days<=7?14:12,maxRotation:0}
        },
        y:{
          title:{display:true,text:`${meta.label} [${meta.unit}]`}
        }
      }
    }
  });
}


async function ensureStationProfile(){
  const loading=document.getElementById("stationProfileLoading");
  try{
    await ensureStationClimateDaysLoaded();
    initializeStationProfileControls();
    loading.hidden=true;document.getElementById("stationProfileContent").hidden=false;
    await updateStationProfileBase();
  }catch(error){loading.hidden=false;loading.textContent=`Stationsprofil konnte nicht geladen werden: ${error.message}`;loading.style.color="#7a1010";}
}
function stationProfileFillYearControls(station,profile){
  const yearSelect=document.getElementById("stationProfileYearSelect"),fromSelect=document.getElementById("stationProfileFromSelect");
  const current=Number(stationClimateDaysIndex.current_year);
  const years=new Set([current]);
  Object.values(profile?.counts||{}).forEach(metric=>((metric?.year)||[]).forEach(row=>years.add(Number(row[0]))));
  const sorted=[...years].filter(Number.isFinite).sort((a,b)=>b-a);
  const prevYear=yearSelect.value;yearSelect.innerHTML="";sorted.forEach(year=>{const o=document.createElement("option");o.value=String(year);o.textContent=String(year);yearSelect.appendChild(o);});
  yearSelect.value=sorted.includes(Number(prevYear))?prevYear:String(current);
  const start=Number(station.start_year||sorted.at(-1)||current);
  const choices=[start,1951,1961,1971,1981,1991,2001,2011].filter((value,index,array)=>value>=start&&value<=current&&array.indexOf(value)===index).sort((a,b)=>a-b);
  const prevFrom=fromSelect.value;fromSelect.innerHTML="";choices.forEach(year=>{const o=document.createElement("option");o.value=String(year);o.textContent=year===start?`${year} (Messbeginn)`:String(year);fromSelect.appendChild(o);});
  fromSelect.value=choices.includes(Number(prevFrom))?prevFrom:String(choices[0]||start);
}
function stationProfileRenderNearby(station){
  const box=document.getElementById("stationProfileNearby");
  const nearby=(stationClimateDaysIndex?.stations||[]).filter(item=>item.id!==station.id).map(item=>({station:item,distance:stationProfileDistanceKm(station,item)})).filter(item=>Number.isFinite(item.distance)).sort((a,b)=>a.distance-b.distance).slice(0,6);
  box.innerHTML=nearby.map(({station:item,distance})=>`<button type="button" data-profile-station="${item.id}"><span class="profile-nearby-name">${item.name}</span><span class="profile-nearby-meta">${distance.toLocaleString("de-DE",{maximumFractionDigits:0})} km · ${item.start_year||"?"}–${item.end_year||"?"}</span></button>`).join("")||'<span class="note">Keine nahegelegenen Stationen mit Koordinaten gefunden.</span>';
  box.querySelectorAll("[data-profile-station]").forEach(button=>button.addEventListener("click",()=>{
    const target=button.dataset.profileStation;
    document.getElementById("stationProfileStateSelect").value="Deutschland";document.getElementById("stationProfileSearch").value="";populateStationProfileStations(target);document.getElementById("stationProfileStationSelect").value=target;updateStationProfileBase();
  }));
}
async function updateStationProfileBase(){
  const requestId=++stationProfileRequestId;
  const id=document.getElementById("stationProfileStationSelect")?.value;if(!id) return;
  const station=stationClimateDaysIndex.stations.find(item=>item.id===id);if(!station) return;
  document.getElementById("stationProfileTitle").textContent=`${station.name} (${station.id})`;
  document.getElementById("stationProfileMeta").textContent=[station.state,Number.isFinite(Number(station.height))?`${station.height} m`:null,station.start_year?`Messreihe seit ${station.start_year}`:null].filter(Boolean).join(" · ");
  document.getElementById("stationProfileDataStatus").innerHTML=`<strong>Messwerte bis ${dailyGermanDate(stationClimateDaysIndex.data_through,true)}</strong>Aktuelle DWD-Werte vorläufig`;
  stationProfileRenderNearby(station);
  try{
    const response=await dashboardFetch(station.file,{cache:"no-store"});if(!response.ok) throw new Error(`HTTP ${response.status}`);const profile=await response.json();if(requestId!==stationProfileRequestId)return;stationProfileProfile=profile;stationProfileFillYearControls(station,profile);window.dispatchEvent(new CustomEvent("stationprofilechange"));
  }catch(error){if(requestId===stationProfileRequestId) document.getElementById("stationProfileDataStatus").innerHTML+=`<br><span style="color:#a12222">Historisches Profil: ${error.message}</span>`;}
}
async function openStationProfileDetail(tab){
  const id=document.getElementById("stationProfileStationSelect")?.value;if(!id){switchTab(tab);return;}
  const station=stationClimateDaysIndex?.stations?.find(item=>item.id===id);
  if(tab==="stationClimateDays"){await ensureStationClimateDaysLoaded();document.getElementById("stationClimateDaysStateSelect").value="Deutschland";document.getElementById("stationClimateDaysSearch").value=id;populateStationClimateDaysStations();document.getElementById("stationClimateDaysStationSelect").value=id;await updateStationClimateDays();}
  else if(tab==="stationHeatwaves"){await ensureStationHeatwavesLoaded();document.getElementById("stationHeatwavesStateSelect").value="Deutschland";document.getElementById("stationHeatwavesSearch").value=id;populateStationHeatwavesStations();document.getElementById("stationHeatwavesStationSelect").value=id;await updateStationHeatwaves();}
  else if(tab==="stationPrecip"){await ensureStationPrecipLoaded();document.getElementById("stationPrecipStateSelect").value="Deutschland";document.getElementById("stationPrecipSearch").value=id;populateStationPrecipStations();if([...document.getElementById("stationPrecipStationSelect").options].some(o=>o.value===id)){document.getElementById("stationPrecipStationSelect").value=id;await updateStationPrecipitation();}}
  switchTab(tab);
}

// ================= VERSION 12.2: STATIONSPROFIL – KENNTAGE =================
function stationProfileReferenceYears(){
  const value=document.getElementById("stationProfileReferenceSelect")?.value||"1991-2020";
  const [start,end]=value.split("-").map(Number);return {start,end,label:value.replace("-","–")};
}
function stationProfileCutoffIndex(){
  const md=String(stationClimateDaysIndex?.data_through||"").slice(5);
  const index=(stationClimateDaysIndex?.labels||[]).indexOf(md);return index>=0?index:364;
}
function stationProfileMetric(id){return (stationClimateDaysIndex?.climate_days||[]).find(item=>item.id===id);}
function stationProfileEventDays(metricId){
  return new Map((stationProfileProfile?.historical_event_days?.[metricId]||[]).map(row=>[Number(row[0]),row[1]||[]]));
}
function stationProfileAnnualCount(metricId,year){
  const row=(stationProfileProfile?.counts?.[metricId]?.year||[]).find(item=>Number(item[0])===Number(year));return row?Number(row[1]):null;
}
function stationProfileCountToCutoff(metricId,year,cutoff){
  const current=Number(stationClimateDaysIndex.current_year);
  if(Number(year)===current){
    const metric=stationProfileMetric(metricId);if(!metric)return null;
    const curve=stationClimateDaysCurrentCumulative(document.getElementById("stationProfileStationSelect").value,metric);
    const v=curve[cutoff];
    if(Number.isFinite(v)) return Number(v);
    for(let i=cutoff;i>=0;i--) if(Number.isFinite(curve[i])) return Number(curve[i]);
    return 0;
  }
  const days=stationProfileEventDays(metricId).get(Number(year));if(!days)return null;
  return days.filter(index=>Number(index)<=cutoff).length;
}
function stationProfileReferenceStats(metricId,cutoff){
  const ref=stationProfileReferenceYears();const annual=[],toDate=[];
  for(let year=ref.start;year<=ref.end;year++){
    const a=stationProfileAnnualCount(metricId,year);const d=stationProfileCountToCutoff(metricId,year,cutoff);
    if(Number.isFinite(a))annual.push(a);if(Number.isFinite(d))toDate.push(d);
  }
  const mean=list=>list.length?list.reduce((a,b)=>a+b,0)/list.length:null;
  return {annualMean:mean(annual),toDateMean:mean(toDate),years:Math.min(annual.length,toDate.length)};
}
function stationProfileHistoricalMax(metricId,cutoff){
  const current=Number(stationClimateDaysIndex.current_year);let bestDate=null,bestAnnual=null;
  (stationProfileProfile?.counts?.[metricId]?.year||[]).forEach(row=>{
    const year=Number(row[0]);if(year===current)return;
    const annual=Number(row[1]);const td=stationProfileCountToCutoff(metricId,year,cutoff);
    if(Number.isFinite(td)&&(!bestDate||td>bestDate.value))bestDate={value:td,year};
    if(Number.isFinite(annual)&&(!bestAnnual||annual>bestAnnual.value))bestAnnual={value:annual,year};
  });return {toDate:bestDate,annual:bestAnnual};
}
function stationProfileEventCard(metricId){
  const metric=stationProfileMetric(metricId);if(!metric)return "";
  const selected=Number(document.getElementById("stationProfileYearSelect").value);const current=Number(stationClimateDaysIndex.current_year);const cutoff=stationProfileCutoffIndex();
  const ref=stationProfileReferenceStats(metricId,cutoff),max=stationProfileHistoricalMax(metricId,cutoff);
  const selectedToDate=stationProfileCountToCutoff(metricId,selected,cutoff);const selectedAnnual=selected===current?null:stationProfileAnnualCount(metricId,selected);
  const fmt=value=>Number.isFinite(value)?Number(value).toLocaleString("de-DE",{maximumFractionDigits:1}):"–";
  return `<article class="profile-event-card" style="--metric:${metric.color||'#555'}"><h3>${metric.label}</h3><div class="profile-event-definition">${metric.definition}</div>
    <div class="profile-event-row"><div class="profile-event-cell"><div class="profile-event-value">${fmt(ref.toDateMean)}</div><div class="profile-event-label">Durchschnitt bis Datenstand<br>${stationProfileReferenceYears().label}</div></div><div class="profile-event-cell"><div class="profile-event-value">${fmt(selectedToDate)}</div><div class="profile-event-label">Messwert bis Datenstand<br>${selected}</div></div><div class="profile-event-cell"><div class="profile-event-value">${max.toDate?fmt(max.toDate.value):'–'}</div><div class="profile-event-label">Maximum bis Datenstand<br>${max.toDate?.year||'–'}</div></div></div>
    <div class="profile-event-row"><div class="profile-event-cell"><div class="profile-event-value">${fmt(ref.annualMean)}</div><div class="profile-event-label">Durchschnitt Gesamtjahr<br>${stationProfileReferenceYears().label}</div></div><div class="profile-event-cell"><div class="profile-event-value">${selected===current?fmt(selectedToDate):fmt(selectedAnnual)}</div><div class="profile-event-label">${selected===current?'Bisheriger Stand':'Gesamtjahr'}<br>${selected}</div></div><div class="profile-event-cell"><div class="profile-event-value">${max.annual?fmt(max.annual.value):'–'}</div><div class="profile-event-label">Maximum Gesamtjahr<br>${max.annual?.year||'–'}</div></div></div></article>`;
}
function stationProfileRolling(values,windowSize){
  if(!windowSize)return values.map(()=>null);return values.map((_,index)=>{if(index<windowSize-1)return null;const window=values.slice(index-windowSize+1,index+1).filter(Number.isFinite);return window.length===windowSize?window.reduce((a,b)=>a+b,0)/window.length:null;});
}
function stationProfileAnnualSeries(metricId,years){
  const current=Number(stationClimateDaysIndex.current_year);return years.map(year=>year===current?stationProfileCountToCutoff(metricId,year,stationProfileCutoffIndex()):stationProfileAnnualCount(metricId,year));
}
function renderStationProfileAnnualChart(canvasId,group,title,existing){
  if(existing)existing.destroy();const from=Number(document.getElementById("stationProfileFromSelect").value||0);const current=Number(stationClimateDaysIndex.current_year);const years=[];for(let year=from;year<=current;year++)years.push(year);const rolling=Number(document.getElementById("stationProfileRollingSelect").value||0);const datasets=[];
  group.forEach(id=>{const metric=stationProfileMetric(id);if(!metric)return;const values=stationProfileAnnualSeries(id,years);datasets.push({label:metric.label,data:values,borderColor:stationClimateDaysHexToRgba(metric.color,.34),backgroundColor:'transparent',borderWidth:1.2,pointRadius:1.2,spanGaps:true,tension:0});if(rolling){datasets.push({label:`${rolling}-Jahres-Mittel · ${metric.label}`,data:stationProfileRolling(values.map((v,i)=>years[i]===current?null:v),rolling),borderColor:metric.color,borderDash:[6,4],borderWidth:2.4,pointRadius:0,spanGaps:true,tension:.15});}});
  return new Chart(document.getElementById(canvasId),{type:'line',data:{labels:years,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{title:{display:true,text:title,font:{size:18,weight:'bold'}},subtitle:{display:true,text:`Historische Gesamtjahre; ${current} bis Datenstand. Gleitendes Mittel ohne laufendes Jahr.`,color:'#666'},datalabels:{display:false},zoom:{pan:{enabled:true,mode:'x'},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:'x'}}},scales:{x:{ticks:{maxTicksLimit:18}},y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:'Anzahl Tage'}}}}});
}
function stationProfileComparisonRows(){
  const from=Number(document.getElementById("stationProfileFromSelect").value||0),current=Number(stationClimateDaysIndex.current_year),cutoff=stationProfileCutoffIndex();const ids=['summer','hot','desert','extreme_hot','tropical_night','frost','ice'];const rows=[];
  for(let year=current;year>=from;year--){const values=ids.map(id=>stationProfileCountToCutoff(id,year,cutoff));if(values.some(Number.isFinite))rows.push({year,values});}return rows;
}
async function renderStationProfileClimate(){
  if(!stationProfileProfile||!stationClimateDaysIndex||!document.getElementById('stationProfileSummerCards'))return;
  await loadStationClimateDaysCurrentMonths();
  document.getElementById('stationProfileSummerCards').innerHTML=['summer','hot','desert','tropical_night','extreme_hot'].map(stationProfileEventCard).join('');
  document.getElementById('stationProfileWinterCards').innerHTML=['frost','ice'].map(stationProfileEventCard).join('');
  stationProfileSummerAnnualChart=renderStationProfileAnnualChart('stationProfileSummerAnnualChart',['summer','hot','desert','tropical_night'],'Sommerereignisse pro Jahr',stationProfileSummerAnnualChart);
  stationProfileWinterAnnualChart=renderStationProfileAnnualChart('stationProfileWinterAnnualChart',['frost','ice'],'Winterereignisse pro Jahr',stationProfileWinterAnnualChart);
  try{renderStationMonthlyDays("profil","stationProfileWinterAnnualChart",stationProfileProfile,document.getElementById("stationProfileStationSelect").value,"frost");}catch(error){console.error("Stationsprofil monatliche Kenntage:",error);}
  const date=dailyGermanDate(stationClimateDaysIndex.data_through,true);document.getElementById('stationProfileComparisonTitle').textContent=`Klimaereignisse bis ${date}`;
  const tbody=document.querySelector('#stationProfileComparisonTable tbody');tbody.innerHTML=stationProfileComparisonRows().map(row=>`<tr class="${row.year===Number(stationClimateDaysIndex.current_year)?'profile-current-row':''}"><td>${row.year}</td>${row.values.map(value=>`<td>${Number.isFinite(value)?value:'–'}</td>`).join('')}</tr>`).join('');
  initializeChartExportButtons();
}
window.addEventListener('stationprofilechange',()=>renderStationProfileClimate().catch(error=>console.error('Stationsprofil Kenntage:',error)));
window.addEventListener('stationprofilechange',()=>renderStationProfileClimateValuesSuite().catch(error=>console.error('Stationsprofil Klimatabelle:',error)));

// ================= VERSION 12.2a: STATIONSPROFIL – GRÜNLANDTEMPERATURSUMME =================
function stationProfileGtsPayload(){
  return stationProfileProfile?.temperature_sums?.gts||null;
}
function stationProfileGtsFactor(month){
  if(Number(month)===1)return .5;
  if(Number(month)===2)return .75;
  return 1;
}
function stationProfileGtsThresholdRows(){
  const payload=stationProfileGtsPayload();
  if(Array.isArray(payload?.threshold_dates)&&payload.threshold_dates.length){
    return payload.threshold_dates.map(row=>({
      year:Number(row[0]),
      thresholdDate:row[1]||null
    })).filter(row=>Number.isFinite(row.year)&&row.thresholdDate);
  }
  return (payload?.years||[]).map(row=>({
    year:Number(row[0]),
    thresholdDate:row[3]||null
  })).filter(row=>Number.isFinite(row.year)&&row.thresholdDate);
}
function stationProfileCurrentGts(){
  const year=Number(stationClimateDaysIndex?.current_year);
  const through=String(stationClimateDaysIndex?.data_through||"");
  const labels=stationClimateDaysIndex?.labels||[];
  const id=document.getElementById('stationProfileStationSelect')?.value;
  const curve=Array(labels.length).fill(null);
  let total=0,exactTotal=0,missingDays=0,thresholdDate=null,missingBeforeThreshold=0,exact=true;
  if(!id||!Number.isFinite(year))return {curve,total:null,missingDays:0,thresholdDate:null,missingBeforeThreshold:0};

  for(let index=0;index<labels.length;index++){
    const iso=`${year}-${labels[index]}`;
    if(through&&iso>through)break;
    const pair=stationClimateDaysPair(id,iso);
    const rawTm=pair?.[4];
    const tm=(rawTm===null||rawTm===undefined||rawTm==="")?null:Number(rawTm)/10;
    if(!Number.isFinite(tm)){
      missingDays+=1;
      exact=false;
      curve[index]=null;
      continue;
    }
    const month=Number(labels[index].slice(0,2));
    const increment=tm>0?tm*stationProfileGtsFactor(month):0;
    total+=increment;
    if(exact)exactTotal+=increment;
    total=Math.round(total*10)/10;
    exactTotal=Math.round(exactTotal*10)/10;
    curve[index]=exact?exactTotal:null;
    if(!thresholdDate&&exact&&exactTotal>=200){
      thresholdDate=iso;
      missingBeforeThreshold=missingDays;
    }
  }
  return {curve,total:Math.round(total*10)/10,missingDays,thresholdDate,missingBeforeThreshold};
}
function stationProfileGtsThresholdStats(rows,startYear=null,endYear=null){
  const labels=stationClimateDaysIndex?.labels||[];
  const items=rows.filter(row=>{
    if(!row.thresholdDate)return false;
    if(Number.isFinite(startYear)&&row.year<startYear)return false;
    if(Number.isFinite(endYear)&&row.year>endYear)return false;
    return true;
  }).map(row=>({...row,index:labels.indexOf(String(row.thresholdDate).slice(5))})).filter(row=>row.index>=0).sort((a,b)=>a.index-b.index||a.year-b.year);
  if(!items.length)return {count:0,medianDate:null,earliest:null,latest:null};
  const middle=(items.length-1)/2;
  const medianIndex=Number.isInteger(middle)?items[middle].index:Math.round((items[Math.floor(middle)].index+items[Math.ceil(middle)].index)/2);
  const medianLabel=labels[Math.max(0,Math.min(labels.length-1,medianIndex))]||null;
  return {
    count:items.length,
    medianDate:medianLabel?`2000-${medianLabel}`:null,
    earliest:items[0],
    latest:items[items.length-1]
  };
}
function stationProfileGtsValue(value){
  return Number.isFinite(Number(value))?`${Number(value).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})} K`:'–';
}
async function renderStationProfileGts(){
  const canvas=document.getElementById('stationProfileGtsChart');
  if(!canvas||!stationProfileProfile||!stationClimateDaysIndex)return;
  await loadStationClimateDaysCurrentMonths();

  const payload=stationProfileGtsPayload();
  const year=Number(stationClimateDaysIndex.current_year);
  const through=stationClimateDaysIndex.data_through;
  document.getElementById('stationProfileGtsCurrentLabel').textContent=`GTS ${year}`;
  document.getElementById('stationProfileGtsThresholdLabel').textContent=`200 K ${year}`;

  if(!payload){
    document.getElementById('stationProfileGtsCurrentValue').textContent='–';
    document.getElementById('stationProfileGtsCurrentDetail').textContent='Für diese Station liegen noch keine GTS-Daten vor.';
    document.getElementById('stationProfileGtsMeanValue').textContent='–';
    document.getElementById('stationProfileGtsThresholdValue').textContent='–';
    document.getElementById('stationProfileGtsThresholdMeanValue').textContent='–';
    document.getElementById('stationProfileGtsRecordNote').textContent='';
    if(stationProfileGtsChart){stationProfileGtsChart.destroy();stationProfileGtsChart=null;}
    return;
  }

  const current=stationProfileCurrentGts();
  const cutoff=stationProfileCutoffIndex();
  const referenceCurve=payload.reference_mean_cumulative||[];
  const referenceValue=Number(referenceCurve[cutoff]);
  const thresholdRows=stationProfileGtsThresholdRows();
  const referenceThreshold=stationProfileGtsThresholdStats(thresholdRows,1991,2020);
  const allThreshold=stationProfileGtsThresholdStats(thresholdRows);

  document.getElementById('stationProfileGtsCurrentValue').textContent=stationProfileGtsValue(current.total);
  document.getElementById('stationProfileGtsCurrentDetail').textContent=`Stand ${dailyGermanDate(through,true)} · ${current.missingDays} fehlende TMK-Tage`;
  document.getElementById('stationProfileGtsMeanValue').textContent=stationProfileGtsValue(referenceValue);
  document.getElementById('stationProfileGtsMeanDetail').textContent=`1991–2020 bis ${dailyGermanDate(through,false)} · ${payload.reference_years||referenceThreshold.count} Referenzjahre`;

  if(current.thresholdDate){
    document.getElementById('stationProfileGtsThresholdValue').textContent=dailyGermanDate(current.thresholdDate,false);
    document.getElementById('stationProfileGtsThresholdDetail').textContent=current.missingBeforeThreshold
      ?`200 K anhand verfügbarer TMK-Werte · ${current.missingBeforeThreshold} Tag(e) davor ohne TMK`
      :'200-K-Schwelle erreicht';
  }else{
    document.getElementById('stationProfileGtsThresholdValue').textContent='noch nicht';
    document.getElementById('stationProfileGtsThresholdDetail').textContent=current.missingDays
      ?'200-K-Termin wegen TMK-Lücke nicht exakt bestimmbar'
      :Number.isFinite(current.total)?`${stationProfileGtsValue(current.total)} von 200 K erreicht`:'keine aktuelle TMK-Reihe';
  }

  document.getElementById('stationProfileGtsThresholdMeanValue').textContent=referenceThreshold.medianDate?dailyGermanDate(referenceThreshold.medianDate,false):'–';
  document.getElementById('stationProfileGtsThresholdMeanDetail').textContent=referenceThreshold.count?`Median aus ${referenceThreshold.count} Jahren 1991–2020`:'kein vollständiger Referenzzeitraum';

  if(allThreshold.earliest&&allThreshold.latest){
    document.getElementById('stationProfileGtsRecordNote').innerHTML=
      `<strong>200-K-Rekorde seit Messbeginn:</strong> frühestens ${dailyGermanDate(allThreshold.earliest.thresholdDate,false)} ${allThreshold.earliest.year}, `+
      `spätestens ${dailyGermanDate(allThreshold.latest.thresholdDate,false)} ${allThreshold.latest.year}. `+
      `Historische Einzeljahreskurven werden nur so lange fortgeführt, wie das DWD-Tagesmittel TMK lückenlos vorliegt.`;
  }else{
    document.getElementById('stationProfileGtsRecordNote').textContent='Für 200-K-Rekorde sind nicht genügend lückenlose historische TMK-Frühjahre vorhanden.';
  }

  const rawLabels=stationClimateDaysIndex.labels||[];
  const extraDays=Math.max(0,Number(payload.chart_extra_days)||10);
  const historicalEnd=Number.isFinite(Number(payload.chart_end_index))?Number(payload.chart_end_index):120;
  const currentThresholdIndex=current.thresholdDate?rawLabels.indexOf(String(current.thresholdDate).slice(5)):-1;
  const throughIndex=rawLabels.indexOf(String(through||'').slice(5));
  const currentEnd=currentThresholdIndex>=0
    ?Math.min(rawLabels.length-1,currentThresholdIndex+extraDays)
    :(throughIndex>=0?throughIndex:historicalEnd);
  const chartEnd=Math.max(0,Math.min(rawLabels.length-1,Math.max(historicalEnd,currentEnd)));
  const labels=rawLabels.slice(0,chartEnd+1).map(stationClimateDaysDateLabel);
  const thresholdLine=labels.map(()=>200);

  const historicalDatasets=(payload.historical_curves||[]).map((row,index)=>({
    label:'Historische Einzeljahre',
    gtsHistorical:true,
    gtsLegend:index===0,
    gtsYear:Number(row[0]),
    data:(row[1]||[]).slice(0,chartEnd+1),
    borderColor:'rgba(105,115,120,.24)',
    borderWidth:.8,
    pointRadius:0,
    pointHoverRadius:2,
    spanGaps:false,
    fill:false,
    tension:0,
    order:10
  }));

  const datasets=[
    ...historicalDatasets,
    {label:'Historisches Minimum',data:(payload.historical_daily_min||[]).slice(0,chartEnd+1),borderColor:'#4c78a8',borderWidth:2,pointRadius:0,spanGaps:false,fill:false,tension:0,order:5},
    {label:'Historisches Maximum',data:(payload.historical_daily_max||[]).slice(0,chartEnd+1),borderColor:'#c66a2b',borderWidth:2,pointRadius:0,spanGaps:false,fill:false,tension:0,order:5},
    {label:'Mittel 1991–2020',data:referenceCurve.slice(0,chartEnd+1),borderColor:'#333',borderDash:[7,5],borderWidth:2.2,pointRadius:0,spanGaps:false,fill:false,tension:0,order:3},
    {label:'Vegetationsschwelle 200 K',data:thresholdLine,borderColor:'rgba(177,107,0,.75)',borderDash:[3,4],borderWidth:1.5,pointRadius:0,spanGaps:true,fill:false,order:2},
    {label:`GTS ${year}`,data:current.curve.slice(0,chartEnd+1),borderColor:'#2e7d32',backgroundColor:'rgba(46,125,50,.10)',borderWidth:3,pointRadius:0,pointHoverRadius:3,spanGaps:false,fill:false,tension:0,order:0}
  ];

  if(stationProfileGtsChart)stationProfileGtsChart.destroy();
  stationProfileGtsChart=new Chart(canvas,{
    type:'line',
    data:{labels,datasets},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:'nearest',intersect:false,axis:'xy'},
      plugins:{
        title:{display:true,text:`Grünlandtemperatursumme ${year} – ${stationProfileProfile.name||''}`,font:{size:18,weight:'bold'}},
        subtitle:{display:true,text:`Alle verfügbaren Messjahre · Tages-Minimum/Maximum · Darstellung bis ${extraDays} Tage nach dem spätesten 200-K-Termin`,color:'#666'},
        datalabels:{display:false},
        legend:{
          labels:{
            filter:(item,data)=>{
              const dataset=data.datasets[item.datasetIndex];
              return !dataset?.gtsHistorical||dataset?.gtsLegend;
            }
          }
        },
        tooltip:{
          callbacks:{
            label:context=>{
              const dataset=context.dataset;
              const label=dataset.gtsHistorical?`GTS ${dataset.gtsYear}`:dataset.label;
              return `${label}: ${Number(context.parsed.y).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})} K`;
            }
          }
        }
      },
      scales:{
        x:{ticks:{maxTicksLimit:12,maxRotation:0}},
        y:{beginAtZero:true,title:{display:true,text:'GTS (K)'}}
      }
    }
  });
  initializeChartExportButtons();
}
window.addEventListener('stationprofilechange',()=>renderStationProfileGts().catch(error=>console.error('Stationsprofil GTS:',error)));

// ================= VERSION 12.2b: STATIONSPROFIL – WÄRME- UND KÄLTESUMME =================
function stationProfileTemperatureSumPayload(id){
  return stationProfileProfile?.temperature_sums?.[id]||null;
}
function stationProfileCurrentWarmthSum(){
  const year=Number(stationClimateDaysIndex?.current_year);
  const through=String(stationClimateDaysIndex?.data_through||"");
  const labels=stationClimateDaysIndex?.labels||[];
  const id=document.getElementById('stationProfileStationSelect')?.value;
  const curve=Array(labels.length).fill(null);
  let total=0,exactTotal=0,missingDays=0,exact=true;
  if(!id||!Number.isFinite(year))return {curve,total:null,missingDays:0};
  for(let index=0;index<labels.length;index++){
    const iso=`${year}-${labels[index]}`;
    if(through&&iso>through)break;
    const pair=stationClimateDaysPair(id,iso);
    const rawTm=pair?.[4];
    const tm=(rawTm===null||rawTm===undefined||rawTm==="")?null:Number(rawTm)/10;
    if(!Number.isFinite(tm)){
      missingDays+=1;
      exact=false;
      continue;
    }
    const contribution=tm>10?tm:0;
    total+=contribution;
    if(exact)exactTotal+=contribution;
    curve[index]=exact?Math.round(exactTotal*10)/10:null;
  }
  return {curve,total:Math.round(total*10)/10,missingDays};
}
function stationProfileWinterLabels(){
  const labels=[];
  const cursor=new Date(Date.UTC(2000,10,1));
  const end=new Date(Date.UTC(2001,2,31));
  while(cursor<=end){
    labels.push(`${String(cursor.getUTCMonth()+1).padStart(2,'0')}-${String(cursor.getUTCDate()).padStart(2,'0')}`);
    cursor.setUTCDate(cursor.getUTCDate()+1);
  }
  return labels;
}
function stationProfileColdSeasonEndYear(){
  const through=String(stationClimateDaysIndex?.data_through||'');
  const year=Number(through.slice(0,4));
  const month=Number(through.slice(5,7));
  return month>=11?year+1:year;
}
function stationProfileCurrentColdSum(){
  const id=document.getElementById('stationProfileStationSelect')?.value;
  const through=String(stationClimateDaysIndex?.data_through||'');
  const seasonEnd=stationProfileColdSeasonEndYear();
  const labels=stationProfileWinterLabels();
  const curve=Array(labels.length).fill(null);
  let total=0,exactTotal=0,missingDays=0,exact=true;
  if(!id||!Number.isFinite(seasonEnd))return {curve,total:null,missingDays:0,seasonEnd:null};
  const startIso=`${seasonEnd-1}-11-01`;
  const endIso=`${seasonEnd}-03-31`;
  labels.forEach((label,index)=>{
    const month=Number(label.slice(0,2));
    const iso=`${month>=11?seasonEnd-1:seasonEnd}-${label}`;
    if(iso<startIso||iso>endIso||iso>through)return;
    const pair=stationClimateDaysPair(id,iso);
    const rawTm=pair?.[4];
    const tm=(rawTm===null||rawTm===undefined||rawTm==="")?null:Number(rawTm)/10;
    if(!Number.isFinite(tm)){
      missingDays+=1;
      exact=false;
      return;
    }
    const contribution=tm<0?Math.abs(tm):0;
    total+=contribution;
    if(exact)exactTotal+=contribution;
    curve[index]=exact?Math.round(exactTotal*10)/10:null;
  });
  return {curve,total:Math.round(total*10)/10,missingDays,seasonEnd};
}
function stationProfileSumRecord(rows,mode='max'){
  const valid=(rows||[]).filter(row=>Number.isFinite(Number(row?.[1])));
  if(!valid.length)return null;
  return valid.reduce((best,row)=>{
    if(!best)return row;
    return mode==='max'
      ?(Number(row[1])>Number(best[1])?row:best)
      :(Number(row[1])<Number(best[1])?row:best);
  },null);
}
function stationProfileWinterSeasonLabel(endYear){
  return Number.isFinite(Number(endYear))?`${Number(endYear)-1}/${String(Number(endYear)).slice(-2)}`:'–';
}
async function renderStationProfileWarmthAndCold(){
  if(!stationProfileProfile||!stationClimateDaysIndex)return;
  await loadStationClimateDaysCurrentMonths();

  const year=Number(stationClimateDaysIndex.current_year);
  const through=String(stationClimateDaysIndex.data_through||'');
  const rawLabels=stationClimateDaysIndex.labels||[];

  const warmth=stationProfileTemperatureSumPayload('warmth');
  const warmthCurrent=stationProfileCurrentWarmthSum();
  document.getElementById('stationProfileWarmthCurrentLabel').textContent=`Wärmesumme ${year}`;
  if(warmth){
    const cutoff=stationProfileCutoffIndex();
    const ref=warmth.reference_mean_cumulative||[];
    const refValue=Number(ref[cutoff]);
    const high=stationProfileSumRecord(warmth.years,'max');
    const low=stationProfileSumRecord(warmth.years,'min');
    document.getElementById('stationProfileWarmthCurrentValue').textContent=stationProfileGtsValue(warmthCurrent.total);
    document.getElementById('stationProfileWarmthCurrentDetail').textContent=`Stand ${dailyGermanDate(through,true)} · ${warmthCurrent.missingDays} fehlende TMK-Tage`;
    document.getElementById('stationProfileWarmthMeanValue').textContent=stationProfileGtsValue(refValue);
    document.getElementById('stationProfileWarmthMeanDetail').textContent=`1991–2020 bis ${dailyGermanDate(through,false)}`;
    document.getElementById('stationProfileWarmthMaxValue').textContent=high?stationProfileGtsValue(high[1]):'–';
    document.getElementById('stationProfileWarmthMaxDetail').textContent=high?`Jahr ${high[0]}`:'keine vollständigen Jahre';
    document.getElementById('stationProfileWarmthMinValue').textContent=low?stationProfileGtsValue(low[1]):'–';
    document.getElementById('stationProfileWarmthMinDetail').textContent=low?`Jahr ${low[0]}`:'keine vollständigen Jahre';

    const labels=rawLabels.map(stationClimateDaysDateLabel);
    const warmthHistoricalDatasets=(warmth.historical_curves||[]).map((row,index)=>({
      label:'Historische Einzeljahre',
      temperatureSumHistorical:true,
      temperatureSumLegend:index===0,
      temperatureSumYear:Number(row[0]),
      data:row[1]||[],
      borderColor:'rgba(105,115,120,.22)',
      borderWidth:.8,
      pointRadius:0,
      pointHoverRadius:2,
      spanGaps:false,
      fill:false,
      tension:0,
      order:10
    }));
    if(stationProfileWarmthChart)stationProfileWarmthChart.destroy();
    stationProfileWarmthChart=new Chart(document.getElementById('stationProfileWarmthChart'),{
      type:'line',
      data:{labels,datasets:[
        ...warmthHistoricalDatasets,
        {label:'Historisches Minimum',data:warmth.historical_daily_min||[],borderColor:'#4c78a8',borderWidth:1.8,pointRadius:0,spanGaps:false,tension:0,order:5},
        {label:'Historisches Maximum',data:warmth.historical_daily_max||[],borderColor:'#c66a2b',borderWidth:1.8,pointRadius:0,spanGaps:false,tension:0,order:5},
        {label:'Mittel 1991–2020',data:ref,borderColor:'#333',borderDash:[7,5],borderWidth:2.1,pointRadius:0,spanGaps:false,tension:0,order:3},
        {label:`Wärmesumme ${year}`,data:warmthCurrent.curve,borderColor:'#b85d18',borderWidth:3,pointRadius:0,pointHoverRadius:3,spanGaps:false,tension:0,order:0}
      ]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'nearest',intersect:false,axis:'xy'},plugins:{title:{display:true,text:`Wärmesumme ${year} – ${stationProfileProfile.name||''}`,font:{size:18,weight:'bold'}},subtitle:{display:true,text:'Alle verfügbaren Messjahre · Summe der TMK an Tagen mit Tagesmittel > 10 °C',color:'#666'},datalabels:{display:false},legend:{labels:{filter:(item,data)=>{const dataset=data.datasets[item.datasetIndex];return !dataset?.temperatureSumHistorical||dataset?.temperatureSumLegend;}}},tooltip:{callbacks:{label:context=>{const dataset=context.dataset;const label=dataset.temperatureSumHistorical?`Wärmesumme ${dataset.temperatureSumYear}`:dataset.label;return `${label}: ${Number(context.parsed.y).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})} K`;}}}},scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:'Wärmesumme (K)'}}}}
    });
  }else{
    ['stationProfileWarmthCurrentValue','stationProfileWarmthMeanValue','stationProfileWarmthMaxValue','stationProfileWarmthMinValue'].forEach(id=>document.getElementById(id).textContent='–');
    document.getElementById('stationProfileWarmthCurrentDetail').textContent='Historischer Cache noch nicht aufgebaut.';
    if(stationProfileWarmthChart){stationProfileWarmthChart.destroy();stationProfileWarmthChart=null;}
  }

  const cold=stationProfileTemperatureSumPayload('cold');
  const coldCurrent=stationProfileCurrentColdSum();
  const seasonLabel=stationProfileWinterSeasonLabel(coldCurrent.seasonEnd);
  document.getElementById('stationProfileColdSumCurrentLabel').textContent=`Kältesumme Winter ${seasonLabel}`;
  if(cold){
    const high=stationProfileSumRecord(cold.seasons,'max');
    const low=stationProfileSumRecord(cold.seasons,'min');
    const winterLabels=stationProfileWinterLabels();
    let currentIndex=-1;
    const month=Number(through.slice(5,7));
    const throughSeasonEnd=month>=11?Number(through.slice(0,4))+1:Number(through.slice(0,4));
    if(throughSeasonEnd===coldCurrent.seasonEnd){
      currentIndex=winterLabels.indexOf(through.slice(5));
      if(month>=4&&month<=10)currentIndex=winterLabels.length-1;
    }
    const ref=cold.reference_mean_cumulative||[];
    const refValue=currentIndex>=0?Number(ref[currentIndex]):null;
    document.getElementById('stationProfileColdSumCurrentValue').textContent=stationProfileGtsValue(coldCurrent.total);
    document.getElementById('stationProfileColdSumCurrentDetail').textContent=coldCurrent.missingDays
      ?`${coldCurrent.missingDays} fehlende TMK-Tage in der Saison`
      :`1. November bis 31. März · ${seasonLabel}`;
    document.getElementById('stationProfileColdSumMeanValue').textContent=stationProfileGtsValue(refValue);
    document.getElementById('stationProfileColdSumMeanDetail').textContent=`Mittel 1991–2020 · gleicher Saisonzeitpunkt`;
    document.getElementById('stationProfileColdSumMaxValue').textContent=high?stationProfileGtsValue(high[1]):'–';
    document.getElementById('stationProfileColdSumMaxDetail').textContent=high?`Winter ${stationProfileWinterSeasonLabel(high[0])}`:'keine vollständigen Winter';
    document.getElementById('stationProfileColdSumMinValue').textContent=low?stationProfileGtsValue(low[1]):'–';
    document.getElementById('stationProfileColdSumMinDetail').textContent=low?`Winter ${stationProfileWinterSeasonLabel(low[0])}`:'keine vollständigen Winter';

    const coldHistoricalDatasets=(cold.historical_curves||[]).map((row,index)=>({
      label:'Historische Einzelwinter',
      temperatureSumHistorical:true,
      temperatureSumLegend:index===0,
      temperatureSumSeasonEnd:Number(row[0]),
      data:row[1]||[],
      borderColor:'rgba(105,115,120,.22)',
      borderWidth:.8,
      pointRadius:0,
      pointHoverRadius:2,
      spanGaps:false,
      fill:false,
      tension:0,
      order:10
    }));
    if(stationProfileColdSumChart)stationProfileColdSumChart.destroy();
    stationProfileColdSumChart=new Chart(document.getElementById('stationProfileColdSumChart'),{
      type:'line',
      data:{labels:winterLabels.map(stationClimateDaysDateLabel),datasets:[
        ...coldHistoricalDatasets,
        {label:'Historisches Minimum',data:cold.historical_daily_min||[],borderColor:'#7aa6c2',borderWidth:1.8,pointRadius:0,spanGaps:false,tension:0,order:5},
        {label:'Historisches Maximum',data:cold.historical_daily_max||[],borderColor:'#405a8d',borderWidth:1.8,pointRadius:0,spanGaps:false,tension:0,order:5},
        {label:'Mittel 1991–2020',data:ref,borderColor:'#333',borderDash:[7,5],borderWidth:2.1,pointRadius:0,spanGaps:false,tension:0,order:3},
        {label:`Winter ${seasonLabel}`,data:coldCurrent.curve,borderColor:'#315f8c',borderWidth:3,pointRadius:0,pointHoverRadius:3,spanGaps:false,tension:0,order:0}
      ]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'nearest',intersect:false,axis:'xy'},plugins:{title:{display:true,text:`Kältesumme Winter ${seasonLabel} – ${stationProfileProfile.name||''}`,font:{size:18,weight:'bold'}},subtitle:{display:true,text:'Alle verfügbaren Winter · Summe der Absolutbeträge negativer TMK vom 1. November bis 31. März',color:'#666'},datalabels:{display:false},legend:{labels:{filter:(item,data)=>{const dataset=data.datasets[item.datasetIndex];return !dataset?.temperatureSumHistorical||dataset?.temperatureSumLegend;}}},tooltip:{callbacks:{label:context=>{const dataset=context.dataset;const label=dataset.temperatureSumHistorical?`Winter ${stationProfileWinterSeasonLabel(dataset.temperatureSumSeasonEnd)}`:dataset.label;return `${label}: ${Number(context.parsed.y).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})} K`;}}}},scales:{x:{ticks:{maxTicksLimit:10,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:'Kältesumme (K)'}}}}
    });
  }else{
    ['stationProfileColdSumCurrentValue','stationProfileColdSumMeanValue','stationProfileColdSumMaxValue','stationProfileColdSumMinValue'].forEach(id=>document.getElementById(id).textContent='–');
    document.getElementById('stationProfileColdSumCurrentDetail').textContent='Historischer Cache noch nicht aufgebaut.';
    if(stationProfileColdSumChart){stationProfileColdSumChart.destroy();stationProfileColdSumChart=null;}
  }
  initializeChartExportButtons();
}
window.addEventListener('stationprofilechange',()=>renderStationProfileWarmthAndCold().catch(error=>console.error('Stationsprofil Wärme-/Kältesumme:',error)));

// ================= VERSION 12.3: STATIONSPROFIL – TEMPERATUR UND EXTREME =================
function stationProfileCurrentTemperatureRows(){
  const id=document.getElementById('stationProfileStationSelect')?.value;if(!id)return [];
  const year=Number(stationClimateDaysIndex.current_year),through=stationClimateDaysIndex.data_through,rows=[];
  (stationClimateDaysIndex.labels||[]).forEach((label,index)=>{const iso=`${year}-${label}`;if(iso>through)return;const pair=stationClimateDaysPair(id,iso);if(!pair)return;const tx=Number.isFinite(Number(pair[2]))?Number(pair[2])/10:null;const tn=Number.isFinite(Number(pair[3]))?Number(pair[3])/10:null;const tm=Number.isFinite(Number(pair[4]))?Number(pair[4])/10:(tx!==null&&tn!==null?(tx+tn)/2:null);if(tx===null&&tn===null&&tm===null)return;rows.push({index,date:iso,tx,tn,tm});});return rows;
}
function stationProfileTemperatureColor(value){if(!Number.isFinite(value))return '#555';if(value>=40)return '#7f1717';if(value>=35)return '#c63d2f';if(value>=30)return '#df6b2f';if(value>=25)return '#d89a16';return '#46525a';}
function stationProfileMinColor(value){if(!Number.isFinite(value))return '#555';if(value>=20)return '#9b3ed1';if(value<0)return '#2785c7';return '#5d666b';}
function stationProfileTempLabel(value,kind){if(!Number.isFinite(value))return '–';const cls=kind==='tn'?(value>=20?'profile-temp-tropical':value<0?'profile-temp-frost':''):(value>=35?'profile-temp-veryhot':value>=30?'profile-temp-hot':'');return `<span class="profile-temp-badge ${cls}">${value.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})} °C</span>`;}
function stationProfileMergeExtremes(kind,currentRows){
  const historical=stationProfileProfile?.temperature_extremes?.[kind]||[];let current=[];
  if(kind==='hottest_days')current=currentRows.filter(r=>Number.isFinite(r.tx)).map(r=>[r.date,r.tx]);
  else current=currentRows.filter(r=>Number.isFinite(r.tn)).map(r=>[r.date,r.tn]);
  const all=[...historical,...current];
  all.sort((a,b)=>kind==='coldest_nights'?Number(a[1])-Number(b[1])||String(a[0]).localeCompare(String(b[0])):Number(b[1])-Number(a[1])||String(a[0]).localeCompare(String(b[0])));
  return all.slice(0,10);
}
function stationProfileRenderExtremeTable(id,rows){
  const currentYear=String(stationClimateDaysIndex.current_year);document.querySelector(`#${id} tbody`).innerHTML=rows.map((row,index)=>`<tr class="${String(row[0]).startsWith(currentYear)?'current-year':''}"><td>${index+1}.</td><td>${dailyGermanDate(row[0],false)}</td><td>${Number(row[1]).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})}</td></tr>`).join('');
}
async function renderStationProfileTemperature(){
  if(!stationProfileProfile||!stationClimateDaysIndex||!document.getElementById('stationProfileTemperatureChart'))return;await loadStationClimateDaysCurrentMonths();
  const rows=stationProfileCurrentTemperatureRows(),labels=(stationClimateDaysIndex.labels||[]).map(stationClimateDaysDateLabel),tx=Array(365).fill(null),tn=Array(365).fill(null);rows.forEach(r=>{tx[r.index]=r.tx;tn[r.index]=r.tn;});
  const records=stationProfileProfile.temperature_daily_records||{},reference=stationProfileProfile.temperature_reference_daily_mean||{};
  if(stationProfileTemperatureChart)stationProfileTemperatureChart.destroy();
  stationProfileTemperatureChart=new Chart(document.getElementById('stationProfileTemperatureChart'),{type:'line',data:{labels,datasets:[
    {label:'Allzeit-Maximum',data:records.tx_max||[],borderColor:'rgba(229,104,55,.32)',borderWidth:1.4,pointRadius:0,spanGaps:true},
    {label:'Allzeit-Minimum',data:records.tn_min||[],borderColor:'rgba(53,151,211,.32)',borderWidth:1.4,pointRadius:0,spanGaps:true},
    {label:'Mittel Tmax 1991–2020',data:reference.tx||[],borderColor:'rgba(60,60,60,.42)',borderDash:[5,5],borderWidth:1.2,pointRadius:0,spanGaps:true},
    {label:'Mittel Tmin 1991–2020',data:reference.tn||[],borderColor:'rgba(100,100,100,.32)',borderDash:[3,5],borderWidth:1.2,pointRadius:0,spanGaps:true},
    {label:`Tmax ${stationClimateDaysIndex.current_year}`,data:tx,borderColor:'#d95c18',borderWidth:2.2,pointRadius:0,spanGaps:false,segment:{borderColor:ctx=>stationProfileTemperatureColor((ctx.p0.parsed.y+ctx.p1.parsed.y)/2)}},
    {label:`Tmin ${stationClimateDaysIndex.current_year}`,data:tn,borderColor:'#386d8d',borderWidth:2,pointRadius:0,spanGaps:false,segment:{borderColor:ctx=>stationProfileMinColor((ctx.p0.parsed.y+ctx.p1.parsed.y)/2)}}
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{title:{display:true,text:`Temperaturverlauf ${stationClimateDaysIndex.current_year} – ${stationProfileProfile.name||''}`},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:12}},y:{title:{display:true,text:'Temperatur (°C)'}}}}});
  document.getElementById('stationProfileDailyTitle').textContent=`Tagesdaten ${stationClimateDaysIndex.current_year}`;
  document.getElementById('stationProfileDailyMessage').textContent=(rows.some(r=>Number.isFinite(r.tn))&&rows.some(r=>Number.isFinite(r.tm)))?'':'Tmin/Tagesmittel sind in den geladenen aktuellen Stationsdateien noch nicht enthalten. Nach dem aktuellen DWD-KL-Datenlauf erscheint die vollständige Tabelle.';
  const latest=rows.at(-1)?.date;document.querySelector('#stationProfileDailyTable tbody').innerHTML=[...rows].reverse().map(r=>`<tr class="${r.date===latest?'latest':''}"><td>${dailyGermanDate(r.date,false)}</td><td>${stationProfileTempLabel(r.tn,'tn')}</td><td>${stationProfileTempLabel(r.tm,'tm')}</td><td>${stationProfileTempLabel(r.tx,'tx')}</td></tr>`).join('');
  stationProfileRenderExtremeTable('stationProfileHotTable',stationProfileMergeExtremes('hottest_days',rows));stationProfileRenderExtremeTable('stationProfileColdTable',stationProfileMergeExtremes('coldest_nights',rows));stationProfileRenderExtremeTable('stationProfileWarmNightTable',stationProfileMergeExtremes('warmest_nights',rows));initializeChartExportButtons();
}
window.addEventListener('stationprofilechange',()=>renderStationProfileTemperature().catch(error=>console.error('Stationsprofil Temperatur:',error)));

// ================= VERSION 12.4: STATIONSPROFIL – ÜBERBLICK, KARTE, NIEDERSCHLAG =================
async function stationProfileLoadAuxiliary(){
  const tasks=[];
  if(!stationProfilePrecipIndex)tasks.push(dashboardFetch('station_precip_index.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Niederschlagsindex HTTP ${r.status}`);return r.json();}).then(data=>stationProfilePrecipIndex=data).catch(error=>console.warn(error)));
  if(!stationProfileHeatwaveIndex)tasks.push(dashboardFetch('station_heatwaves_index.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Hitzewellenindex HTTP ${r.status}`);return r.json();}).then(async data=>{stationProfileHeatwaveIndex=data;if(data.ready){const r=await dashboardFetch(data.current_file||'station_heatwaves_current.json',{cache:'no-store'});if(r.ok)stationProfileHeatwaveCurrent=await r.json();}}).catch(error=>console.warn(error)));
  await Promise.all(tasks);
}
function stationProfileRenderOverview(){
  const id=document.getElementById('stationProfileStationSelect')?.value;if(!id)return;
  document.getElementById('stationProfileHistoryValue').textContent=stationProfileProfile?.history_years??'–';
  const ref=stationProfileReferenceYears();document.getElementById('stationProfileReferenceValue').textContent=ref.label;document.getElementById('stationProfileReferenceDetail').textContent=`Auswahl für Kenntage: ${ref.label}; Niederschlag derzeit 1991–2020`;
  const precip=stationProfilePrecipIndex?.stations?.find(item=>item.id===id);const map=precip?.map||{};
  document.getElementById('stationProfilePrecipValue').textContent=Number.isFinite(Number(map.current_total))?`${Number(map.current_total).toLocaleString('de-DE',{maximumFractionDigits:1})} mm`:'–';
  document.getElementById('stationProfilePrecipDetail').textContent=precip?(Number.isFinite(Number(map.deviation_percent))?`${Number(map.deviation_percent)>0?'+':''}${Number(map.deviation_percent).toLocaleString('de-DE',{maximumFractionDigits:1})} % zu 1991–2020 · ${map.missing_days||0} fehlende Tage`:'Referenzwert nicht verfügbar'):'Keine gleichnamige RR-Station im aktuellen Niederschlagsindex';
  const events=stationProfileHeatwaveCurrent?.stations?.[id]?.events||[];document.getElementById('stationProfileHeatwaveValue').textContent=stationProfileHeatwaveIndex?.ready?String(events.length):'–';document.getElementById('stationProfileHeatwaveDetail').textContent=stationProfileHeatwaveIndex?.ready?`${events.reduce((sum,event)=>sum+Number(event.duration||0),0)} Hitzewellentage · Stand ${dailyGermanDate(stationProfileHeatwaveCurrent?.data_through||stationClimateDaysIndex.data_through,true)}`:'Hitzewellendaten noch nicht aufgebaut';
}
function stationProfileMarkerIcon(active=false){return L.divIcon({className:'station-map-marker-icon',html:`<span class="station-map-marker-dot" style="width:${active?18:12}px;height:${active?18:12}px;background:${active?'#0a806a':'#73c9b8'};border:${active?3:2}px solid #fff"></span>`,iconSize:[active?18:12,active?18:12],iconAnchor:[active?9:6,active?9:6]});}
function stationProfileRenderMap(){
  const id=document.getElementById('stationProfileStationSelect')?.value,station=stationClimateDaysIndex?.stations?.find(item=>item.id===id),container=document.getElementById('stationProfileMap');if(!container||!station||!Number.isFinite(Number(station.latitude))||!Number.isFinite(Number(station.longitude))){if(container)container.innerHTML='<div class="note" style="padding:16px">Keine Koordinaten verfügbar.</div>';return;}
  if(!stationProfileMap){stationProfileMap=L.map(container,{scrollWheelZoom:false}).setView([station.latitude,station.longitude],8);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; OpenStreetMap'}).addTo(stationProfileMap);stationProfileMapLayer=L.layerGroup().addTo(stationProfileMap);}stationProfileMapLayer.clearLayers();
  L.marker([station.latitude,station.longitude],{icon:stationProfileMarkerIcon(true)}).bindPopup(`<strong>${station.name}</strong><br>${station.state||''} · ${station.height??'–'} m`).addTo(stationProfileMapLayer);
  (stationClimateDaysIndex.stations||[]).filter(item=>item.id!==id).map(item=>({item,d:stationProfileDistanceKm(station,item)})).filter(x=>x.d<=70&&Number.isFinite(x.d)).sort((a,b)=>a.d-b.d).slice(0,25).forEach(({item,d})=>L.marker([item.latitude,item.longitude],{icon:stationProfileMarkerIcon(false)}).bindPopup(`<strong>${item.name}</strong><br>${d.toLocaleString('de-DE',{maximumFractionDigits:0})} km entfernt`).on('click',()=>{}).addTo(stationProfileMapLayer));
  stationProfileMap.setView([station.latitude,station.longitude],8);setTimeout(()=>stationProfileMap.invalidateSize(),50);
}
async function renderStationProfileAuxiliary(){
  if(!stationProfileProfile)return;await stationProfileLoadAuxiliary();stationProfileRenderOverview();stationProfileRenderMap();
}
window.addEventListener('stationprofilechange',()=>renderStationProfileAuxiliary().catch(error=>console.error('Stationsprofil Zusatzdaten:',error)));

