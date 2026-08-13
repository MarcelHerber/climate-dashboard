#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MARKER = "// ERA5_PERIOD_YEAR_LABEL_FIX_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"ERA5-Beschriftungsfix: {label} nicht gefunden.")
    return text.replace(old, new, 1)


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    if MARKER in text:
        print("ERA5 Perioden-/Jahresbeschriftung ist bereits korrigiert.")
        return 0

    helper_anchor = 'function era5EuropeShowMonthlyRankingPending(meta,period,year){\n'
    helpers = r'''// ERA5_PERIOD_YEAR_LABEL_FIX_V1
function era5EuropePeriodDisplayLabel(period,year){
  const raw=String(period?.label||"Zeitraum").trim();
  const y=Number(year);
  if(!Number.isFinite(y))return raw;
  const periodYear=Number(period?.year);
  if(Number.isFinite(periodYear)){
    const re=new RegExp(`\\b${periodYear}\\b`,'g');
    if(re.test(raw))return raw.replace(re,String(y));
  }
  const months=(period?.months||[]).map(Number).filter(Number.isFinite);
  if(months.length===1)return `${raw.replace(/\\s+(?:19|20)\\d{2}\\s*$/,'').trim()} ${y}`;
  return raw;
}
function era5EuropeSyncPeriodOptionLabels(){
  const select=document.getElementById("era5EuropePeriod");if(!select||!era5EuropeIndex)return;
  const selectedYear=era5EuropeMapYear();
  for(const option of select.options){
    if(!String(option.value||"").startsWith("month_"))continue;
    const period=era5EuropeIndex?.periods?.[option.value];if(!period)continue;
    const year=Number.isFinite(selectedYear)?selectedYear:Number(period?.year);
    option.textContent=era5EuropePeriodDisplayLabel(period,year);
  }
}
'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "Helper-Anker")

    text = replace_once(
        text,
        '  document.getElementById("era5EuropeRankingTitle").textContent=`${meta.label} · ${period?.label||"Monat"} ${year}`;\n',
        '  document.getElementById("era5EuropeRankingTitle").textContent=`${meta.label} · ${era5EuropePeriodDisplayLabel(period,year)}`;\n',
        "Ranking-Titel",
    )

    text = replace_once(
        text,
        '  document.getElementById("era5EuropeMapTitle").textContent=`${meta.label} · ${year} · ${period?.label||year}`;document.getElementById("era5EuropeMapSubtitle").textContent=`Historische 0,1°-ERA5-Land-Karte · ${document.getElementById("era5EuropeView")?.selectedOptions?.[0]?.textContent||view}${clickable?\' · Rankings/KPIs separat auf 1,0°\':\' · Monatsarchiv\'}`;\n'
        '  document.getElementById("era5EuropePeriodKpi").textContent=`${year} · ${period?.label||periodId}`;document.getElementById("era5EuropeDataKpi").textContent="Historisches Archiv · sichtbares Raster 0,1°";\n',
        '  const periodDisplayLabel=era5EuropePeriodDisplayLabel(period,year);\n'
        '  document.getElementById("era5EuropeMapTitle").textContent=`${meta.label} · ${periodDisplayLabel}`;document.getElementById("era5EuropeMapSubtitle").textContent=`Historische 0,1°-ERA5-Land-Karte · ${document.getElementById("era5EuropeView")?.selectedOptions?.[0]?.textContent||view}${clickable?\' · Rankings/KPIs separat auf 1,0°\':\' · Monatsarchiv\'}`;\n'
        '  document.getElementById("era5EuropePeriodKpi").textContent=periodDisplayLabel;document.getElementById("era5EuropeDataKpi").textContent="Historisches Archiv · sichtbares Raster 0,1°";\n',
        "Historischer Karten-/KPI-Titel",
    )

    text = replace_once(
        text,
        'function renderEra5Europe(){\n  if(!era5EuropeIndex?.ready)return;\n',
        'function renderEra5Europe(){\n  if(!era5EuropeIndex?.ready)return;\n  era5EuropeSyncPeriodOptionLabels();\n',
        "Render-Synchronisierung",
    )

    INDEX.write_text(text, encoding="utf-8")
    print("ERA5 historische Monatsbeschriftungen korrigiert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
