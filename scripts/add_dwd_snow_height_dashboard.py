#!/usr/bin/env python3
'''Patch the CURRENT repository index.html with the DWD snow-height frontend.

The repository dashboard evolves quickly, so this patcher preserves every
newer feature already present on main instead of replacing index.html with an
older local copy.
'''
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TARGET = Path("index.html")
MARKER = "DWD_SNOW_HEIGHT_FRONTEND_V1"

SNOW_HTML = r'''
<!-- ================= DWD_SNOW_HEIGHT_FRONTEND_V1 ================= -->
<div id="stationSnow" class="tab-content">
  <div class="section-header">
    <h2>Stationsschneehöhe</h2>
    <p>Tägliche Schneehöhe im hydrologischen Jahr im Vergleich mit der Klimatologie 1991–2020 und den historischen Stationswerten.</p>
    <span class="section-status">DWD CDC · SHK_TAG · hydrologisches Jahr 01.11.–31.10. · Fehlwerte werden nicht als 0 cm gewertet</span>
  </div>

  <div id="stationSnowLoading" class="record-loading">
    Schneehöhen werden beim ersten Öffnen geladen …
  </div>

  <div id="stationSnowContent" hidden>
    <div class="controls">
      <div class="control-group">
        <label for="stationSnowStateSelect">Bundesland</label>
        <select id="stationSnowStateSelect"></select>
      </div>

      <div class="control-group" style="min-width:260px">
        <label for="stationSnowSearch">Station suchen</label>
        <input id="stationSnowSearch" type="search" placeholder="Ort oder Stations-ID"
               style="padding:9px 10px;border:1px solid #bbb;border-radius:6px">
      </div>

      <div class="control-group" style="min-width:300px">
        <label for="stationSnowStationSelect">Schneestation</label>
        <select id="stationSnowStationSelect"></select>
      </div>

      <div class="control-group">
        <label for="stationSnowPeriodSelect">Anzeige</label>
        <select id="stationSnowPeriodSelect">
          <option value="snow" selected>Schneesaison (01.11.–31.05.)</option>
          <option value="hydro">Hydrologisches Jahr (01.11.–31.10.)</option>
        </select>
      </div>

      <button class="action" onclick="resetStationSnowZoom()">Zoom zurücksetzen</button>
    </div>

    <div id="stationSnowSummary" class="summary-box">
      Schneehöhenprofil wird aufgebaut …
    </div>

    <div class="chart-container">
      <canvas id="stationSnowChart"></canvas>
    </div>

    <div class="chart-container">
      <canvas id="stationSnowDeviationChart"></canvas>
    </div>

    <div class="chart-container auto">
      <div class="stat-grid">
        <div class="stat-card">
          <h4>Letzte Meldung</h4>
          <div id="stationSnowLatestStat" class="daily-stat-value">–</div>
          <div id="stationSnowLatestDetail" class="daily-stat-detail">–</div>
        </div>
        <div class="stat-card">
          <h4>Saisonmaximum</h4>
          <div id="stationSnowMaxStat" class="daily-stat-value">–</div>
          <div id="stationSnowMaxDetail" class="daily-stat-detail">aktuelles hydrologisches Jahr</div>
        </div>
        <div class="stat-card">
          <h4>Schneedeckentage ≥ 1 cm</h4>
          <div id="stationSnowCoverDaysStat" class="daily-stat-value">–</div>
          <div class="daily-stat-detail">nur tatsächlich beobachtete SHK_TAG-Tage</div>
        </div>
        <div class="stat-card">
          <h4>Referenz 1991–2020</h4>
          <div id="stationSnowReferenceStat" class="daily-stat-value">–</div>
          <div id="stationSnowReferenceDetail" class="daily-stat-detail">Qualitätsjahre mit ≥ 98 % Tagesabdeckung</div>
        </div>
        <div class="stat-card">
          <h4>Historische Reihe</h4>
          <div id="stationSnowHistoryStat" class="daily-stat-value">–</div>
          <div id="stationSnowHistoryDetail" class="daily-stat-detail">akzeptierte hydrologische Jahre</div>
        </div>
      </div>
    </div>

    <p id="stationSnowSourceNote" class="note"></p>
  </div>
</div>
'''

