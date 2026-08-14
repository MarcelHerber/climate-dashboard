#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMEAN_DAILY_RECORDS_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmean-Rekordkurven-Patch fehlgeschlagen "
            f"({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        print("HYRAS Tmean historische Tagesrekorde sind bereits im Frontend.")
        return 0

    if "// HYRAS_TMEAN_REGION_CURVES_V1" not in text:
        raise RuntimeError("HYRAS Tmean Gebietskurven fehlen im Frontend.")

    old_state = '''let hyrasTmeanRegionsClimate=null;
let hyrasTmeanMapDownloads=null;
let hyrasTmeanRegionChart=null;'''
    new_state = '''let hyrasTmeanRegionsClimate=null;
let hyrasTmeanMapDownloads=null;
// HYRAS_TMEAN_DAILY_RECORDS_V1
let hyrasTmeanRegionsRecords=null;
let hyrasTmeanRegionChart=null;'''
    text = replace_once(text, old_state, new_state, "Rekord-State")

    old_guard = '''if(hyrasTmeanRegionsIndex&&hyrasTmeanRegionsCurrent&&hyrasTmeanRegionsClimate&&hyrasTmeanMapDownloads)return hyrasTmeanRegionsIndex;'''
    new_guard = '''if(hyrasTmeanRegionsIndex&&hyrasTmeanRegionsCurrent&&hyrasTmeanRegionsClimate&&hyrasTmeanMapDownloads&&hyrasTmeanRegionsRecords)return hyrasTmeanRegionsIndex;'''
    text = replace_once(text, old_guard, new_guard, "Load-Guard")

    old_fetch = '''const [current,climate,maps]=await Promise.all([
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.current_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.climate_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.map_downloads_file),
    ]);
    hyrasTmeanRegionsCurrent=current;hyrasTmeanRegionsClimate=climate;hyrasTmeanMapDownloads=maps;'''
    new_fetch = '''const [current,climate,maps,records]=await Promise.all([
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.current_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.climate_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.map_downloads_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.records_file),
    ]);
    hyrasTmeanRegionsCurrent=current;hyrasTmeanRegionsClimate=climate;hyrasTmeanMapDownloads=maps;hyrasTmeanRegionsRecords=records;'''
    text = replace_once(text, old_fetch, new_fetch, "Rekorddatei laden")

    old_rows = '''function hyrasTmeanCurveRows(region,period){
  const dates=hyrasTmeanRegionsCurrent?.dates||[],values=hyrasTmeanRegionsCurrent?.regions?.[region]||[],climate=hyrasTmeanRegionsClimate?.regions?.[region]||{};
  const rows=[];
  for(let i=0;i<dates.length;i++){
    const date=dates[i];if(date<period.start_date||date>period.end_date)continue;
    const current=Number(values[i]),normal=Number(climate[date.slice(5,10)]);
    rows.push({date,current:Number.isFinite(current)?current:null,normal:Number.isFinite(normal)?normal:null});
  }
  return rows;
}'''
    new_rows = '''function hyrasTmeanCurveRows(region,period){
  const dates=hyrasTmeanRegionsCurrent?.dates||[],values=hyrasTmeanRegionsCurrent?.regions?.[region]||[],climate=hyrasTmeanRegionsClimate?.regions?.[region]||{},records=hyrasTmeanRegionsRecords?.regions?.[region]||{};
  const rows=[];
  for(let i=0;i<dates.length;i++){
    const date=dates[i];if(date<period.start_date||date>period.end_date)continue;
    const mmdd=date.slice(5,10),current=Number(values[i]),normal=Number(climate[mmdd]),record=records[mmdd]||{};
    const recordMax=record.max===null||record.max===undefined?null:Number(record.max),recordMin=record.min===null||record.min===undefined?null:Number(record.min);
    rows.push({date,current:Number.isFinite(current)?current:null,normal:Number.isFinite(normal)?normal:null,recordMax:Number.isFinite(recordMax)?recordMax:null,recordMin:Number.isFinite(recordMin)?recordMin:null,recordMaxYears:Array.isArray(record.max_years)?record.max_years:[],recordMinYears:Array.isArray(record.min_years)?record.min_years:[]});
  }
  return rows;
}'''
    text = replace_once(text, old_rows, new_rows, "Rekordwerte pro Tag")

    old_arrays = '''const climate=rows.map(r=>r.normal),current=rows.map(r=>r.current);
  hyrasTmeanRegionChart=new Chart(document.getElementById("hyrasTmeanRegionCanvas"),{'''
    new_arrays = '''const climate=rows.map(r=>r.normal),current=rows.map(r=>r.current),recordMax=rows.map(r=>r.recordMax),recordMin=rows.map(r=>r.recordMin);
  const recordFirst=Number(hyrasTmeanRegionsIndex.records_first_year||hyrasTmeanRegionsRecords?.first_year||1951),recordLast=Number(hyrasTmeanRegionsIndex.records_last_year||hyrasTmeanRegionsRecords?.last_year||2025);
  hyrasTmeanRegionChart=new Chart(document.getElementById("hyrasTmeanRegionCanvas"),{'''
    text = replace_once(text, old_arrays, new_arrays, "Rekordarrays")

    old_datasets = '''data:{labels,datasets:[
      {label:"Mittel 1991–2020",data:climate,borderColor:"#666",borderWidth:2,pointRadius:0,tension:.08,spanGaps:false},
      {label:`${hyrasTmeanRegionsIndex.year}`,data:current,borderColor:"#111",borderWidth:2.4,pointRadius:0,tension:.08,spanGaps:false,fill:{target:0,above:"rgba(210,55,45,.28)",below:"rgba(55,115,190,.28)"}}
    ]},'''
    new_datasets = '''data:{labels,datasets:[
      {label:"Mittel 1991–2020",data:climate,borderColor:"#666",borderWidth:2,pointRadius:0,tension:.08,spanGaps:false},
      {label:`${hyrasTmeanRegionsIndex.year}`,data:current,borderColor:"#111",borderWidth:2.4,pointRadius:0,tension:.08,spanGaps:false,fill:{target:0,above:"rgba(210,55,45,.28)",below:"rgba(55,115,190,.28)"}},
      {label:`Historisches Maximum ${recordFirst}–${recordLast}`,data:recordMax,borderColor:"#b42318",backgroundColor:"transparent",borderWidth:1.5,borderDash:[6,4],pointRadius:0,tension:.04,spanGaps:false},
      {label:`Historisches Minimum ${recordFirst}–${recordLast}`,data:recordMin,borderColor:"#1f5f99",backgroundColor:"transparent",borderWidth:1.5,borderDash:[6,4],pointRadius:0,tension:.04,spanGaps:false}
    ]},'''
    text = replace_once(text, old_datasets, new_datasets, "Rekordlinien")

    old_tooltip = '''plugins:{legend:{display:true},datalabels:{display:false},tooltip:{callbacks:{afterBody(items){if(!items?.length)return "";const i=items[0].dataIndex,a=current[i],b=climate[i];return Number.isFinite(a)&&Number.isFinite(b)?`Abweichung: ${(a-b)>=0?"+":""}${(a-b).toFixed(2).replace(".",",")} K`:"";}}}},'''
    new_tooltip = '''plugins:{legend:{display:true},datalabels:{display:false},tooltip:{filter:item=>item.datasetIndex<2,callbacks:{afterBody(items){
        if(!items?.length)return "";
        const i=items[0].dataIndex,a=current[i],b=climate[i],row=rows[i]||{},lines=[];
        if(Number.isFinite(a)&&Number.isFinite(b))lines.push(`Abweichung: ${(a-b)>=0?"+":""}${(a-b).toFixed(2).replace(".",",")} K`);
        if(Number.isFinite(row.recordMax))lines.push(`Historisches Maximum: ${row.recordMax.toFixed(2).replace(".",",")} °C (${(row.recordMaxYears||[]).join(", ")})`);
        if(Number.isFinite(row.recordMin))lines.push(`Historisches Minimum: ${row.recordMin.toFixed(2).replace(".",",")} °C (${(row.recordMinYears||[]).join(", ")})`);
        return lines;
      }}}},'''
    text = replace_once(text, old_tooltip, new_tooltip, "Rekord-Tooltip")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean historische Tagesrekorde V1 eingebaut:")
    print("- historische Maximal-Linie")
    print("- historische Minimal-Linie")
    print("- Rekordjahr(e) im Tooltip")
    print("- 2026/1991–2020 und rot-blaue Abweichungsflächen bleiben erhalten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
