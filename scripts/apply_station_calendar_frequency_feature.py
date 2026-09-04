#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


HTML_BLOCK = r'''

    <div class="chart-container auto">
      <div class="anomaly-table-heading">
        <div>
          <h2>Kalenderhäufigkeit · Temperatur</h2>
          <p>Wie häufig wurde am jeweiligen Kalendertag ein Tagesmaximum von mindestens 25, 30 oder 35 °C gemessen?</p>
        </div>
        <div class="control-group" style="min-width:170px">
          <label for="stationClimateDaysFrequencyMode">Darstellung</label>
          <select id="stationClimateDaysFrequencyMode" onchange="renderStationClimateDaysFrequency()">
            <option value="percent" selected>Prozent</option>
            <option value="count">Anzahl Jahre</option>
          </select>
        </div>
      </div>
      <div style="height:420px"><canvas id="stationClimateDaysTemperatureFrequencyChart"></canvas></div>
      <div class="table-wrap" style="margin-top:14px">
        <table id="stationClimateDaysTemperatureFrequencyRecords">
          <thead><tr><th>Schwelle</th><th>Frühester Termin</th><th>Spätester Termin</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <p id="stationClimateDaysTemperatureFrequencyNote" class="note"></p>
    </div>

    <div class="chart-container auto">
      <div class="anomaly-table-heading">
        <div>
          <h2>Kalenderhäufigkeit · Schneehöhe</h2>
          <p>Wie häufig lag am jeweiligen Kalendertag eine Schneedecke von mindestens 1, 5 oder 10 cm?</p>
        </div>
      </div>
      <div style="height:420px"><canvas id="stationClimateDaysSnowFrequencyChart"></canvas></div>
      <div class="table-wrap" style="margin-top:14px">
        <table id="stationClimateDaysSnowFrequencyRecords">
          <thead><tr><th>Schwelle</th><th>Früheste Schneedecke im 2. Halbjahr</th><th>Späteste Schneedecke im 1. Halbjahr</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <p id="stationClimateDaysSnowFrequencyNote" class="note">Schneehöhe = DWD SHK_TAG; dies beschreibt eine Schneedecke, nicht zwingend Neuschneefall.</p>
    </div>
'''


