#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

TARGET = Path("index.html")
MARKER = "// DASHBOARD_LAZY_LOADING_V1"


def remove_optional(text: str, pattern: str, flags: int = 0) -> tuple[str, int]:
    return re.subn(pattern, "", text, count=1, flags=flags)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    original = text

    # 1) Weltweite GHCN-Stationen vorerst vollständig aus dem Frontend.
    text = text.replace(
        '      <button class="nav-link tab-button" data-nav-group="world" onclick="switchTab(\'worldStations\')">Weltweite Stationen</button>\n',
        "",
    )

    text, _ = remove_optional(
        text,
        r'\n?/\* ================= WELTWEITE STATIONEN · GHCN ================= \*/\n.*?(?=\n</style>)',
        re.S,
    )

    text, _ = remove_optional(
        text,
        r'\n?<!-- ================= WELTWEITE STATIONEN · GHCN ================= -->\n'
        r'<div id="worldStations" class="tab-content">.*?'
        r'(?=\n<!-- ================= VERGLEICHE ================= -->)',
        re.S,
    )

    text, _ = remove_optional(
        text,
        r'\n?// ================= WELTWEITE STATIONEN · GHCN =================\n.*?'
        r'(?=\nfunction switchTab\()',
        re.S,
    )
    text = text.replace('  if(tab==="worldStations") ensureWorldStationsLoaded();\n', "")

    # 2) Große Tages-Tmax-Datei erst bei tatsächlichem Bedarf laden.
    if MARKER not in text:
        old_loader = '''// ================= TAGESDATEN =================
dashboardFetch("daily_tmax_1881_2026.json",{cache:"no-store"})
  .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
  .then(data=>{
    dailyData=data;
    initializeDailyControls();
    initializeCompareYearControls();
    updateDaily();
    buildExtremeCharts();
  })
  .catch(error=>showError(`Tagesdaten konnten nicht geladen werden: ${error.message}`));

'''
        new_loader = '''// ================= TAGESDATEN =================
// DASHBOARD_LAZY_LOADING_V1
let dailyDashboardLoading=null;
let extremeDashboardInitialized=false;

function renderLoadedDailyDashboardForActiveTab(){
  const active=document.querySelector(".tab-content.active")?.id||"";
  if(active==="daily"){
    updateDaily();
    return;
  }
  if(active==="extremes"){
    if(!extremeDashboardInitialized){
      buildExtremeCharts();
      extremeDashboardInitialized=true;
    }else{
      updateExtremeDashboard();
    }
    return;
  }
  if(active==="compare"){
    initializeCompareYearControls();
    updateCompareYears();
  }
}

function ensureDailyDashboardLoaded(){
  if(dailyData.length){
    renderLoadedDailyDashboardForActiveTab();
    return Promise.resolve(dailyData);
  }
  if(dailyDashboardLoading) return dailyDashboardLoading;

  dailyDashboardLoading=dashboardFetch("daily_tmax_1881_2026.json",{cache:"no-store"})
    .then(response=>{
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data=>{
      dailyData=data;
      initializeDailyControls();
      initializeCompareYearControls();
      renderLoadedDailyDashboardForActiveTab();
      return data;
    })
    .catch(error=>{
      showError(`Tagesdaten konnten nicht geladen werden: ${error.message}`);
      throw error;
    })
    .finally(()=>{dailyDashboardLoading=null;});

  return dailyDashboardLoading;
}

'''
        if old_loader not in text:
            raise RuntimeError("Der bisherige direkte Tagesdaten-Ladeblock wurde nicht gefunden.")
        text = text.replace(old_loader, new_loader, 1)

    lazy_switch = '  if(tab==="daily"||tab==="extremes"||tab==="compare") ensureDailyDashboardLoaded();\n'
    if lazy_switch not in text:
        anchor = '  if(tab==="current") ensureCurrentConditions();\n'
        if anchor not in text:
            raise RuntimeError("switchTab-Anker für Lazy Loading nicht gefunden.")
        text = text.replace(anchor, lazy_switch + anchor, 1)

    # 3) Große Monatsdiagramme/-tabellen nur bei geöffnetem Monatsreiter rendern.
    monthly_guard = '  if(!document.getElementById("monthly")?.classList.contains("active")) return;\n'
    for function_name in (
        "updateMonthly",
        "updateMonthlyAnomalyTable",
        "updateMonthlyAbsoluteAnomalyTable",
        "updateClimateIndex",
        "updateAccumulation",
        "updateRegionalMap",
    ):
        signature = f"function {function_name}(){{\n"
        if signature in text:
            guarded = signature + monthly_guard
            if guarded not in text:
                text = text.replace(signature, guarded, 1)

    old_monthly_switch = '  if(tab==="monthly") window.setTimeout(()=>{if(regionalMap){regionalMap.invalidateSize();updateRegionalMap();}},80);\n'
    new_monthly_switch = '''  if(tab==="monthly") window.setTimeout(()=>{
    updateMonthly();
    updateMonthlyAnomalyTable();
    updateMonthlyAbsoluteAnomalyTable();
    updateClimateIndex();
    updateAccumulation();
    updateRegionalMap();
    if(regionalMap) regionalMap.invalidateSize();
  },80);
'''
    if old_monthly_switch in text:
        text = text.replace(old_monthly_switch, new_monthly_switch, 1)
    elif new_monthly_switch not in text:
        raise RuntimeError("Monats-Reiter-Anker in switchTab nicht gefunden.")

    if text == original:
        print("Dashboard-Performancepatch bereits vollständig aktiv.")
        return 0

    TARGET.write_text(text, encoding="utf-8")
    print("Dashboard-Performancepatch angewendet:")
    print("- Weltweite Stationen aus Navigation, HTML, CSS und JavaScript entfernt")
    print("- daily_tmax erst beim Öffnen von Tagesdaten/Kenntagen/Vergleich")
    print("- schwere Monatsdarstellungen nur noch beim Öffnen des Monatsreiters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
