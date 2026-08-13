#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MARKER = "// ERA5_TP_ALL_MONTHS_FRONTEND_V1"


def replace_once(text: str, pattern: str, replacement: str, *, flags: int = 0, label: str) -> str:
    new, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Frontend-Patch fehlgeschlagen ({label}): Treffer={count}")
    return new


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    if MARKER in text:
        print("ERA5 T/P-Monatsfrontend ist bereits eingebaut.")
        return 0

    helpers = r'''
// ERA5_TP_ALL_MONTHS_FRONTEND_V1
function era5EuropeUpdatePeriodOptions(){
  const select=document.getElementById("era5EuropePeriod");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const previous=select.value||"latest_month";
  const latest=era5EuropeIndex?.periods?.latest_month;
  const summer=era5EuropeIndex?.periods?.summer;
  let html='<optgroup label="Aktuell / Saison">'+
    `<option value="latest_month">${latest?.label||"Jüngster vollständiger Monat"}</option>`+
    `<option value="summer">${summer?.label||"Sommer (JJA)"}</option>`+
    '</optgroup>';
  const monthNumbers=(era5EuropeIndex?.history_map?.temperature_precipitation_months||[]).map(Number).filter(m=>m>=1&&m<=12);
  if((parameter==="temperature"||parameter==="precipitation")&&monthNumbers.length){
    const options=monthNumbers.map(month=>{const id=`month_${String(month).padStart(2,"0")}`,p=era5EuropeIndex?.periods?.[id];return `<option value="${id}">${p?.label||id}</option>`;}).join("");
    html+=`<optgroup label="Historisches Monatsarchiv 1950–${era5EuropeIndex?.history_map?.year_end||""}">${options}</optgroup>`;
  }
  select.innerHTML=html;
  if([...select.options].some(o=>o.value===previous))select.value=previous;else select.value="latest_month";
}
function era5EuropePeriodIsHistoricalOnly(periodId){return Boolean(era5EuropeIndex?.periods?.[periodId]?.historical_only);}
function era5EuropeHighresSampleEntries(field,maxSamples=40000){
  const values=field?.values||[];if(!values.length)return [];
  const step=Math.max(1,Math.floor(values.length/maxSamples)),rows=[];
  for(let i=0;i<values.length;i+=step){const value=Number(values[i]);if(Number.isFinite(value))rows.push({value});}
  return rows;
}
function era5EuropeHighresWeightedMean(field){
  if(!field?.values||!field.nlat||!field.nlon)return null;
  let sum=0,weights=0;const nlat=Number(field.nlat),nlon=Number(field.nlon),latStart=Number(field.latStart),latStep=Number(field.latStep);
  for(let y=0;y<nlat;y++){
    const lat=latStart+y*latStep,w=Math.max(.01,Math.cos(lat*Math.PI/180)),row=y*nlon;
    for(let x=0;x<nlon;x++){const value=Number(field.values[row+x]);if(Number.isFinite(value)){sum+=value*w;weights+=w;}}
  }
  return weights?sum/weights:null;
}
function era5EuropeShowMonthlyRankingPending(meta,period,year){
  const panel=document.getElementById("era5EuropeRanking");if(!panel)return;
  document.getElementById("era5EuropeRankingTitle").textContent=`${meta.label} · ${period?.label||"Monat"} ${year}`;
  document.getElementById("era5EuropeRankingSubtitle").textContent="0,1°-Monatskarte verfügbar · 1,0°-Rankings und Gitterpunkt-Zeitreihen werden in einer späteren Stufe ergänzt.";
  for(const id of ["era5EuropeRankingMax","era5EuropeRankingMin","era5EuropeRankingHighRecords","era5EuropeRankingLowRecords","era5EuropeRankingMaxDetail","era5EuropeRankingMinDetail"]){const el=document.getElementById(id);if(el)el.textContent="–";}
  const top=document.getElementById("era5EuropeRankingTop"),bottom=document.getElementById("era5EuropeRankingBottom");
  if(top)top.innerHTML='<div class="era5-europe-loading">Für das neue Monatsarchiv ist in dieser Stufe zunächst nur die hochaufgelöste Karte aktiv.</div>';
  if(bottom)bottom.innerHTML='';
  const foot=document.getElementById("era5EuropeRankingFoot");if(foot)foot.textContent="Temperatur und Niederschlag sind bereits vollständig als Monatskarten vorhanden; Rankings werden separat nachgezogen.";
  era5EuropeRankingPoints=[];era5EuropeRenderRankingMarkers();clearEra5EuropePoint();
}
'''
    text = replace_once(
        text,
        r'function era5EuropeUpdateMapYearOptions\(\)\{',
        helpers + '\nfunction era5EuropeUpdateMapYearOptions(){',
        label="Hilfsfunktionen"
    )

    new_year_function = r'''function era5EuropeUpdateMapYearOptions(){
  const select=document.getElementById("era5EuropeMapYear");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  const period=era5EuropeIndex?.periods?.[periodId]||{};
  const historicalOnly=Boolean(period.historical_only);
  const previous=select.value||"current";
  const currentYear=Number(period.year||era5EuropeIndex?.history_map?.year_end||new Date().getFullYear());
  const start=parameter==="soil_moisture"?Number(era5EuropeIndex?.history_map?.soil_year_start||1991):Number(era5EuropeIndex?.history_map?.year_start||1950);
  const end=parameter==="soil_moisture"?Number(era5EuropeIndex?.history_map?.soil_year_end||2020):Number(era5EuropeIndex?.history_map?.year_end||currentYear-1);
  const years=[];for(let y=end;y>=start;y--)years.push(y);
  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+
    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  else select.value=historicalOnly?String(end):"current";
}
function era5EuropeMapYear'''
    text = replace_once(
        text,
        r'function era5EuropeUpdateMapYearOptions\(\)\{.*?\n\}\nfunction era5EuropeMapYear',
        new_year_function,
        flags=re.S,
        label="Kartenjahre"
    )

    new_historical = r'''async function renderEra5EuropeHistorical(){
  const wrap=document.getElementById("era5EuropeImageWrap");if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Historische Karte wird aus dem echten 0,1°-ERA5-Land-Archiv aufgebaut …</div>';
  try{await ensureEra5EuropeHighresArchiveLoaded();}catch(error){if(wrap)wrap.innerHTML=`<div class="era5-europe-loading">Historisches 0,1°-Kartenarchiv konnte nicht geladen werden: ${error.message}</div>`;return;}
  let analysisReady=false;try{await ensureEra5EuropeAnalysisLoaded();analysisReady=true;}catch(error){console.warn("ERA5 1°-Analyse für diese Monatskarte nicht erforderlich:",error);}
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature",layer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1",periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month",view=document.getElementById("era5EuropeView")?.value||"absolute",year=era5EuropeMapYear();if(!Number.isFinite(year))return;
  const period=era5EuropeIndex?.periods?.[periodId],meta=era5EuropeMetricMeta(parameter,layer);
  if(period?.historical_only&&!["temperature","precipitation"].includes(parameter)){if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Das neue Monatsarchiv ist in dieser Stufe nur für Temperatur und Niederschlag verfügbar.</div>';return;}
  let rows=analysisReady?era5EuropeHistoricalField(parameter,layer,periodId,year,view):[];era5EuropeHistoricalEntries=rows;
  try{era5EuropeHistoricalRaster=await era5EuropeHighresViewField(parameter,layer,periodId,year,view);}catch(error){console.error(error);if(wrap)wrap.innerHTML=`<div class="era5-europe-loading">Die historische 0,1°-Karte ist noch nicht aufgebaut: ${error.message}<br>Bitte den Workflow „ERA5-Land Europa aktualisieren“ einmal mit force = false ausführen.</div>`;return;}
  era5EuropeHistoricalScale=era5EuropeHistoryScaleFor(rows.length?rows:era5EuropeHighresSampleEntries(era5EuropeHistoricalRaster),parameter,view);
  const rawRaster=await era5EuropeHighresCombinedRaw(parameter,layer,periodId,year);
  const referenceRaster=await era5EuropeHighresReference(parameter,layer,periodId);
  const rawMean=era5EuropeHighresWeightedMean(rawRaster),refMean=era5EuropeHighresWeightedMean(referenceRaster);
  const base=`${ERA5_EUROPE_RAW_BASE}${era5EuropeIndex?.history_map?.base_file||"era5_land_europe/maps/historical_base.png"}?v=${encodeURIComponent(era5EuropeIndex.generated_at||Date.now())}`;
  const minLabel=era5EuropeHistoryLegendLabel(era5EuropeHistoricalScale.min,meta,view),maxLabel=era5EuropeHistoryLegendLabel(era5EuropeHistoricalScale.max,meta,view),clickable=rows.length>0;
  if(wrap)wrap.innerHTML=`<div id="era5EuropeImageStage" class="era5-europe-image-stage"><img id="era5EuropeImage" class="era5-europe-image" crossorigin="anonymous" alt="Historische ERA5-Land-Karte ${year}" src="${base}"><canvas id="era5EuropeHistoryCanvas" class="era5-europe-history-canvas"></canvas><div id="era5EuropePointMarker" class="era5-europe-point-marker"></div><div class="era5-europe-history-badge">Historisches Kartenarchiv<br>${year} · 0,1° ERA5-Land</div><div class="era5-europe-click-hint">${clickable?'Karte anklicken<br>→ Gitterpunktanalyse':'Monatsarchiv<br>0,1° ERA5-Land'}</div><div class="era5-europe-history-legend"><span>${minLabel}</span><div class="era5-europe-history-gradient" style="background:${era5EuropeHistoricalScale.gradient}"></div><span>${maxLabel}</span></div></div>`;
  const stage=document.getElementById("era5EuropeImageStage"),img=document.getElementById("era5EuropeImage");if(clickable)stage?.addEventListener("click",era5EuropeHandleMapClick);img?.addEventListener("load",()=>{era5EuropeDrawHistoricalCanvas();if(clickable)era5EuropePlaceMarker();});img?.addEventListener("error",()=>{if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Die historische Basiskarte konnte nicht geladen werden.</div>';});
  document.getElementById("era5EuropeMapTitle").textContent=`${meta.label} · ${year} · ${period?.label||year}`;document.getElementById("era5EuropeMapSubtitle").textContent=`Historische 0,1°-ERA5-Land-Karte · ${document.getElementById("era5EuropeView")?.selectedOptions?.[0]?.textContent||view}${clickable?' · Rankings/KPIs separat auf 1,0°':' · Monatsarchiv'}`;
  document.getElementById("era5EuropePeriodKpi").textContent=`${year} · ${period?.label||periodId}`;document.getElementById("era5EuropeDataKpi").textContent="Historisches Archiv · sichtbares Raster 0,1°";
  const diffLabel=document.getElementById("era5EuropeDifferenceLabel");document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(rawMean,meta.decimals,` ${meta.unit}`);document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(refMean,meta.decimals,` ${meta.unit}`);
  if(parameter==="precipitation"){if(diffLabel)diffLabel.textContent="Vom Mittel";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(Number.isFinite(rawMean)&&Number.isFinite(refMean)&&refMean!==0?rawMean/refMean*100:null,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`Niederschlag ${year} gegenüber 1991–2020`;}
  else{if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(Number.isFinite(rawMean)&&Number.isFinite(refMean)?rawMean-refMean:null,meta.decimals,` ${parameter==="temperature"?"K":meta.diffUnit||meta.unit}`);document.getElementById("era5EuropeDifferenceDetail").textContent=`${year} gegenüber 1991–2020`;}
  const source=document.getElementById("era5EuropeSource");if(source)source.textContent=`Quelle: ${era5EuropeIndex.source}. ${era5EuropeIndex.history_map?.note||"Historische sichtbare Karte auf 0,1°."} ${era5EuropeIndex.history_map?.tp_all_months_note||""}`.trim();
  if(clickable){if(era5EuropeSelectedPoint)renderEra5EuropePointAnalysis();renderEra5EuropeRankings();}else era5EuropeShowMonthlyRankingPending(meta,period,year);
}
async function ensureEra5EuropeLoaded'''
    text = replace_once(
        text,
        r'async function renderEra5EuropeHistorical\(\)\{.*?\n\}\nasync function ensureEra5EuropeLoaded',
        new_historical,
        flags=re.S,
        label="historische Monatsdarstellung"
    )

    text = text.replace(
        '    era5EuropeUpdateMapYearOptions();\n    renderEra5Europe();',
        '    era5EuropeUpdatePeriodOptions();\n    era5EuropeUpdateMapYearOptions();\n    renderEra5Europe();',
        1,
    )
    old_handler = 'parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdateMapYearOptions();renderEra5Europe();});'
    new_handler = 'parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdatePeriodOptions();era5EuropeUpdateMapYearOptions();renderEra5Europe();});'
    if old_handler not in text:
        raise RuntimeError("Frontend-Patch fehlgeschlagen: Parameter-Handler nicht gefunden.")
    text = text.replace(old_handler, new_handler, 1)

    text = text.replace(
        '<span class="section-status">Version 8.1 · Europa-Rankings &amp; Extreme · Historische Karten seit 1950 · Aktuell 0,1° · Analyse 1,0° · Copernicus C3S / ECMWF</span>',
        '<span class="section-status">Version 9.0 · Temperatur &amp; Niederschlag monatlich Jan–Dez seit 1950 · Aktuell 0,1° · Analyse 1,0° · Copernicus C3S / ECMWF</span>',
        1,
    )
    text = text.replace(
        '<div><strong>V8.1 · historische Karten jetzt 0,1°:</strong><br>Auch gewählte historische Jahre werden sichtbar auf dem echten ERA5-Land-0,1°-Raster dargestellt. Das frühere grobe 1°-Kartenraster wird nicht mehr angezeigt.</div>',
        '<div><strong>V9.0 · Temperatur &amp; Niederschlag für alle Monate:</strong><br>Historische Monatskarten Januar bis Dezember werden auf dem echten ERA5-Land-0,1°-Raster dargestellt. Bodenfeuchte, Wasserhaushalt und Schnee folgen schrittweise.</div>',
        1,
    )

    INDEX.write_text(text, encoding="utf-8")
    print("ERA5 T/P-Monatsfrontend erfolgreich in index.html ergänzt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