SNOW_JS = r'''
// ================= DWD_SNOW_HEIGHT_FRONTEND_V1 =================
function stationSnowFormat(value,decimals=1){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function stationSnowGermanDate(iso){
  if(!iso) return "–";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}

function stationSnowMonthDayLabel(monthDay){
  if(!monthDay || !monthDay.includes("-")) return monthDay||"";
  const [month,day]=monthDay.split("-");
  return `${day}.${month}.`;
}

function stationSnowReferenceStatusLabel(status){
  const labels={
    complete:"vollständig",
    good:"sehr gut",
    usable:"brauchbar",
    limited:"eingeschränkt",
    insufficient:"unzureichend"
  };
  return labels[status]||status||"–";
}

async function ensureStationSnowLoaded(){
  if(stationSnowIndex && stationSnowCurrentIndex){
    await updateStationSnow();
    return stationSnowIndex;
  }
  if(stationSnowLoading) return stationSnowLoading;

  const loading=document.getElementById("stationSnowLoading");
  loading.textContent="Schneehöhen werden geladen …";

  stationSnowLoading=Promise.all([
    dashboardFetch("station_snow_height_index.json",{cache:"no-store"}).then(response=>{
      if(!response.ok) throw new Error(`Historischer Schneehöhenindex: HTTP ${response.status}`);
      return response.json();
    }),
    dashboardFetch("station_snow_height_current_index.json",{cache:"no-store"}).then(response=>{
      if(!response.ok) throw new Error(`Aktueller Schneehöhenindex: HTTP ${response.status}`);
      return response.json();
    })
  ]).then(([historyIndex,currentIndex])=>{
    if(!historyIndex.ready) throw new Error("Die historischen Schneehöhenprofile sind noch nicht bereit.");
    if(!currentIndex.ready) throw new Error("Die aktuelle Schneehöhensaison ist noch nicht bereit.");

    stationSnowIndex=historyIndex;
    stationSnowCurrentIndex=currentIndex;
    initializeStationSnowControls();

    loading.hidden=true;
    document.getElementById("stationSnowContent").hidden=false;

    document.getElementById("stationSnowSourceNote").textContent=
      `${historyIndex.source_note||"Quelle: DWD Climate Data Center, SHK_TAG."} `+
      `Hydrologisches Jahr ${currentIndex.hydrological_year}: ${currentIndex.period_start} bis ${currentIndex.period_end}. `+
      `Aktueller Netz-Datenstand: ${currentIndex.data_through?stationSnowGermanDate(currentIndex.data_through):"–"}.`;

    return updateStationSnow().then(()=>historyIndex);
  }).catch(error=>{
    loading.textContent=`Schneehöhen konnten nicht geladen werden: ${error.message}`;
    loading.style.color="#7a1010";
    throw error;
  });

  return stationSnowLoading;
}

function initializeStationSnowControls(){
  const stateSelect=document.getElementById("stationSnowStateSelect");
  const states=[...new Set((stationSnowIndex.stations||[]).map(station=>station.state).filter(Boolean))]
    .sort((a,b)=>a.localeCompare(b,"de"));

  stateSelect.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  states.forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });
  stateSelect.value="Deutschland";

  stateSelect.addEventListener("change",()=>{
    populateStationSnowStations();
    updateStationSnow();
  });

  document.getElementById("stationSnowSearch").addEventListener("input",()=>{
    populateStationSnowStations();
    updateStationSnow();
  });

  document.getElementById("stationSnowStationSelect").addEventListener("change",updateStationSnow);
  document.getElementById("stationSnowPeriodSelect").addEventListener("change",updateStationSnow);

  populateStationSnowStations(true);
}

function filteredStationSnowStations(){
  const state=document.getElementById("stationSnowStateSelect").value;
  const search=document.getElementById("stationSnowSearch").value.trim().toLocaleLowerCase("de-DE");

  return (stationSnowIndex.stations||[]).filter(station=>{
    if(state!=="Deutschland" && station.state!==state) return false;
    if(!search) return true;
    return `${station.name} ${station.id}`.toLocaleLowerCase("de-DE").includes(search);
  });
}

function populateStationSnowStations(firstLoad=false){
  const select=document.getElementById("stationSnowStationSelect");
  const previous=select.value;
  const stations=filteredStationSnowStations();

  select.innerHTML="";
  stations.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    const currentMeta=(stationSnowCurrentIndex?.stations||[]).find(item=>item.id===station.id);
    option.textContent=`${station.name} (${station.id})${currentMeta && !currentMeta.current_available?" · keine Saisonwerte":""}`;
    select.appendChild(option);
  });

  if(stations.some(station=>station.id===previous)){
    select.value=previous;
  }else if(firstLoad && stations.some(station=>station.id==="05792")){
    select.value="05792";
  }else if(stations.length){
    select.value=stations[0].id;
  }
}

function stationSnowDailyObjects(profile){
  const columns=profile.daily_columns||[];
  const indexes=Object.fromEntries(columns.map((name,index)=>[name,index]));

  return (profile.daily||[]).map(row=>({
    monthDay:row[indexes.month_day],
    nReference:row[indexes.n_reference],
    median:row[indexes.median_cm],
    p16:row[indexes.p16_cm],
    p84:row[indexes.p84_cm],
    p2_5:row[indexes.p2_5_cm],
    p97_5:row[indexes.p97_5_cm],
    historicalMax:row[indexes.historical_max_cm]
  }));
}

function stationSnowCurrentObjects(current){
  if(!current) return new Map();
  const columns=current.columns||[];
  const indexes=Object.fromEntries(columns.map((name,index)=>[name,index]));
  const result=new Map();

  (current.rows||[]).forEach(row=>{
    const iso=row[indexes.date];
    if(!iso) return;
    result.set(String(iso).slice(5),{
      date:iso,
      snow:row[indexes.snow_cm],
      median:row[indexes.reference_median_cm],
      anomaly:row[indexes.anomaly_cm]
    });
  });

  return result;
}

function stationSnowVisibleDaily(profile){
  const period=document.getElementById("stationSnowPeriodSelect")?.value||"snow";
  const rows=stationSnowDailyObjects(profile);
  if(period==="hydro") return rows;

  const end=rows.findIndex(row=>row.monthDay==="05-31");
  return end>=0?rows.slice(0,end+1):rows;
}

function stationSnowBandDataset(label,data,backgroundColor,borderColor,helper=false){
  return {
    label,
    data,
    borderColor,
    backgroundColor,
    borderWidth:helper?0:0.7,
    pointRadius:0,
    tension:.08,
    fill:helper?false:"-1",
    _snowBandHelper:helper
  };
}

function stationSnowCurrentMeta(stationId){
  return (stationSnowCurrentIndex?.stations||[]).find(station=>station.id===stationId)||null;
}

async function loadStationSnowFiles(stationId){
  const station=(stationSnowIndex.stations||[]).find(item=>item.id===stationId);
  if(!station) throw new Error("Station nicht gefunden.");

  const currentMeta=stationSnowCurrentMeta(stationId);

  const profilePromise=dashboardFetch(station.file||`station_snow_height_profiles/${stationId}.json`,{cache:"no-store"})
    .then(response=>{
      if(!response.ok) throw new Error(`Historisches Profil HTTP ${response.status}`);
      return response.json();
    });

  const currentPromise=currentMeta?.current_available && currentMeta.file
    ? dashboardFetch(currentMeta.file,{cache:"no-store"}).then(response=>{
        if(!response.ok) throw new Error(`Aktuelle Saison HTTP ${response.status}`);
        return response.json();
      })
    : Promise.resolve(null);

  const [profile,current]=await Promise.all([profilePromise,currentPromise]);
  return {station,profile,current,currentMeta};
}

async function updateStationSnow(){
  if(!stationSnowIndex || !stationSnowCurrentIndex) return;

  const stationId=document.getElementById("stationSnowStationSelect")?.value;
  if(!stationId){
    document.getElementById("stationSnowSummary").textContent="Keine Station für den gewählten Filter gefunden.";
    return;
  }

  const requestId=++stationSnowRequestId;
  document.getElementById("stationSnowSummary").textContent="Schneehöhenprofil wird geladen …";

  try{
    const {station,profile,current,currentMeta}=await loadStationSnowFiles(stationId);
    if(requestId!==stationSnowRequestId) return;

    stationSnowProfile=profile;
    stationSnowCurrent=current;

    const daily=stationSnowVisibleDaily(profile);
    const currentByMonthDay=stationSnowCurrentObjects(current);

    const labels=daily.map(row=>stationSnowMonthDayLabel(row.monthDay));
    const currentValues=daily.map(row=>currentByMonthDay.get(row.monthDay)?.snow??null);
    const medianValues=daily.map(row=>row.median??null);
    const p16=daily.map(row=>row.p16??null);
    const p84=daily.map(row=>row.p84??null);
    const p2_5=daily.map(row=>row.p2_5??null);
    const p97_5=daily.map(row=>row.p97_5??null);
    const historicalMax=daily.map(row=>row.historicalMax??null);
    const anomalies=daily.map(row=>currentByMonthDay.get(row.monthDay)?.anomaly??null);

    const hydroYear=stationSnowCurrentIndex.hydrological_year;
    const height=station.height===null||station.height===undefined?"":` · ${station.height} m`;
    const periodLabel=document.getElementById("stationSnowPeriodSelect").value==="hydro"
      ?"01.11.–31.10."
      :"01.11.–31.05.";

    if(stationSnowChart) stationSnowChart.destroy();
    stationSnowChart=new Chart(document.getElementById("stationSnowChart"),{
      type:"line",
      data:{
        labels,
        datasets:[
          stationSnowBandDataset("",p2_5,"rgba(160,166,171,0)","rgba(160,166,171,0)",true),
          stationSnowBandDataset("2,5–97,5 %",p97_5,"rgba(154,160,166,.22)","rgba(135,142,148,.32)"),
          stationSnowBandDataset("",p16,"rgba(100,108,115,0)","rgba(100,108,115,0)",true),
          stationSnowBandDataset("16–84 %",p84,"rgba(105,112,119,.30)","rgba(95,102,108,.38)"),
          {
            label:"Median 1991–2020",
            data:medianValues,
            borderColor:"#343a40",
            backgroundColor:"#343a40",
            borderWidth:2.2,
            pointRadius:0,
            fill:false,
            tension:.08
          },
          {
            label:"Historisches Maximum",
            data:historicalMax,
            borderColor:"rgba(80,86,91,.70)",
            borderWidth:1.5,
            borderDash:[7,5],
            pointRadius:0,
            fill:false,
            tension:.05
          },
          {
            label:`Hydrologisches Jahr ${hydroYear}`,
            data:currentValues,
            borderColor:"#d9342b",
            backgroundColor:"#d9342b",
            borderWidth:3,
            pointRadius:0,
            pointHoverRadius:4,
            fill:false,
            spanGaps:false,
            tension:.08
          }
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        plugins:{
          title:{
            display:true,
            text:`Schneehöhe ${station.name} (${station.id})${height} · ${periodLabel}`
          },
          legend:{labels:{filter:item=>Boolean(item.text)}},
          datalabels:{display:false},
          tooltip:{
            callbacks:{
              label:context=>{
                if(context.parsed.y===null || context.parsed.y===undefined) return null;
                return `${context.dataset.label}: ${stationSnowFormat(context.parsed.y)} cm`;
              }
            }
          },
          zoom:{
            pan:{enabled:true,mode:"x"},
            zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}
          }
        },
        scales:{
          x:{ticks:{maxTicksLimit:12,maxRotation:0}},
          y:{beginAtZero:true,title:{display:true,text:"Schneehöhe (cm)"}}
        }
      }
    });

    if(stationSnowDeviationChart) stationSnowDeviationChart.destroy();
    stationSnowDeviationChart=new Chart(document.getElementById("stationSnowDeviationChart"),{
      type:"line",
      data:{
        labels,
        datasets:[{
          label:`Abweichung ${hydroYear} zum Median 1991–2020`,
          data:anomalies,
          borderWidth:1.6,
          pointRadius:0,
          fill:"origin",
          spanGaps:false,
          tension:.05,
          segment:{
            borderColor:context=>{
              const y0=context.p0.parsed.y??0;
              const y1=context.p1.parsed.y??0;
              return (y0+y1)/2>=0?"#2f6f9f":"#c0523d";
            },
            backgroundColor:context=>{
              const y0=context.p0.parsed.y??0;
              const y1=context.p1.parsed.y??0;
              return (y0+y1)/2>=0?"rgba(47,111,159,.28)":"rgba(192,82,61,.24)";
            }
          }
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        plugins:{
          title:{
            display:true,
            text:`Abweichung der Schneehöhe vom Median 1991–2020 · ${station.name}`
          },
          datalabels:{display:false},
          tooltip:{
            callbacks:{
              label:context=>{
                if(context.parsed.y===null || context.parsed.y===undefined) return null;
                const value=context.parsed.y;
                return `Abweichung: ${value>=0?"+":""}${stationSnowFormat(value)} cm`;
              }
            }
          },
          zoom:{
            pan:{enabled:true,mode:"x"},
            zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}
          }
        },
        scales:{
          x:{ticks:{maxTicksLimit:12,maxRotation:0}},
          y:{title:{display:true,text:"Abweichung (cm)"}}
        }
      }
    });

    const quality=profile.quality||{};
    const summary=current?.summary||null;
    const refYears=Number(quality.reference_years_available||0);
    const historyYears=Number(quality.accepted_history_years||0);
    const referenceStatus=stationSnowReferenceStatusLabel(quality.reference_status);

    document.getElementById("stationSnowReferenceStat").textContent=`${refYears}/30 Jahre`;
    document.getElementById("stationSnowReferenceDetail").textContent=
      `${referenceStatus} · nur hydrologische Jahre mit ≥ 98 % Tagesabdeckung`;

    document.getElementById("stationSnowHistoryStat").textContent=`${historyYears} Jahre`;
    document.getElementById("stationSnowHistoryDetail").textContent=
      quality.history_start_year && quality.history_end_year
        ?`Hydrologische Jahre ${quality.history_start_year}–${quality.history_end_year}`
        :"akzeptierte historische hydrologische Jahre";

    if(summary){
      document.getElementById("stationSnowLatestStat").textContent=
        `${stationSnowFormat(summary.last_value_cm)} cm`;
      document.getElementById("stationSnowLatestDetail").textContent=
        `am ${stationSnowGermanDate(summary.last_observation)} · Abweichung zum Median `+
        `${summary.last_anomaly_cm===null||summary.last_anomaly_cm===undefined?"–":`${Number(summary.last_anomaly_cm)>=0?"+":""}${stationSnowFormat(summary.last_anomaly_cm)} cm`}`;

      document.getElementById("stationSnowMaxStat").textContent=
        `${stationSnowFormat(summary.max_cm)} cm`;
      document.getElementById("stationSnowMaxDetail").textContent=
        summary.max_dates?.length
          ?`am ${summary.max_dates.slice(0,2).map(stationSnowGermanDate).join(", ")}${summary.max_dates.length>2?" …":""}`
          :"aktuelles hydrologisches Jahr";

      document.getElementById("stationSnowCoverDaysStat").textContent=
        `${Number(summary.snow_cover_days_observed?.["1"]||0).toLocaleString("de-DE")} Tage`;

      const stale=currentMeta?.last_observation && stationSnowCurrentIndex.data_through &&
        currentMeta.last_observation<stationSnowCurrentIndex.data_through;

      document.getElementById("stationSnowSummary").innerHTML=
        `<strong>${station.name} (${station.id})${height} · hydrologisches Jahr ${hydroYear}:</strong> `+
        `letzte gemeldete Schneehöhe ${stationSnowFormat(summary.last_value_cm)} cm am ${stationSnowGermanDate(summary.last_observation)}. `+
        `Saisonmaximum ${stationSnowFormat(summary.max_cm)} cm. `+
        `${stale?`Die Station meldet SHK_TAG derzeit nicht bis zum Netz-Datenstand ${stationSnowGermanDate(stationSnowCurrentIndex.data_through)}; die rote Kurve endet deshalb am letzten echten Messwert. `:""}`+
        `Referenzbasis: ${refYears}/30 Qualitätsjahre 1991–2020 (${referenceStatus}).`;
    }else{
      document.getElementById("stationSnowLatestStat").textContent="–";
      document.getElementById("stationSnowLatestDetail").textContent="keine SHK_TAG-Werte im hydrologischen Jahr";
      document.getElementById("stationSnowMaxStat").textContent="–";
      document.getElementById("stationSnowMaxDetail").textContent="keine aktuellen Saisonwerte";
      document.getElementById("stationSnowCoverDaysStat").textContent="–";
      document.getElementById("stationSnowSummary").innerHTML=
        `<strong>${station.name} (${station.id})${height}:</strong> `+
        `Für das hydrologische Jahr ${hydroYear} liegen derzeit keine SHK_TAG-Saisonwerte vor. `+
        `Die historische Klimatologie bleibt verfügbar. Referenzbasis: ${refYears}/30 Qualitätsjahre 1991–2020 (${referenceStatus}).`;
    }

  }catch(error){
    if(requestId!==stationSnowRequestId) return;
    document.getElementById("stationSnowSummary").textContent=
      `Schneehöhenprofil konnte nicht geladen werden: ${error.message}`;
  }
}

function resetStationSnowZoom(){
  if(stationSnowChart) stationSnowChart.resetZoom();
  if(stationSnowDeviationChart) stationSnowDeviationChart.resetZoom();
}
'''

