#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MARKER = "// ERA5_RUNNING_FRONTEND_V1"


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    if MARKER in text:
        print("ERA5 laufendes Frontend ist bereits eingebaut.")
        return 0

    pattern = re.compile(
        r'// ERA5_TP_ALL_MONTHS_FRONTEND_V1\nfunction era5EuropeUpdatePeriodOptions\(\)\{.*?\n\}\nfunction era5EuropePeriodIsHistoricalOnly',
        re.S,
    )
    replacement = '''// ERA5_TP_ALL_MONTHS_FRONTEND_V1\n''' + MARKER + '''\nfunction era5EuropeUpdatePeriodOptions(){
  const select=document.getElementById("era5EuropePeriod");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const previous=select.value||"latest_month";
  const latest=era5EuropeIndex?.periods?.latest_month;
  const summer=era5EuropeIndex?.periods?.summer;
  const runningMonth=era5EuropeIndex?.periods?.running_month;
  const runningSummer=era5EuropeIndex?.periods?.running_summer;
  const tp=parameter==="temperature"||parameter==="precipitation";
  let html='<optgroup label="Aktuell / Saison">';
  if(tp&&runningMonth)html+=`<option value="running_month">${runningMonth.label||"Laufender Monat"}</option>`;
  if(tp&&runningSummer)html+=`<option value="running_summer">${runningSummer.label||"Laufender Sommer"}</option>`;
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
}
function era5EuropePeriodIsHistoricalOnly'''
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Frontend-Patch: era5EuropeUpdatePeriodOptions nicht gefunden.")

    old = '''  const historicalOnly=Boolean(period.historical_only);\n  const previous=select.value||"current";'''
    new = '''  const historicalOnly=Boolean(period.historical_only);\n  const runningOnly=Boolean(period.running_only);\n  const previous=select.value||"current";'''
    if old not in text:
        raise RuntimeError("Frontend-Patch: Map-Year-Patchstelle 1 fehlt.")
    text = text.replace(old, new, 1)

    old = '''  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+\n    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");\n  if([...select.options].some(o=>o.value===previous))select.value=previous;\n  else select.value=historicalOnly?String(end):"current";'''
    new = '''  if(runningOnly){select.innerHTML='<option value="current">Laufender Datenstand</option>';select.value="current";return;}\n  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+\n    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");\n  if([...select.options].some(o=>o.value===previous))select.value=previous;\n  else select.value=historicalOnly?String(end):"current";'''
    if old not in text:
        raise RuntimeError("Frontend-Patch: Map-Year-Patchstelle 2 fehlt.")
    text = text.replace(old, new, 1)

    helper_needle = 'function renderEra5Europe(){\n'
    helper = '''function era5EuropePeriodDataThrough(period){return period?.running_data_through||era5EuropeIndex?.data_through||"–";}\nfunction renderEra5Europe(){\n'''
    if helper_needle not in text:
        raise RuntimeError("Frontend-Patch: renderEra5Europe fehlt.")
    text = text.replace(helper_needle, helper, 1)

    text = text.replace(
        'document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropeIndex.data_through}`;',
        'document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropePeriodDataThrough(period)}`;',
    )

    INDEX.write_text(text, encoding="utf-8")
    print("ERA5 laufender Monat und Sommer im Frontend ergänzt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
