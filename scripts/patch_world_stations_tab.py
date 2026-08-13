#!/usr/bin/env python3
"""Idempotently add the 'Weltweite Stationen' tab to the current dashboard HTML.

The script intentionally patches the checked-out *current* index.html inside the
GitHub Actions runner.  That avoids replacing newer dashboard work with an older
local copy.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

NAV_MARKER = "<!-- WORLD_STATIONS_TAB_NAV_V1 -->"
HTML_START = "<!-- WORLD_STATIONS_TAB_HTML_V1_START -->"
HTML_END = "<!-- WORLD_STATIONS_TAB_HTML_V1_END -->"
ASSET_MARKER = "<!-- WORLD_STATIONS_ASSETS_V1 -->"

EUROPE_BUTTON = "  <button class=\"tab-button\" onclick=\"switchTab('europeStations')\">Europa-Stationen</button>"
CURRENT_MARKER = "<!-- ================= AKTUELL / 10-MINUTEN ================= -->"

TAB_HTML = r'''<!-- WORLD_STATIONS_TAB_HTML_V1_START -->
<!-- ================= WELTWEITE STATIONEN · GHCN ================= -->
<div id="worldStations" class="tab-content">
  <div class="section-header">
    <h2>Weltweite Stationen</h2>
    <p>Historische GHCN-Daily-Temperaturstationen weltweit mit Stationsrekorden, Messzeiträumen und dem fachlich geprüften Länderrekord-Master bis einschließlich 2025.</p>
    <span id="worldStationBaselineInfo" class="section-status">NOAA GHCN-Daily · historischer Cutoff 2025</span>
  </div>
  <div class="controls world-station-controls">
    <div class="control-group"><label for="worldStationContinent">Bereich / Kontinent</label><select id="worldStationContinent"><option value="world">Welt</option><option value="Europe">Europa</option><option value="Africa">Afrika</option><option value="Asia">Asien</option><option value="North America">Nordamerika</option><option value="South America">Südamerika</option><option value="Oceania">Ozeanien</option><option value="Antarctica">Antarktis</option></select></div>
    <div class="control-group"><label for="worldStationCountry">Land</label><select id="worldStationCountry"><option value="">Alle Länder</option></select></div>
    <div class="control-group"><label for="worldStationStatusFilter">Stationsstatus</label><select id="worldStationStatusFilter"><option value="active" selected>Nur bis 2025 aktive</option><option value="all">Alle historischen Stationen</option></select></div>
    <div class="control-group"><label for="worldStationAvailability">Messparameter</label><select id="worldStationAvailability"><option value="any">TMAX oder TMIN</option><option value="both" selected>TMAX + TMIN</option><option value="tmax">TMAX</option><option value="tmin">TMIN</option></select></div>
    <div class="control-group"><label for="worldStationMinYears">Mind. Messjahre</label><select id="worldStationMinYears"><option value="0" selected>keine Begrenzung</option><option value="10">10 Jahre</option><option value="30">30 Jahre</option><option value="50">50 Jahre</option><option value="75">75 Jahre</option><option value="100">100 Jahre</option></select></div>
    <div class="control-group"><label for="worldStationSearch">Stationssuche</label><input id="worldStationSearch" type="search" autocomplete="off" placeholder="Name, ID oder Land …"></div>
  </div>
  <div class="world-station-summary">
    <div class="world-station-summary-card"><div class="label">Stationen sichtbar</div><div id="worldStationShown" class="value">–</div><div class="detail">nach allen Filtern</div></div>
    <div class="world-station-summary-card"><div class="label">davon aktiv</div><div id="worldStationActiveShown" class="value">–</div><div class="detail">Inventar reicht bis 2025/2026</div></div>
    <div class="world-station-summary-card"><div class="label">Länder / Gebiete</div><div id="worldStationCountriesShown" class="value">–</div><div class="detail">mit sichtbaren Stationen</div></div>
    <div class="world-station-summary-card"><div class="label">Datenbestand</div><div id="worldStationDataStatus" class="value" style="font-size:14px">–</div><div class="detail">NOAA GHCN-Daily · QC-Master Stage 9</div></div>
  </div>
  <div id="worldStationStatus" class="world-station-loading">Weltweite Stationsdaten werden beim ersten Öffnen geladen …</div>
  <div class="world-station-layout" style="margin-top:14px">
    <div class="chart-container auto world-station-map-card">
      <div id="worldStationMap" class="world-station-map" role="img" aria-label="Weltkarte der GHCN-Temperaturstationen"></div>
      <div class="world-station-map-legend"><span><i style="background:#3aa06a"></i> bis 2025 aktive Station</span><span><i style="background:#9da5ab"></i> historische Station</span></div>
    </div>
    <div class="world-station-side">
      <div id="worldStationSelected" class="world-station-side-card"><h3>Station auswählen</h3><p class="note">Klicke einen Punkt auf der Karte oder eine Tabellenzeile an. Danach erscheinen hier Messzeitraum und die vier berechneten Stations-Temperaturextreme.</p></div>
      <div class="world-station-side-card"><h3>Länderrekorde · Stage 9</h3><p class="note">Ein Land im Filter auswählen. Offene QC-Fälle werden nicht als fertiger Rekord ausgegeben.</p><div id="worldStationCountryRecords" class="world-country-records"><p class="note">Land auswählen …</p></div></div>
    </div>
  </div>
  <div class="world-station-table-card">
    <div class="world-station-table-head"><div><h3>Stationsliste</h3><p id="worldStationTableNote" class="note">Daten werden geladen …</p></div></div>
    <div class="world-station-table-wrap"><table id="worldStationTable" class="world-station-table"><thead><tr><th>Station</th><th>Stations-ID</th><th>Land</th><th>Status</th><th>TMAX-Reihe</th><th>TMIN-Reihe</th><th>TMAX max</th><th>TMIN min</th><th>Höhe</th></tr></thead><tbody><tr><td colspan="9">Daten werden geladen …</td></tr></tbody></table></div>
  </div>
  <p class="note" style="margin-top:12px">Methodik: Stationswerte stammen aus dem historischen NOAA-GHCN-Daily-Baseline-Lauf bis 2025. Akzeptiert werden nur Tagesbeobachtungen mit leerem GHCN-QFLAG; die fachliche Länderrekord-QC bleibt davon getrennt. Die Kontinentwahl lädt nur den jeweiligen Datenblock und zoomt die Karte automatisch auf den gewählten Bereich.</p>
</div>
<!-- WORLD_STATIONS_TAB_HTML_V1_END -->'''


def patch_text(text: str) -> str:
    if NAV_MARKER not in text:
        if EUROPE_BUTTON not in text:
            raise RuntimeError("Europa-Stationen-Button als Patch-Anker nicht gefunden.")
        text = text.replace(
            EUROPE_BUTTON,
            EUROPE_BUTTON + "\n" + NAV_MARKER + "\n  <button class=\"tab-button\" onclick=\"switchTab('worldStations')\">Weltweite Stationen</button>",
            1,
        )

    if HTML_START not in text:
        if CURRENT_MARKER not in text:
            raise RuntimeError("Aktuell-Abschnitt als HTML-Patch-Anker nicht gefunden.")
        text = text.replace(CURRENT_MARKER, TAB_HTML + "\n" + CURRENT_MARKER, 1)

    if ASSET_MARKER not in text:
        if "</head>" not in text or "</body>" not in text:
            raise RuntimeError("HTML head/body Abschluss nicht gefunden.")
        text = text.replace(
            "</head>",
            f'{ASSET_MARKER}\n<link rel="stylesheet" href="world_stations_tab.css?v=1">\n</head>',
            1,
        )
        text = text.replace(
            "</body>",
            '<script src="world_stations_tab.js?v=1"></script>\n<!-- Erweiterung 19.0: Weltweite GHCN-Stationen mit Kontinentfilter -->\n</body>',
            1,
        )

    if text.count("switchTab('worldStations')") != 1:
        raise RuntimeError("Weltweite-Stationen-Tab wurde nicht eindeutig eingebaut.")
    if text.count('id="worldStations"') != 1:
        raise RuntimeError("worldStations-HTML ist nicht eindeutig vorhanden.")
    if text.count("world_stations_tab.js?v=1") != 1 or text.count("world_stations_tab.css?v=1") != 1:
        raise RuntimeError("World-Station-Assets sind nicht eindeutig eingebunden.")
    return text


def self_test() -> None:
    sample = f'''<!doctype html><html><head><style></style></head><body><div class="tabs">\n{EUROPE_BUTTON}\n</div>\n{CURRENT_MARKER}\n<div id="current"></div>\n</body></html>'''
    first = patch_text(sample)
    second = patch_text(first)
    assert first == second
    assert "Weltweite Stationen" in first
    assert 'id="worldStationContinent"' in first
    print("patch_world_stations_tab.py self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("index.html"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    text = args.input.read_text(encoding="utf-8")
    patched = patch_text(text)
    args.input.write_text(patched, encoding="utf-8")
    print(f"Weltweite-Stationen-Reiter in {args.input} geprüft/eingebaut.")


if __name__ == "__main__":
    main()