VARIABLES = r'''
let stationSnowIndex=null;
let stationSnowCurrentIndex=null;
let stationSnowLoading=null;
let stationSnowProfile=null;
let stationSnowCurrent=null;
let stationSnowChart=null;
let stationSnowDeviationChart=null;
let stationSnowRequestId=0;
'''

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: erwartete genau 1 Fundstelle, gefunden {count}.")
    return text.replace(old, new, 1)


def patch_html(text: str) -> str:
    if MARKER in text:
        return text

    text = replace_once(
        text,
        '''  <button class="tab-button" onclick="switchTab('stationPrecip')">Stationsniederschlag</button>''',
        '''  <button class="tab-button" onclick="switchTab('stationPrecip')">Stationsniederschlag</button>
  <button class="tab-button" onclick="switchTab('stationSnow')">Schneehöhe</button>''',
        "Tab-Schaltfläche",
    )

    text = replace_once(
        text,
        '''<!-- ================= VERGLEICHE ================= -->''',
        SNOW_HTML + "\n<!-- ================= VERGLEICHE ================= -->",
        "Schneehöhen-HTML",
    )

    text = replace_once(
        text,
        '''const stationPrecipMonthCache=new Map();''',
        '''const stationPrecipMonthCache=new Map();
''' + VARIABLES.strip(),
        "Schneehöhen-Variablen",
    )

    text = replace_once(
        text,
        '''  if(tab==="stationPrecip") ensureStationPrecipLoaded();''',
        '''  if(tab==="stationPrecip") ensureStationPrecipLoaded();
  if(tab==="stationSnow") ensureStationSnowLoaded();''',
        "switchTab",
    )

    text = replace_once(
        text,
        '''stationPrecipChart,stationPrecipDeviationChart,stationClimateDaysCumulativeChart''',
        '''stationPrecipChart,stationPrecipDeviationChart,stationSnowChart,stationSnowDeviationChart,stationClimateDaysCumulativeChart''',
        "Chart-Resize",
    )

    text = replace_once(
        text,
        '''  "station_precip_current/",''',
        '''  "station_precip_current/",
  "station_snow_height_profiles/",
  "station_snow_height_current/",''',
        "Datenpfade",
    )

    text = replace_once(
        text,
        '''// ================= GRAFIK-EXPORT PNG / PDF =================''',
        SNOW_JS + "\n// ================= GRAFIK-EXPORT PNG / PDF =================",
        "Schneehöhen-JavaScript",
    )

    text = replace_once(
        text,
        '''  stationPrecipDeviationChart:"Stationsniederschlag - Abweichung",''',
        '''  stationPrecipDeviationChart:"Stationsniederschlag - Abweichung",
  stationSnowChart:"Stationsschneehöhe - hydrologisches Jahr",
  stationSnowDeviationChart:"Stationsschneehöhe - Abweichung",''',
        "Export-Titel",
    )

    return text


