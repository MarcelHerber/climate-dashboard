#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMEAN_REGION_CURVES_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Tmean-Regionen-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Tmean-Regionen-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}")
    return new


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS Tmean Gebietskurven sind bereits eingebaut.")
        return 0
    if "// HYRAS_TMEAN_FRONTEND_V1" not in text:
        raise RuntimeError("HYRAS Tmean Frontend fehlt.")

    controls_old = '''      <select id="hyrasParameterSelect">
        <option value="precipitation">Niederschlag</option>
        <option value="tmean">2-m-Temperaturmittel</option>
      </select>
    </div>
    <div class="control-group">
      <label for="hyrasPeriodSelect">Zeitraum</label>'''
    controls_new = '''      <select id="hyrasParameterSelect">
        <option value="precipitation">Niederschlag</option>
        <option value="tmean">2-m-Temperaturmittel</option>
      </select>
    </div>
    <div id="hyrasTmeanRegionGroup" class="control-group" hidden>
      <label for="hyrasTmeanRegionSelect">Gebiet</label>
      <select id="hyrasTmeanRegionSelect"><option value="Deutschland">Deutschland</option></select>
    </div>
    <div class="control-group">
      <label for="hyrasPeriodSelect">Zeitraum</label>'''
    text = replace_once(text, controls_old, controls_new, "Gebietsauswahl")

    css = '''
/* HYRAS Tmean Gebietskurven */
.hyras-tmean-region-panel{background:#fff;border:1px solid #d8e0e5;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
.hyras-tmean-region-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap;margin-bottom:10px}
.hyras-tmean-region-head h3{margin:0 0 4px;font-size:21px}
.hyras-tmean-region-head p{margin:0;color:var(--muted);font-size:12px;line-height:1.45}
.hyras-tmean-chart-wrap{position:relative;height:470px}
.hyras-tmean-downloads{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0 4px}
.hyras-tmean-download{display:inline-flex;align-items:center;padding:9px 12px;border-radius:7px;background:#344a5e;color:#fff;text-decoration:none;font-size:12px;font-weight:800}
.hyras-tmean-download:hover{background:#263948}
.hyras-tmean-download.disabled{pointer-events:none;opacity:.42;background:#8a949c}
.hyras-tmean-region-note{margin:10px 0 0;color:var(--muted);font-size:11px;line-height:1.5}
@media(max-width:700px){.hyras-tmean-chart-wrap{height:390px}.hyras-tmean-download{width:100%;justify-content:center}}
'''
    text = text.replace("</style>", css + "\n</style>", 1)

    state_old = '''let hyrasTmeanExportObjectUrl=null;
let hyrasPointChart=null;'''
    state_new = '''let hyrasTmeanExportObjectUrl=null;
// HYRAS_TMEAN_REGION_CURVES_V1
let hyrasTmeanRegionsIndex=null;
let hyrasTmeanRegionsCurrent=null;
let hyrasTmeanRegionsClimate=null;
let hyrasTmeanMapDownloads=null;
let hyrasTmeanRegionChart=null;
let hyrasTmeanRegionsLoading=null;
let hyrasPointChart=null;'''
    text = replace_once(text, state_old, state_new, "Region-State")

    region_js = r'''
function hyrasTmeanRegionsBase(){return `${HYRAS_DATA_BASE}/tmean/regions`;}
async function hyrasTmeanRegionsFetch(path){
  const response=await fetch(`${hyrasTmeanRegionsBase()}/${path}?v=${encodeURIComponent(hyrasTmeanRegionsIndex?.data_through||"1")}`);
  if(!response.ok)throw new Error(`Tmean-Gebietsdaten ${path} fehlen (${response.status}).`);
  return response.json();
}
async function hyrasTmeanRegionsEnsureLoaded(){
  if(hyrasTmeanRegionsIndex&&hyrasTmeanRegionsCurrent&&hyrasTmeanRegionsClimate&&hyrasTmeanMapDownloads)return hyrasTmeanRegionsIndex;
  if(hyrasTmeanRegionsLoading)return hyrasTmeanRegionsLoading;
  hyrasTmeanRegionsLoading=(async()=>{
    hyrasTmeanRegionsIndex=await hyrasTmeanRegionsFetch("index.json");
    const [current,climate,maps]=await Promise.all([
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.current_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.climate_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.map_downloads_file),
    ]);
    hyrasTmeanRegionsCurrent=current;hyrasTmeanRegionsClimate=climate;hyrasTmeanMapDownloads=maps;
    return hyrasTmeanRegionsIndex;
  })().finally(()=>{hyrasTmeanRegionsLoading=null;});
  return hyrasTmeanRegionsLoading;
}
function hyrasTmeanPopulateRegions(){
  const select=document.getElementById("hyrasTmeanRegionSelect");if(!select||!hyrasTmeanRegionsIndex)return;
  const previous=select.value||"Deutschland";
  select.innerHTML=(hyrasTmeanRegionsIndex.regions||[]).map(name=>`<option value="${name.replace(/"/g,"&quot;")}">${name}</option>`).join("");
  select.value=(hyrasTmeanRegionsIndex.regions||[]).includes(previous)?previous:"Deutschland";
}
function hyrasTmeanPopulateCurvePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");if(!select||!hyrasTmeanRegionsIndex)return;
  const previous=select.value,periods=hyrasTmeanRegionsIndex.periods||[];
  select.innerHTML=periods.map(p=>`<option value="${p.key}">${p.label}</option>`).join("");
  const preferred=periods.find(p=>p.key==="summer")||periods[0];
  if(previous&&periods.some(p=>p.key===previous))select.value=previous;else if(preferred)select.value=preferred.key;
}
function hyrasTmeanCurvePeriod(){
  const key=document.getElementById("hyrasPeriodSelect")?.value;
  return (hyrasTmeanRegionsIndex?.periods||[]).find(p=>p.key===key)||(hyrasTmeanRegionsIndex?.periods||[])[0]||null;
}
function hyrasTmeanRegionName(){return document.getElementById("hyrasTmeanRegionSelect")?.value||"Deutschland";}
function hyrasTmeanCurveRows(region,period){
  const dates=hyrasTmeanRegionsCurrent?.dates||[],values=hyrasTmeanRegionsCurrent?.regions?.[region]||[],climate=hyrasTmeanRegionsClimate?.regions?.[region]||{};
  const rows=[];
  for(let i=0;i<dates.length;i++){
    const date=dates[i];if(date<period.start_date||date>period.end_date)continue;
    const current=Number(values[i]),normal=Number(climate[date.slice(5,10)]);
    rows.push({date,current:Number.isFinite(current)?current:null,normal:Number.isFinite(normal)?normal:null});
  }
  return rows;
}
function hyrasTmeanMeanOf(values){const valid=values.filter(Number.isFinite);return valid.length?valid.reduce((a,b)=>a+b,0)/valid.length:NaN;}
function hyrasTmeanFmt(value,unit="°C",signed=false){
  if(!Number.isFinite(value))return "–";const sign=signed&&value>0?"+":"";
  return `${sign}${value.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} ${unit}`;
}
function hyrasTmeanSetCurveKpis(region,period,rows){
  const current=hyrasTmeanMeanOf(rows.map(r=>r.current)),normal=hyrasTmeanMeanOf(rows.map(r=>r.normal)),anom=current-normal;
  const setHeading=(id,text)=>{const el=document.getElementById(id),h=el?.parentElement?.querySelector("h4");if(h)h.textContent=text;};
  document.getElementById("hyrasPeriodStat").textContent=period.label;
  document.getElementById("hyrasDataThrough").textContent=`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`;
  setHeading("hyrasCurrentMean",`Mittel ${hyrasTmeanRegionsIndex.year}`);document.getElementById("hyrasCurrentMean").textContent=hyrasTmeanFmt(current);document.getElementById("hyrasCurrentMeanDetail").textContent=region;
  setHeading("hyrasReferenceMean","Mittel 1991–2020");document.getElementById("hyrasReferenceMean").textContent=hyrasTmeanFmt(normal);document.getElementById("hyrasReferenceMeanDetail").textContent="exakt dieselben Kalendertage";
  setHeading("hyrasPercentMean","Abweichung");document.getElementById("hyrasPercentMean").textContent=hyrasTmeanFmt(anom,"K",true);
  setHeading("hyrasAnomalyMean","Datentage");document.getElementById("hyrasAnomalyMean").textContent=String(rows.filter(r=>Number.isFinite(r.current)).length);
  document.getElementById("hyrasReferenceNote").textContent=hyrasTmeanRegionsIndex.method_note||"HYRAS-Tmean-Gebietsmittel, Referenz 1991–2020.";
}
function hyrasTmeanDownloadHref(path){return path?`${HYRAS_DATA_BASE}/tmean/${path}`:"#";}
function hyrasTmeanRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");if(!frame)return;
  if(hyrasTmeanRegionChart){hyrasTmeanRegionChart.destroy();hyrasTmeanRegionChart=null;}
  const maps=hyrasTmeanMapDownloads?.periods?.[period.map_key]||{};
  const absClass=maps.absolute?"hyras-tmean-download":"hyras-tmean-download disabled";
  const anomClass=maps.anomaly?"hyras-tmean-download":"hyras-tmean-download disabled";
  frame.innerHTML=`<div class="hyras-tmean-region-panel">
    <div class="hyras-tmean-region-head"><div><h3>Temperaturmittel – ${region}</h3><p>${period.label} · tägliches HYRAS-Gebietsmittel gegen 1991–2020</p></div></div>
    <div class="hyras-tmean-chart-wrap"><canvas id="hyrasTmeanRegionCanvas"></canvas></div>
    <div class="hyras-tmean-downloads">
      <a class="${absClass}" ${maps.absolute?`href="${hyrasTmeanDownloadHref(maps.absolute)}" download`:""}>Temperaturkarte herunterladen</a>
      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" download`:""}>Abweichungskarte 1991–2020 herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">${maps.anomaly?"Absolute Temperatur- und Anomaliekarte stehen als fertige PNGs bereit.":"Für diesen laufenden Zeitraum ist die absolute Temperaturkarte als fertige PNG verfügbar; die Gebietskurve nutzt trotzdem bereits die tagesgenaue 1991–2020-Referenz."}</p>
  </div>`;
  const labels=rows.map(r=>{const [,m,d]=r.date.split("-");return `${d}.${m}.`;});
  const climate=rows.map(r=>r.normal),current=rows.map(r=>r.current);
  hyrasTmeanRegionChart=new Chart(document.getElementById("hyrasTmeanRegionCanvas"),{
    type:"line",
    data:{labels,datasets:[
      {label:"Mittel 1991–2020",data:climate,borderColor:"#666",borderWidth:2,pointRadius:0,tension:.08,spanGaps:false},
      {label:`${hyrasTmeanRegionsIndex.year}`,data:current,borderColor:"#111",borderWidth:2.4,pointRadius:0,tension:.08,spanGaps:false,fill:{target:0,above:"rgba(210,55,45,.28)",below:"rgba(55,115,190,.28)"}}
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:250},interaction:{mode:"index",intersect:false},
      plugins:{legend:{display:true},datalabels:{display:false},tooltip:{callbacks:{afterBody(items){if(!items?.length)return "";const i=items[0].dataIndex,a=current[i],b=climate[i];return Number.isFinite(a)&&Number.isFinite(b)?`Abweichung: ${(a-b)>=0?"+":""}${(a-b).toFixed(2).replace(".",",")} K`:"";}}}},
      scales:{x:{ticks:{maxTicksLimit:14}},y:{title:{display:true,text:"Temperatur (°C)"}}}
    }
  });
}
async function renderHyrasTmean(){
  try{
    await hyrasTmeanRegionsEnsureLoaded();const region=hyrasTmeanRegionName(),period=hyrasTmeanCurvePeriod();if(!period)return;
    const rows=hyrasTmeanCurveRows(region,period);hyrasTmeanSetCurveKpis(region,period,rows);hyrasTmeanRenderCurveChart(region,period,rows);
  }catch(error){console.error("HYRAS Tmean Gebietskurven:",error);const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;}
}
'''
    old_render = r'async function renderHyrasTmean\(\)\{.*?\n\}(?=\nasync function hyrasSwitchParameter\(\))'
    m = re.search(old_render, text, re.S)
    if not m:
        raise RuntimeError("Altes renderHyrasTmean nicht gefunden.")
    text = text[:m.start()] + region_js + "\n" + text[m.end():]

    switch_new = r'''async function hyrasSwitchParameter(){
  const isTmean=hyrasParameter()==="tmean";
  const custom=document.getElementById("hyrasCustomApply")?.parentElement;
  const historical=document.getElementById("hyrasHistoricalApply")?.parentElement;
  const panel=document.getElementById("hyrasPointAnalysis");
  const metricGroup=document.getElementById("hyrasMetricSelect")?.closest(".control-group");
  const regionGroup=document.getElementById("hyrasTmeanRegionGroup");
  if(panel)panel.hidden=true;
  hyrasHistoricalState=null;hyrasCustomState=null;hyrasPresetState=null;hyrasLivePresetState=null;
  if(isTmean){
    if(custom)custom.style.display="none";if(historical)historical.style.display="none";if(metricGroup)metricGroup.style.display="none";if(regionGroup)regionGroup.hidden=false;
    const oldLink=document.getElementById("hyrasOpenImage");if(oldLink)oldLink.style.display="none";
    const status=document.getElementById("hyrasStatus");if(status)status.textContent="HYRAS Tmean Gebietskurven werden geladen …";
    await hyrasTmeanRegionsEnsureLoaded();hyrasTmeanPopulateRegions();hyrasTmeanPopulateCurvePeriods();
    if(status)status.textContent=`Tmean · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmeanRegionsIndex.data_through)} · Referenz 1991–2020`;
    await renderHyrasTmean();
  }else{
    if(typeof hyrasTmeanResetExportLink==="function")hyrasTmeanResetExportLink();
    if(custom)custom.style.display="";if(historical)historical.style.display="";if(metricGroup)metricGroup.style.display="";if(regionGroup)regionGroup.hidden=true;
    hyrasRestorePrecipMetricOptions();populateHyrasPeriods();hyrasRestorePrecipHistoricalYears();
    const status=document.getElementById("hyrasStatus");if(status&&hyrasIndex)status.textContent=`Niederschlag · Daten bis ${hyrasDate(hyrasIndex.data_through)} · Historie ${hyrasIndex.historical_first_year}–${hyrasIndex.historical_last_year}`;
    renderHyras();
  }
}'''
    text = regex_once(text, r'async function hyrasSwitchParameter\(\)\{.*?\n\}(?=\nfunction renderHyras\(\))', switch_new, "Parameterwechsel")

    listener = '  document.getElementById("hyrasParameterSelect")?.addEventListener("change",()=>hyrasSwitchParameter());'
    text = replace_once(text, listener, listener + '\n  document.getElementById("hyrasTmeanRegionSelect")?.addEventListener("change",()=>renderHyrasTmean());', "Gebietslistener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean Gebietskurven V1 eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
