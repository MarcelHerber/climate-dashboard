#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


TARGETS = [
    Path("index.html"),
    Path("scripts/apply_station_calendar_frequency_feature.py"),
]

TEMP_CHART = '      <div style="height:420px"><canvas id="stationClimateDaysTemperatureFrequencyChart"></canvas></div>\n'
TEMP_EXPORT = '''      <div id="stationClimateDaysTemperatureFrequencyExportTools" style="display:flex;justify-content:flex-end;gap:7px;margin:0 0 8px">
        <button type="button" class="chart-export-button" title="Grafik als PNG herunterladen" onclick='runChartExport(this,document.getElementById("stationClimateDaysTemperatureFrequencyChart"),"png")'>PNG</button>
        <button type="button" class="chart-export-button" title="Grafik als PDF herunterladen" onclick='runChartExport(this,document.getElementById("stationClimateDaysTemperatureFrequencyChart"),"pdf")'>PDF</button>
        <button type="button" class="chart-export-button" title="Kalenderhäufigkeiten als CSV herunterladen" onclick='runStationClimateDaysFrequencyCsvExport(this,"temperature")'>CSV</button>
      </div>
''' + TEMP_CHART

SNOW_CHART = '      <div style="height:420px"><canvas id="stationClimateDaysSnowFrequencyChart"></canvas></div>\n'
SNOW_EXPORT = '''      <div id="stationClimateDaysSnowFrequencyExportTools" style="display:flex;justify-content:flex-end;gap:7px;margin:0 0 8px">
        <button type="button" class="chart-export-button" title="Grafik als PNG herunterladen" onclick='runChartExport(this,document.getElementById("stationClimateDaysSnowFrequencyChart"),"png")'>PNG</button>
        <button type="button" class="chart-export-button" title="Grafik als PDF herunterladen" onclick='runChartExport(this,document.getElementById("stationClimateDaysSnowFrequencyChart"),"pdf")'>PDF</button>
        <button type="button" class="chart-export-button" title="Kalenderhäufigkeiten als CSV herunterladen" onclick='runStationClimateDaysFrequencyCsvExport(this,"snow")'>CSV</button>
      </div>
''' + SNOW_CHART

JS_ANCHOR = 'function stationClimateDaysFrequencyChart(canvasId,existing,block,thresholds,colors,title){\n'
JS_EXPORT = r'''function stationClimateDaysFrequencyCsvRows(block,thresholds,unit){
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

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: erwartete genau 1 Fundstelle, gefunden: {count}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if 'id="stationClimateDaysTemperatureFrequencyExportTools"' not in text:
        text = replace_once(text, TEMP_CHART, TEMP_EXPORT, f"{path}: Temperatur-Export")

    if 'id="stationClimateDaysSnowFrequencyExportTools"' not in text:
        text = replace_once(text, SNOW_CHART, SNOW_EXPORT, f"{path}: Schnee-Export")

    if "function stationClimateDaysFrequencyCsvRows(" not in text:
        text = replace_once(text, JS_ANCHOR, JS_EXPORT + JS_ANCHOR, f"{path}: CSV-JavaScript")

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> int:
    for target in TARGETS:
        if not target.exists():
            raise RuntimeError(f"Datei fehlt: {target}")
        changed = patch(target)
        print(f"{target}: {'geändert' if changed else 'bereits aktuell'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