def validate_html(text: str) -> None:
    required = [
        MARKER,
        'id="stationSnow"',
        'id="stationSnowChart"',
        'id="stationSnowDeviationChart"',
        "function ensureStationSnowLoaded()",
        "function updateStationSnow()",
        "function resetStationSnowZoom()",
        '"station_snow_height_profiles/"',
        '"station_snow_height_current/"',
        'if(tab==="stationSnow") ensureStationSnowLoaded();',
    ]
    for token in required:
        if token not in text:
            raise RuntimeError(f"Validierung fehlgeschlagen: {token}")

    ids = [
        "stationSnow",
        "stationSnowLoading",
        "stationSnowContent",
        "stationSnowStateSelect",
        "stationSnowSearch",
        "stationSnowStationSelect",
        "stationSnowPeriodSelect",
        "stationSnowChart",
        "stationSnowDeviationChart",
    ]
    for item_id in ids:
        count = text.count(f'id="{item_id}"')
        if count != 1:
            raise RuntimeError(f"ID {item_id}: erwartet 1, gefunden {count}.")

    if text.count(MARKER) < 2:
        raise RuntimeError("Frontend-Marker wurde nicht vollständig eingesetzt.")


def check_inline_javascript(text: str) -> None:
    if shutil.which("node") is None:
        print("Hinweis: node nicht gefunden; JS-Syntaxprüfung übersprungen.")
        return

    scripts = re.findall(
        r"<script(?:\s[^>]*)?>(.*?)</script>",
        text,
        flags=re.I | re.S,
    )
    inline = "\n".join(script for script in scripts if script.strip())
    if not inline.strip():
        raise RuntimeError("Kein Inline-JavaScript für Syntaxprüfung gefunden.")

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".js",
        encoding="utf-8",
        delete=False,
    ) as handle:
        handle.write(inline)
        temp_name = handle.name

    try:
        proc = subprocess.run(
            ["node", "--check", temp_name],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "JavaScript-Syntaxprüfung fehlgeschlagen:\n"
                + proc.stdout
                + proc.stderr
            )
    finally:
        Path(temp_name).unlink(missing_ok=True)


