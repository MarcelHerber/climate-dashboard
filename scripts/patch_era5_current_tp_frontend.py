#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MARKER = "// ERA5_TP_CURRENT_MONTHS_FRONTEND_V1"


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    if MARKER in text:
        print("ERA5 aktuelles T/P-Monatsfrontend ist bereits eingebaut.")
        return 0

    # Die Monatsgruppe umfasst jetzt sowohl das aktuelle vollständige Jahr als auch
    # die historische Auswahl 1950–2025.
    text, count = re.subn(
        r'Historisches Monatsarchiv 1950–\$\{era5EuropeIndex\?\.history_map\?\.year_end\|\|""\}',
        r'Monate · aktuell + Historie 1950–${era5EuropeIndex?.history_map?.year_end||""}',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"Frontend-Patch: Monatsgruppen-Label nicht gefunden ({count}).")

    # Für die neuen aktuellen Einzelmonate gibt es zunächst noch keine 1°-Historienanalyse.
    # Daher Klickanalyse dort deaktivieren, statt ein leeres Analysepanel zu öffnen.
    needle = 'async function era5EuropeHandleMapClick(event){\n'
    replacement = (
        MARKER + '\n' +
        'async function era5EuropeHandleMapClick(event){\n'
        '  const selectedPeriodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";\n'
        '  if(era5EuropeIndex?.periods?.[selectedPeriodId]?.analysis_ready===false)return;\n'
    )
    if needle not in text:
        raise RuntimeError("Frontend-Patch: era5EuropeHandleMapClick nicht gefunden.")
    text = text.replace(needle, replacement, 1)

    # Im aktuellen Kartenmodus für die neuen Einzelmonate ebenfalls klar anzeigen,
    # dass Rankings/Gitterpunktserien erst in einer späteren Stufe folgen.
    old = (
        '  if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();\n'
        '  renderEra5EuropeRankings();\n'
        '}\nasync function downloadEra5EuropeMap'
    )
    new = (
        '  if(period?.analysis_ready===false){\n'
        '    era5EuropeShowMonthlyRankingPending(meta,period,Number(period?.year));\n'
        '  }else{\n'
        '    if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();\n'
        '    renderEra5EuropeRankings();\n'
        '  }\n'
        '}\nasync function downloadEra5EuropeMap'
    )
    if old not in text:
        raise RuntimeError("Frontend-Patch: Ende von renderEra5Europe nicht gefunden.")
    text = text.replace(old, new, 1)

    text = text.replace(
        'Version 9.0 · Temperatur &amp; Niederschlag monatlich Jan–Dez seit 1950',
        'Version 10.0 · Temperatur &amp; Niederschlag monatlich · aktuelles Jahr + Historie seit 1950',
        1,
    )

    INDEX.write_text(text, encoding="utf-8")
    print("ERA5 aktuelles T/P-Monatsfrontend ergänzt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
