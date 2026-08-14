#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_LIVE_DAILY_PRESETS_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS-Live-Frontend ist bereits eingebaut.")
        return 0

    text = replace_once(
        text,
        "let hyrasPresetState=null;\n",
        "let hyrasPresetState=null;\nlet hyrasLivePresetState=null;\n",
        "Live-State",
    )

    helper = r'''// HYRAS_LIVE_DAILY_PRESETS_V1
async function hyrasRenderLiveDailyPreset(period){
  const manifest=await hyrasLoadWebManifest();
  const start=period?.start_date,end=period?.end_date;
  if(!start||!end)throw new Error("Laufender HYRAS-Zeitraum besitzt kein Start-/Enddatum.");
  if(start<manifest.first_date||end>manifest.last_date)throw new Error(`Tagesdaten verfügbar: ${hyrasDate(manifest.first_date)} bis ${hyrasDate(manifest.last_date)}.`);
  const stateKey=`${period.key}|${start}|${end}|${manifest.data_through||manifest.last_date}`;
  if(!hyrasLivePresetState||hyrasLivePresetState.stateKey!==stateKey){
    const prev=hyrasPreviousIso(start);
    const [curEnd,curPrev,refEnd,refPrev]=await Promise.all([
      hyrasCumulativeRaster("current",end),
      hyrasCumulativeRaster("current",prev,true),
      hyrasCumulativeRaster("reference",end),
      hyrasCumulativeRaster("reference",prev,true),
    ]);
    const current=hyrasRangeDifference(curEnd,curPrev),reference=hyrasRangeDifference(refEnd,refPrev),stats=hyrasCustomStats(current,reference);
    hyrasLivePresetState={stateKey,start,end,current,reference,stats,width:current.width,height:current.height,resolutionKm:Number(manifest.web_sampling_km||2)};
  }
  const state=hyrasLivePresetState,stats=state.stats||{};
  const metricSelect=document.getElementById("hyrasMetricSelect");
  if(metricSelect)[...metricSelect.options].forEach(option=>option.disabled=false);
  document.getElementById("hyrasPeriodStat").textContent=period.label||"Aktueller Zeitraum";
  document.getElementById("hyrasDataThrough").textContent=period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`;
  document.getElementById("hyrasCurrentMean").textContent=hyrasNum(stats.current_mean_mm,"l/m²",1);
  document.getElementById("hyrasCurrentMeanDetail").textContent=`HYRAS-Tagesdaten · Webraster ${state.resolutionKm} km`;
  document.getElementById("hyrasReferenceMean").textContent=hyrasNum(stats.reference_mean_mm,"l/m²",1);
  document.getElementById("hyrasReferenceMeanDetail").textContent="exakter gleicher Kalenderabschnitt 1991–2020";
  document.getElementById("hyrasPercentMean").textContent=hyrasNum(stats.percent_of_reference,"%",1);
  const anom=Number(stats.anomaly_mean_mm);
  document.getElementById("hyrasAnomalyMean").textContent=Number.isFinite(anom)?`${anom>=0?"+":""}${hyrasNum(anom,"l/m²",1)} zum Mittel`:"Abweichung nicht verfügbar";
  const note=document.getElementById("hyrasReferenceNote");
  if(note)note.textContent=period.reference_note||"Tagesgenauer HYRAS-Vergleich mit exakt demselben Kalenderabschnitt 1991–2020.";
  await hyrasDrawInteractiveMap({
    state,
    title:`HYRAS-Niederschlag · ${period.label||"Aktueller Zeitraum"}`,
    subtitle:`${period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`} · tagesgenaue Referenz 1991–2020`,
    boundaryOverlay:manifest.boundary_overlay,
    geoLookup:manifest.geo_lookup,
    downloadName:`hyras_${period.key}_${metricSelect?.value||"percent"}.png`,
  });
}
'''
    text = replace_once(text, "function renderHyras(){\n", helper + "function renderHyras(){\n", "Live-Renderer")

    old = "  const period=hyrasSelectedPeriod();if(!period)return;updateHyrasMetricAvailability(period);"
    new = "  const period=hyrasSelectedPeriod();if(!period)return;if(period.daily_live){hyrasRenderLiveDailyPreset(period).catch(error=>{console.error(\"HYRAS Live-Preset:\",error);const frame=document.getElementById(\"hyrasMapFrame\");if(frame)frame.innerHTML=`<div class=\"hyras-loading\">${error.message}</div>`;});return;}updateHyrasMetricAvailability(period);"
    text = replace_once(text, old, new, "Render-Routing")

    old_change = 'document.getElementById("hyrasPeriodSelect")?.addEventListener("change",event=>{if(event.target.value!=="__custom__")hyrasCustomState=null;if(event.target.value!=="__historical__")hyrasHistoricalState=null;hyrasPresetState=null;renderHyras();});'
    new_change = 'document.getElementById("hyrasPeriodSelect")?.addEventListener("change",event=>{if(event.target.value!=="__custom__")hyrasCustomState=null;if(event.target.value!=="__historical__")hyrasHistoricalState=null;hyrasPresetState=null;hyrasLivePresetState=null;renderHyras();});'
    text = replace_once(text, old_change, new_change, "Periodenwechsel")

    text = text.replace(
        "Version 15.4 · interaktive HYRAS-Karten mit Mouseover · Historie ab 1931 · Referenz 1991–2020",
        "Version 15.5 · laufender Monat &amp; aktuelle Jahreszeit tagesgenau · Historie ab 1931 · Referenz 1991–2020",
        1,
    )
    text = text.replace(
        "Prozent- und Abweichungskarten werden nur dann gezeigt, wenn für den gewählten Zeitraum ein exakter 1991–2020-Vergleich vorliegt.",
        "Laufender Monat, aktuelle Jahreszeit und Jahr werden bis zum letzten HYRAS-Tag fortgeschrieben und mit exakt demselben Kalenderabschnitt 1991–2020 verglichen.",
        1,
    )

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS-Live-Frontend in index.html eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