def main() -> int:
    if not TARGET.exists():
        raise RuntimeError("index.html im Repository-Hauptverzeichnis fehlt.")

    original = TARGET.read_text(encoding="utf-8")

    if MARKER in original:
        print("Schneehöhen-Frontend ist bereits eingebaut; keine Änderung nötig.")
        validate_html(original)
        check_inline_javascript(original)
        return 0

    patched = patch_html(original)
    validate_html(patched)
    check_inline_javascript(patched)
    TARGET.write_text(patched, encoding="utf-8")

    print("DWD-Schneehöhenbereich erfolgreich in die aktuelle index.html eingebaut.")
    print("Enthalten:")
    print(" - eigener Reiter Schneehöhe")
    print(" - Bundesland / Suche / Station")
    print(" - Schneesaison oder vollständiges hydrologisches Jahr")
    print(" - aktuelle SHK_TAG-Kurve")
    print(" - Median 1991–2020")
    print(" - 16–84-%-Band")
    print(" - 2,5–97,5-%-Band")
    print(" - historisches Tagesmaximum")
    print(" - Abweichung zum Median")
    print(" - Statistik-Karten")
    print(" - Export-Integration")
    return 0


def self_test() -> None:
    fixture = r'''<!doctype html>
<html>
<body>
<div class="tabs">
  <button class="tab-button" onclick="switchTab('stationPrecip')">Stationsniederschlag</button>
</div>
<div id="stationPrecip"></div>
<!-- ================= VERGLEICHE ================= -->
<script>
let stationPrecipChart=null;
let stationPrecipDeviationChart=null;
let stationPrecipIndex=null;
const stationPrecipMonthCache=new Map();
function switchTab(tab){
  if(tab==="stationPrecip") ensureStationPrecipLoaded();
  [stationPrecipChart,stationPrecipDeviationChart,stationClimateDaysCumulativeChart].filter(Boolean).forEach(chart=>chart.resize());
}
const DASHBOARD_RAW_PREFIXES=[
  "station_precip_current/",
];
function dashboardFetch(a,b){return fetch(a,b);}
function ensureStationPrecipLoaded(){}
// ================= GRAFIK-EXPORT PNG / PDF =================
const CHART_EXPORT_FALLBACK_TITLES={
  stationPrecipDeviationChart:"Stationsniederschlag - Abweichung",
};
</script>
</body>
</html>'''

    patched = patch_html(fixture)
    validate_html(patched)

    assert "Schneehöhe</button>" in patched
    assert 'id="stationSnowChart"' in patched
    assert "Median 1991–2020" in patched
    assert "2,5–97,5 %" in patched
    assert "16–84 %" in patched
    assert "Historisches Maximum" in patched
    assert "Fehlwerte werden nicht als 0 cm gewertet" in patched
    assert 'if(tab==="stationSnow") ensureStationSnowLoaded();' in patched
    assert '"station_snow_height_profiles/"' in patched
    assert patch_html(patched) == patched

    print("DWD snow-height dashboard patch self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
