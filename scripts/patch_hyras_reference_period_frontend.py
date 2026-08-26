#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_REFERENCE_PERIOD_SELECTOR_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Referenz-Patch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS-Referenzauswahl ist bereits eingebaut.")
        return 0

    metric_group = '''    <div class="control-group">
      <label for="hyrasMetricSelect">Darstellung</label>
      <select id="hyrasMetricSelect">'''
    reference_group = '''    <div class="control-group" id="hyrasReferenceGroup">
      <label for="hyrasReferenceSelect">Referenzmittel</label>
      <select id="hyrasReferenceSelect">
        <option value="1991-2020">1991–2020</option>
        <option value="1961-1990">1961–1990</option>
      </select>
    </div>
    <div class="control-group">
      <label for="hyrasMetricSelect">Darstellung</label>
      <select id="hyrasMetricSelect">'''
    text = replace_once(text, metric_group, reference_group, "Referenz-Auswahl")

    helper_anchor = 'function hyrasMetricConfig(metric){'
    helper = r'''// HYRAS_REFERENCE_PERIOD_SELECTOR_V1
function hyrasReferencePeriod(){return document.getElementById("hyrasReferenceSelect")?.value||"1991-2020";}
function hyrasReferenceDisplay(){return hyrasReferencePeriod().replace("-","–");}
function hyrasReferenceYears(){const parts=hyrasReferencePeriod().split("-").map(Number);return {start:parts[0]||1991,end:parts[1]||2020};}
function hyrasReferenceSlug(){return hyrasReferencePeriod().replace("-","_");}
function hyrasReferenceFiles(manifest){
  const ref=hyrasReferencePeriod();
  return manifest?.reference_files_by_period?.[ref]||manifest?.reference_files||{};
}
'''
    text = replace_once(text, helper_anchor, helper + helper_anchor, "Referenz-Helfer")

    text = text.replace(
        'return {key:"percent",label:"Prozent des Mittels 1991–2020"};',
        'return {key:"percent",label:`Prozent des Mittels ${hyrasReferenceDisplay()}`};',
        1,
    )

    old_hist_ref = '''async function hyrasLoadHistoricalReference(month){
  const manifest=await hyrasLoadHistoricalManifest();
  const path=manifest.reference_files?.[String(month)];
  if(!path) throw new Error(`Referenzraster für Monat ${month} fehlt.`);'''
    new_hist_ref = '''async function hyrasLoadHistoricalReference(month){
  const manifest=await hyrasLoadHistoricalManifest();
  const path=hyrasReferenceFiles(manifest)?.[String(month)];
  if(!path) throw new Error(`Referenzraster ${hyrasReferenceDisplay()} für Monat ${month} fehlt.`);'''
    text = replace_once(text, old_hist_ref, new_hist_ref, "Historische Niederschlagsreferenz")

    old_cum = '''  const files=kind==="reference"?manifest.reference_files:manifest.current_files;
  const path=files?.[iso];if(!path) throw new Error(`Für ${hyrasDate(iso)} liegt kein ${kind==="reference"?"Referenz-":"aktuelles "}Webraster vor.`);'''
    new_cum = '''  const files=kind==="reference"?hyrasReferenceFiles(manifest):manifest.current_files;
  const path=files?.[iso];if(!path) throw new Error(`Für ${hyrasDate(iso)} liegt kein ${kind==="reference"?`Referenzraster ${hyrasReferenceDisplay()} `:"aktuelles "}Webraster vor.`);'''
    text = replace_once(text, old_cum, new_cum, "Tagesreferenz-Auswahl")

    old_preset = '''async function hyrasLoadPresetState(period){
  const info=period?.interactive;if(!info?.current)throw new Error("Interaktives 1-km-Raster fehlt für diesen Zeitraum.");
  const current=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(info.current),info.value_scale||10);let reference=null;
  if(info.reference)reference=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(info.reference),info.value_scale||10);
  return {current,reference,width:current.width,height:current.height,resolutionKm:1,key:period.key};
}'''
    new_preset = '''async function hyrasLoadPresetState(period){
  const info=period?.interactive;if(!info?.current)throw new Error("Interaktives 1-km-Raster fehlt für diesen Zeitraum.");
  const current=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(info.current),info.value_scale||10);let reference=null;
  const referencePath=info.references?.[hyrasReferencePeriod()]||info.reference;
  if(referencePath)reference=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(referencePath),info.value_scale||10);
  return {current,reference,width:current.width,height:current.height,resolutionKm:1,key:period.key,referenceKey:hyrasReferencePeriod()};
}'''
    text = replace_once(text, old_preset, new_preset, "Preset-Referenz")

    old_render_preset = '''  if(!hyrasPresetState||hyrasPresetState.key!==period.key)hyrasPresetState=await hyrasLoadPresetState(period);
  const interactive=hyrasIndex?.interactive||{};
  await hyrasDrawInteractiveMap({state:hyrasPresetState,title:`HYRAS-Niederschlag · ${period.label||""}`,subtitle:`${period.date_label||""} · ${period.reference_exact?"Referenz 1991–2020":"aktueller HYRAS-Zeitraum"}`,boundaryOverlay:interactive.boundary_overlay_1km,geoLookup:interactive.geo_lookup_1km,downloadName:`hyras_${period.key}_${document.getElementById("hyrasMetricSelect")?.value||"sum"}.png`});'''
    new_render_preset = '''  if(!hyrasPresetState||hyrasPresetState.key!==period.key||hyrasPresetState.referenceKey!==hyrasReferencePeriod())hyrasPresetState=await hyrasLoadPresetState(period);
  const interactive=hyrasIndex?.interactive||{};
  await hyrasDrawInteractiveMap({state:hyrasPresetState,title:`HYRAS-Niederschlag · ${period.label||""}`,subtitle:`${period.date_label||""} · ${period.reference_exact?`Referenz ${hyrasReferenceDisplay()}`:"aktueller HYRAS-Zeitraum"}`,boundaryOverlay:interactive.boundary_overlay_1km,geoLookup:interactive.geo_lookup_1km,downloadName:`hyras_${period.key}_${document.getElementById("hyrasMetricSelect")?.value||"sum"}_${hyrasReferenceSlug()}.png`});'''
    text = replace_once(text, old_render_preset, new_render_preset, "Preset-Untertitel")

    text = text.replace(
        'subtitle:`${state.dateLabel} · Referenz 1991–2020 · historisches HYRAS-1-km-Raster`',
        'subtitle:`${state.dateLabel} · Referenz ${hyrasReferenceDisplay()} · historisches HYRAS-1-km-Raster`',
        1,
    )

    old_live_key = 'const stateKey=`${period.key}|${start}|${end}|${manifest.data_through||manifest.last_date}`;'
    new_live_key = 'const stateKey=`${period.key}|${start}|${end}|${manifest.data_through||manifest.last_date}|${hyrasReferencePeriod()}`;'
    text = replace_once(text, old_live_key, new_live_key, "Live-State-Referenz")
    text = text.replace(
        'document.getElementById("hyrasReferenceMeanDetail").textContent="exakter gleicher Kalenderabschnitt 1991–2020";',
        'document.getElementById("hyrasReferenceMeanDetail").textContent=`exakter gleicher Kalenderabschnitt ${hyrasReferenceDisplay()}`;',
        1,
    )
    text = text.replace(
        'if(note)note.textContent=period.reference_note||"Tagesgenauer HYRAS-Vergleich mit exakt demselben Kalenderabschnitt 1991–2020.";',
        'if(note)note.textContent=`Tagesgenauer HYRAS-Vergleich mit exakt demselben Kalenderabschnitt ${hyrasReferenceDisplay()}.`;',
        1,
    )
    text = text.replace(
        'subtitle:`${period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`} · tagesgenaue Referenz 1991–2020`,',
        'subtitle:`${period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`} · tagesgenaue Referenz ${hyrasReferenceDisplay()}`,',
        1,
    )

    old_restore = '''function hyrasRestorePrecipMetricOptions(){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  select.innerHTML='<option value="percent">Prozent des Mittels 1991–2020</option><option value="sum">Niederschlagssumme</option><option value="anomaly">Abweichung in l/m²</option>';
  select.value="percent";
}'''
    new_restore = '''function hyrasRestorePrecipMetricOptions(){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  select.innerHTML=`<option value="percent">Prozent des Mittels ${hyrasReferenceDisplay()}</option><option value="sum">Niederschlagssumme</option><option value="anomaly">Abweichung zu ${hyrasReferenceDisplay()} in l/m²</option>`;
  select.value="percent";
}'''
    text = replace_once(text, old_restore, new_restore, "Niederschlags-Metriken")

    old_tmean_opts = '''function hyrasTmeanMetricOptions(hasAnomaly=true){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  const previous=select.value;
  select.innerHTML='<option value="absolute">Temperatur (°C)</option><option value="anomaly">Abweichung 1991–2020 (K)</option>';
  select.querySelector('option[value="anomaly"]').disabled=!hasAnomaly;
  select.value=(previous==="anomaly"&&hasAnomaly)?"anomaly":"absolute";
}'''
    new_tmean_opts = '''function hyrasTmeanMetricOptions(hasAnomaly=true){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  const previous=select.value;
  select.innerHTML=`<option value="absolute">Temperatur (°C)</option><option value="anomaly">Abweichung ${hyrasReferenceDisplay()} (K)</option>`;
  select.querySelector('option[value="anomaly"]').disabled=!hasAnomaly;
  select.value=(previous==="anomaly"&&hasAnomaly)?"anomaly":"absolute";
}'''
    text = replace_once(text, old_tmean_opts, new_tmean_opts, "Tmean-Metriken")

    old_hist_loop = '''async function hyrasTmeanHistoricalReference(type,month){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,sum=new Float64Array(plane),count=new Uint16Array(plane);
  for(let year=1991;year<=2020;year++){'''
    new_hist_loop = '''async function hyrasTmeanHistoricalReference(type,month){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,sum=new Float64Array(plane),count=new Uint16Array(plane),refYears=hyrasReferenceYears();
  for(let year=refYears.start;year<=refYears.end;year++){'''
    text = replace_once(text, old_hist_loop, new_hist_loop, "Tmean-Historienreferenz")

    old_tmean_current = '''  const path=selectedMode==="anomaly"?period.anomaly:period.absolute;if(!path)throw new Error("Für diesen laufenden Tmean-Zeitraum ist die Abweichung noch nicht verfügbar.");
  const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768,0,HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR);
  const stats=period.stats||{},anom=Number(stats.anomaly_mean_k),ref=Number(stats.reference_mean_c),cur=Number(stats.current_mean_c);'''
    new_tmean_current = '''  const selectedReference=hyrasReferencePeriod();
  const anomalyPath=period.anomaly_by_reference?.[selectedReference]||period.anomaly;
  const path=selectedMode==="anomaly"?anomalyPath:period.absolute;if(!path)throw new Error(`Für diesen Tmean-Zeitraum ist die Abweichung zu ${hyrasReferenceDisplay()} noch nicht verfügbar.`);
  const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768,0,HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR);
  const refStats=period.stats_by_reference?.[selectedReference]||period.stats||{},stats=period.stats||{},anom=Number(refStats.anomaly_mean_k),ref=Number(refStats.reference_mean_c),cur=Number(stats.current_mean_c);'''
    text = replace_once(text, old_tmean_current, new_tmean_current, "Tmean-Aktuellreferenz")

    text = text.replace(
        'subtitle:`${selectedMode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`',
        'subtitle:`${selectedMode==="anomaly"?`Abweichung ${hyrasReferenceDisplay()}`:"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`',
        1,
    )
    text = text.replace(
        'subtitle:`${mode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · Historie seit ${hyrasTmeanHistoryManifest.first_year}`',
        'subtitle:`${mode==="anomaly"?`Abweichung ${hyrasReferenceDisplay()}`:"2-m-Temperaturmittel"} · Historie seit ${hyrasTmeanHistoryManifest.first_year}`',
        1,
    )
    text = text.replace(
        'Referenz 1991–2020.`;',
        'Referenz ${hyrasReferenceDisplay()}.`;',
        1,
    )

    # Downloadkarten der Temperaturparameter verwenden die gewählte Referenz.
    replacements = (
        ('const maps=hyrasTmeanMapDownloads?.periods?.[period.map_key]||{};',
         'const mapsBase=hyrasTmeanMapDownloads?.periods?.[period.map_key]||{},maps={...mapsBase,anomaly:mapsBase.anomaly_by_reference?.[hyrasReferencePeriod()]||mapsBase.anomaly};'),
        ('const maps=hyrasTmaxMapDownloads?.periods?.[period.key]||{};',
         'const mapsBase=hyrasTmaxMapDownloads?.periods?.[period.key]||{},maps={...mapsBase,anomaly:mapsBase.anomaly_by_reference?.[hyrasReferencePeriod()]||mapsBase.anomaly};'),
        ('const maps=hyrasTminMapDownloads?.periods?.[period.key]||{};',
         'const mapsBase=hyrasTminMapDownloads?.periods?.[period.key]||{},maps={...mapsBase,anomaly:mapsBase.anomaly_by_reference?.[hyrasReferencePeriod()]||mapsBase.anomaly};'),
    )
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"HYRAS-Referenz-Patch fehlgeschlagen (Temperatur-Map-Auswahl): {old}")
        text = text.replace(old, new, 1)
    text = text.replace("Abweichungskarte 1991–2020 herunterladen", "Abweichungskarte ${hyrasReferenceDisplay()} herunterladen")

    # Referenzwechsel invalidiert nur HYRAS-Zustände, nicht das Seitendesign.
    listener_anchor = 'document.getElementById("hyrasMetricSelect")?.addEventListener("change",()=>renderHyras());'
    listener = listener_anchor + '\n  document.getElementById("hyrasReferenceSelect")?.addEventListener("change",()=>{hyrasPresetState=null;hyrasLivePresetState=null;hyrasHistoricalState=null;hyrasTmeanHistoricalState=null;hyrasRestorePrecipMetricOptions();const p=hyrasParameter();if(p==="precipitation"&&document.getElementById("hyrasPeriodSelect")?.value==="__historical__")hyrasApplyHistorical();else renderHyras();});'
    text = replace_once(text, listener_anchor, listener, "Referenz-Listener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS-Referenzauswahl 1991–2020 / 1961–1990 eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
