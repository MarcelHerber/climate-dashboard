#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MARKER_V1 = "// ERA5_RUNNING_FRONTEND_V1"
MARKER_V2 = "// ERA5_RUNNING_FRONTEND_V2"

DYNAMIC_FUNCTION = '''function era5EuropeUpdatePeriodOptions(){
  const select=document.getElementById("era5EuropePeriod");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const previous=select.value||"latest_month";
  const latest=era5EuropeIndex?.periods?.latest_month;
  const summer=era5EuropeIndex?.periods?.summer;
  const runningMonth=era5EuropeIndex?.periods?.running_month;
  const runningSeasonIds=["running_spring","running_summer","running_autumn","running_winter"];
  const runningSeasonId=runningSeasonIds.find(id=>era5EuropeIndex?.periods?.[id]);
  const runningSeason=runningSeasonId?era5EuropeIndex.periods[runningSeasonId]:null;
  const tp=parameter==="temperature"||parameter==="precipitation";
  let html='<optgroup label="Aktuell / Saison">';
  if(tp&&runningMonth)html+=`<option value="running_month">${runningMonth.label||"Laufender Monat"}</option>`;
  if(tp&&runningSeason)html+=`<option value="${runningSeasonId}">${runningSeason.label||"Laufende Saison"}</option>`;
  html+=`<option value="latest_month">${latest?.label||"Jüngster vollständiger Monat"}</option>`+
        `<option value="summer">${summer?.label||"Sommer (JJA)"}</option>`+
        '</optgroup>';
  const monthNumbers=(era5EuropeIndex?.history_map?.temperature_precipitation_months||[]).map(Number).filter(m=>m>=1&&m<=12);
  if(tp&&monthNumbers.length){
    const options=monthNumbers.map(month=>{const id=`month_${String(month).padStart(2,"0")}`,p=era5EuropeIndex?.periods?.[id];return `<option value="${id}">${p?.label||id}</option>`;}).join("");
    html+=`<optgroup label="Monate · aktuell + Historie 1950–${era5EuropeIndex?.history_map?.year_end||""}">${options}</optgroup>`;
  }
  select.innerHTML=html;
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  else if(tp&&runningMonth)select.value="running_month";
  else select.value="latest_month";
}'''


def replace_period_function(text: str) -> str:
    pattern = re.compile(
        r'function era5EuropeUpdatePeriodOptions\(\)\{.*?\n\}\n(?=function era5EuropePeriodIsHistoricalOnly)',
        re.S,
    )
    text, count = pattern.subn(DYNAMIC_FUNCTION + "\n", text, count=1)
    if count != 1:
        raise RuntimeError("Frontend-Patch: era5EuropeUpdatePeriodOptions nicht gefunden.")
    return text


def patch_text(text: str) -> str:
    if MARKER_V2 in text:
        return text

    if MARKER_V1 in text:
        text = text.replace(MARKER_V1, MARKER_V2, 1)
        return replace_period_function(text)

    pattern = re.compile(
        r'// ERA5_TP_ALL_MONTHS_FRONTEND_V1\nfunction era5EuropeUpdatePeriodOptions\(\)\{.*?\n\}\n(?=function era5EuropePeriodIsHistoricalOnly)',
        re.S,
    )
    replacement = '// ERA5_TP_ALL_MONTHS_FRONTEND_V1\n' + MARKER_V2 + '\n' + DYNAMIC_FUNCTION + '\n'
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Frontend-Patch: Basisfunktion era5EuropeUpdatePeriodOptions nicht gefunden.")

    old = '''  const historicalOnly=Boolean(period.historical_only);\n  const previous=select.value||"current";'''
    new = '''  const historicalOnly=Boolean(period.historical_only);\n  const runningOnly=Boolean(period.running_only);\n  const previous=select.value||"current";'''
    if old in text:
        text = text.replace(old, new, 1)

    old = '''  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+\n    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");\n  if([...select.options].some(o=>o.value===previous))select.value=previous;\n  else select.value=historicalOnly?String(end):"current";'''
    new = '''  if(runningOnly){select.innerHTML='<option value="current">Laufender Datenstand</option>';select.value="current";return;}\n  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+\n    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");\n  if([...select.options].some(o=>o.value===previous))select.value=previous;\n  else select.value=historicalOnly?String(end):"current";'''
    if old in text:
        text = text.replace(old, new, 1)

    if 'function era5EuropePeriodDataThrough(period)' not in text:
        helper_needle = 'function renderEra5Europe(){\n'
        if helper_needle in text:
            text = text.replace(
                helper_needle,
                'function era5EuropePeriodDataThrough(period){return period?.running_data_through||era5EuropeIndex?.data_through||"–";}\n' + helper_needle,
                1,
            )

    text = text.replace(
        'document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropeIndex.data_through}`;',
        'document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropePeriodDataThrough(period)}`;',
    )
    return text


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    patched = patch_text(text)
    if patched == text:
        print("ERA5 laufendes Frontend V2 ist bereits eingebaut.")
        return 0
    INDEX.write_text(patched, encoding="utf-8")
    print("ERA5 laufender Monat und dynamische Saison im Frontend ergänzt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