JS_BLOCK = r'''
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
  try{snow=await stationClimateDaysLoadSnowFrequency(station.id);}catch(_error){snow=null;}
  if(requestId!==stationClimateDaysFrequencyRequest) return;
  const snowBody=document.querySelector("#stationClimateDaysSnowFrequencyRecords tbody");
  const snowNote=document.getElementById("stationClimateDaysSnowFrequencyNote");
  if(snow){
    stationClimateDaysSnowFrequencyChart=stationClimateDaysFrequencyChart(
      "stationClimateDaysSnowFrequencyChart",
      stationClimateDaysSnowFrequencyChart,
      snow,
      [1,5,10],
      ["#8fc7e8","#4f8fc4","#24527a"],
      `Kalenderhäufigkeit Schneehöhe – ${station.name}`
    );
    if(snowBody){
      snowBody.innerHTML=[1,5,10].map(threshold=>{
        const record=snow.records?.[String(threshold)]||{};
        return `<tr><td><strong>≥ ${threshold} cm</strong></td><td>${stationClimateDaysFrequencyRecordText(record.earliest_second_half)}</td><td>${stationClimateDaysFrequencyRecordText(record.latest_first_half)}</td></tr>`;
      }).join("");
    }
    if(snowNote) snowNote.textContent="Je Kalendertag werden nur akzeptierte historische Schneehöhenjahre mit gültigem DWD-Wert SHK_TAG berücksichtigt. Angezeigt wird Schneedecke/Schneehöhe, nicht zwingend Neuschneefall.";
  }else{
    if(stationClimateDaysSnowFrequencyChart){stationClimateDaysSnowFrequencyChart.destroy();stationClimateDaysSnowFrequencyChart=null;}
    if(snowBody) snowBody.innerHTML='<tr><td colspan="3">Für diese Station sind noch keine Kalenderhäufigkeiten der Schneehöhe verfügbar.</td></tr>';
    if(snowNote) snowNote.textContent="Die Schneehöhen-Häufigkeiten werden beim nächsten Neuaufbau der historischen Schneehöhenprofile ergänzt.";
  }
  initializeChartExportButtons();
}

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: erwartete genau 1 Fundstelle, gefunden: {count}")
    return text.replace(old, new, 1)


def patch_climate_updater(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    import_line = "from station_calendar_frequency import build_calendar_frequency_payload\n"
    if import_line not in text:
        anchor = "from dwd_common import atomic_write_json, download, read_json\n"
        text = replace_once(text, anchor, anchor + import_line, "Kalenderhäufigkeit-Import")

    if "STATE_VERSION = 10" in text:
        text = text.replace("STATE_VERSION = 10", "STATE_VERSION = 11", 1)
    elif "STATE_VERSION = 11" not in text:
        raise RuntimeError("Unerwartete STATE_VERSION bei Stations-Kenntagen.")

    calculation = '''    tx_by_day: dict[date, float] = {}\n    for observation in observations:\n        if observation.day.year >= current_year:\n            continue\n        tx, _tn = observation_temperatures(observation)\n        if tx is not None:\n            tx_by_day[observation.day] = float(tx)\n    calendar_temperature_frequency = build_calendar_frequency_payload(tx_by_day, {})["temperature"]\n'''
    if "calendar_temperature_frequency = build_calendar_frequency_payload" not in text:
        anchor = "    cold_payload = build_cold_sum_payload(tmean_by_day or {}, current_year)\n"
        text = replace_once(text, anchor, anchor + calculation, "Berechnung Kalenderhäufigkeit")

    if '"calendar_frequency": {"temperature": calendar_temperature_frequency},' not in text:
        anchor = '''        "temperature_sums": {\n            "gts": gts_payload,\n            "warmth": warmth_payload,\n            "cold": cold_payload,\n        },\n'''
        replacement = anchor + '        "calendar_frequency": {"temperature": calendar_temperature_frequency},\n'
        text = replace_once(text, anchor, replacement, "Profil-Payload Kalenderhäufigkeit")

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def patch_snow_builder(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    import_line = "from station_calendar_frequency import build_calendar_frequency_payload\n"
    if import_line not in text:
        anchor = "from typing import Any\n"
        text = replace_once(text, anchor, anchor + "\n" + import_line, "Schnee-Import Kalenderhäufigkeit")

    if "PROFILE_VERSION = 1" in text:
        text = text.replace("PROFILE_VERSION = 1", "PROFILE_VERSION = 2", 1)
    elif "PROFILE_VERSION = 2" not in text:
        raise RuntimeError("Unerwartete PROFILE_VERSION bei Schneehöhenprofilen.")

    calculation = '''    snow_by_day: dict[date, float] = {}\n    for values in accepted.values():\n        snow_by_day.update(values)\n    calendar_frequency = build_calendar_frequency_payload({}, snow_by_day)["snow"]\n\n'''
    if "calendar_frequency = build_calendar_frequency_payload({}, snow_by_day)" not in text:
        anchor = "    climatology, reference_year_count = build_daily_climatology(accepted)\n\n"
        text = replace_once(text, anchor, anchor + calculation, "Schnee-Berechnung Kalenderhäufigkeit")

    if '"calendar_frequency": calendar_frequency,' not in text:
        anchor = '        "annual": annual,\n'
        text = replace_once(text, anchor, anchor + '        "calendar_frequency": calendar_frequency,\n', "Schnee-Profil-Payload")

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def patch_index(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if 'id="stationClimateDaysTemperatureFrequencyChart"' not in text:
        anchor = '''    <div class="chart-container">\n      <canvas id="stationClimateDaysCumulativeChart"></canvas>\n    </div>\n'''
        text = replace_once(text, anchor, anchor + HTML_BLOCK, "Kenntage-HTML nach kumulativem Verlauf")

    variable_anchor = "let stationClimateDaysCumulativeChart=null;\nlet stationClimateDaysBarChart=null;\n"
    if "let stationClimateDaysTemperatureFrequencyChart=null;" not in text:
        variable_replacement = (
            "let stationClimateDaysCumulativeChart=null;\n"
            "let stationClimateDaysBarChart=null;\n"
            "let stationClimateDaysTemperatureFrequencyChart=null;\n"
            "let stationClimateDaysSnowFrequencyChart=null;\n"
            "let stationClimateDaysSnowFrequencyIndex=null;\n"
            "const stationClimateDaysSnowFrequencyProfileCache=new Map();\n"
            "let stationClimateDaysFrequencyRequest=0;\n"
        )
        text = replace_once(text, variable_anchor, variable_replacement, "Kenntage-Chartvariablen")

    if "function stationClimateDaysFrequencyMode()" not in text:
        anchor = "async function updateStationClimateDays(){\n"
        text = replace_once(text, anchor, JS_BLOCK + anchor, "Kenntage-JS vor updateStationClimateDays")

    call = "    renderStationClimateDaysFrequency(station);\n"
    if call not in text:
        anchor = "    stationClimateDaysProfile=await profileResponse.json();\n"
        text = replace_once(text, anchor, anchor + call, "Kenntage-Aufruf Kalenderhäufigkeit")

    old_reset = '''function resetStationClimateDaysZoom(){\n  if(stationClimateDaysCumulativeChart) stationClimateDaysCumulativeChart.resetZoom();\n  if(stationClimateDaysBarChart) stationClimateDaysBarChart.resetZoom();\n}\n'''
    new_reset = '''function resetStationClimateDaysZoom(){\n  if(stationClimateDaysCumulativeChart) stationClimateDaysCumulativeChart.resetZoom();\n  if(stationClimateDaysBarChart) stationClimateDaysBarChart.resetZoom();\n  if(stationClimateDaysTemperatureFrequencyChart) stationClimateDaysTemperatureFrequencyChart.resetZoom();\n  if(stationClimateDaysSnowFrequencyChart) stationClimateDaysSnowFrequencyChart.resetZoom();\n}\n'''
    if "stationClimateDaysTemperatureFrequencyChart.resetZoom" not in text:
        text = replace_once(text, old_reset, new_reset, "Kenntage-Zoom")

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> int:
    root = Path.cwd()
    climate_script = root / "scripts" / "update_station_climate_days.py"
    snow_script = root / "scripts" / "build_dwd_snow_height_profiles.py"
    index_path = root / "index.html"
    for path in (climate_script, snow_script, index_path):
        if not path.exists():
            raise RuntimeError(f"Datei fehlt: {path}")

    changed_climate = patch_climate_updater(climate_script)
    changed_snow = patch_snow_builder(snow_script)
    changed_index = patch_index(index_path)

    root_updater = root / "update_station_climate_days.py"
    if changed_climate or root_updater.read_text(encoding="utf-8") != climate_script.read_text(encoding="utf-8"):
        shutil.copyfile(climate_script, root_updater)

    print("Stations-Kalenderhäufigkeiten:")
    print(f"  Kenntage-Backend: {'geändert' if changed_climate else 'bereits aktuell'}")
    print(f"  Schneehöhen-Backend: {'geändert' if changed_snow else 'bereits aktuell'}")
    print(f"  Frontend: {'geändert' if changed_index else 'bereits aktuell'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
