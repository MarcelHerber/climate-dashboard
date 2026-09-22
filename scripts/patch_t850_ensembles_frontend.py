#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

CSS_TAG = '<link rel="stylesheet" href="t850_ensembles.css?v=20260922-6">'
JS_TAG = '<script src="t850_ensembles.js?v=20260922-6"></script>'
NAV_ANCHOR = '<button class="tab-button" data-nav-group="europe" onclick="switchTab(\'sst-europe\')">Meere / SST</button>'
NAV_BUTTON = '<button class="tab-button" data-nav-group="europe" onclick="switchTab(\'t850-ensembles\')">T850-Ensembles</button>'
PANEL_MARKER = '<!-- ================= T850 ENSEMBLES ================= -->'
PANEL = r'''<!-- ================= T850 ENSEMBLES ================= -->
<div id="t850-ensembles" class="tab-content">
  <div class="section-header t850-header">
    <h2>T850-Ensembles</h2>
    <p>850-hPa-Temperatur der Ensembles von ECMWF IFS, ECMWF AIFS, DWD ICON und GFS/GEFS für einen frei wählbaren Ort.</p>
    <span class="section-status">4 Modelle · voller Modellhorizont · Hauptlauf · ERA5-Referenz 1991–2020</span>
  </div>

  <form id="t850SearchForm" class="controls t850-controls">
    <div class="control-group t850-place-control">
      <label for="t850LocationInput">Ort</label>
      <input id="t850LocationInput" type="search" autocomplete="off" placeholder="z. B. Berlin, Wien, Zürich" aria-label="Ort für T850-Ensembles">
    </div>
    <div class="control-group t850-view-control">
      <label for="t850PanelSelect">Ansicht</label>
      <select id="t850PanelSelect">
        <option value="" selected>Panel auswählen …</option>
        <option value="gefs">GFS / GEFS Seamless groß</option>
        <option value="ecmwf">ECMWF IFS ENS groß</option>
        <option value="aifs">ECMWF AIFS ENS groß</option>
        <option value="icon">DWD ICON-EU EPS / Fallback</option>
        <option value="four">4er-Tafel + Modellvergleich</option>
      </select>
    </div>
    <button id="t850LoadButton" class="action" type="submit">Ensembles laden</button>
    <button id="t850ResetZoom" class="t850-secondary-button" type="button">Zoom zurücksetzen</button>
    <div class="t850-export">
      <button id="t850PngDownload" type="button" disabled>PNG</button>
      <button id="t850PdfDownload" type="button" disabled>PDF</button>
    </div>
  </form>

  <div id="t850ResolvedLocation" class="t850-location"></div>
  <div id="t850Status" class="t850-status" aria-live="polite"></div>

  <div id="t850ExportArea" class="t850-export-area">
    <div id="t850ModelGrid" class="t850-grid">
      <section class="t850-model-card" data-t850-model="ecmwf">
        <div class="t850-model-head"><div><h3>ECMWF IFS ENS</h3><div id="t850RunEcmwf" class="t850-run-label">Ensemble: – · Hauptlauf: –</div><div id="t850MetaEcmwf" class="t850-model-meta">Ort auswählen</div></div></div>
        <div class="t850-chart-shell"><canvas id="t850ChartEcmwf"></canvas></div>
      </section>
      <section class="t850-model-card" data-t850-model="aifs">
        <div class="t850-model-head"><div><h3>ECMWF AIFS ENS</h3><div id="t850RunAifs" class="t850-run-label">Ensemble: – · Hauptlauf: –</div><div id="t850MetaAifs" class="t850-model-meta">Ort auswählen</div></div></div>
        <div class="t850-chart-shell"><canvas id="t850ChartAifs"></canvas></div>
      </section>
      <section class="t850-model-card" data-t850-model="icon">
        <div class="t850-model-head"><div><h3>DWD ICON-EU EPS</h3><div id="t850RunIcon" class="t850-run-label">Ensemble: – · Hauptlauf: –</div><div id="t850MetaIcon" class="t850-model-meta">Ort auswählen</div></div></div>
        <div class="t850-chart-shell"><canvas id="t850ChartIcon"></canvas></div>
      </section>
      <section class="t850-model-card" data-t850-model="gefs">
        <div class="t850-model-head"><div><h3>GFS / GEFS Seamless</h3><div id="t850RunGefs" class="t850-run-label">Ensemble: – · Hauptlauf: –</div><div id="t850MetaGefs" class="t850-model-meta">Ort auswählen</div></div></div>
        <div class="t850-chart-shell"><canvas id="t850ChartGefs"></canvas></div>
      </section>
    </div>

    <section id="t850ComparisonCard" class="t850-comparison-card">
      <div class="t850-comparison-head">
        <div><h3>Vergleich der Ensemble-Mittel</h3><div class="t850-model-meta">Alle vier Ensemble-Mittel auf einer gemeinsamen Skala</div></div>
      </div>
      <div class="t850-chart-shell"><canvas id="t850ComparisonChart"></canvas></div>
      <div class="t850-legend-note">
        <span><i class="t850-swatch members"></i> einzelne Member</span>
        <span><i class="t850-swatch control"></i> Kontrolllauf</span>
        <span><i class="t850-swatch"></i> Ensemble-Mittel</span>
        <span><i class="t850-swatch main"></i> Hauptlauf</span>
        <span><i class="t850-swatch climate"></i> ERA5 1991–2020</span>
      </div>
    </section>
  </div>

  <p class="t850-source">
    Ensemblevorhersagen: Open-Meteo Ensemble API mit ECMWF IFS ENS, ECMWF AIFS ENS, DWD ICON EPS und NOAA GEFS.
    Die API-Daten werden stündlich geladen und im Browser auf 00/06/12/18 UTC ausgedünnt. ECMWF/AIFS laufen bis 15 Tage. ICON-EU EPS wird für T850 zuerst direkt abgefragt. Solange die API dort nur leere Werte liefert, zeigt das Panel automatisch den ICON-EU-Hauptlauf als klar gekennzeichneten Fallback. GEFS nutzt das GFS Ensemble Seamless mit erweitertem Langfrist-Horizont.
    Hauptläufe: Open-Meteo Single Runs API mit exakter UTC-Initialisierung.
    Klimareferenz: ERA5-T850 1991–2020; synoptische Monatsmittel für 00/06/12/18 UTC, zwischen den Monatsstützpunkten zeitlich interpoliert.
  </p>
</div>
'''


def patch_html(text: str) -> str:
    if CSS_TAG not in text:
        if "</head>" not in text:
            raise RuntimeError("</head> fehlt")
        text = text.replace("</head>", CSS_TAG + "\n</head>", 1)

    if "switchTab('t850-ensembles')" not in text:
        pos = text.find(NAV_ANCHOR)
        if pos < 0:
            raise RuntimeError("Europa-Navigation als T850-Anker fehlt")
        end = pos + len(NAV_ANCHOR)
        text = text[:end] + "\n          " + NAV_BUTTON + text[end:]

    if PANEL_MARKER not in text:
        footer = '  <footer class="dashboard-footer">'
        if footer not in text:
            raise RuntimeError("Dashboard-Footer als Panel-Marker fehlt")
        text = text.replace(footer, PANEL + "\n\n" + footer, 1)

    if JS_TAG not in text:
        marker = '<script src="sst_europe.js"></script>'
        if marker not in text:
            marker = "<script>\nChart.register(ChartDataLabels);"
        if marker not in text:
            raise RuntimeError("Script-Marker fehlt")
        text = text.replace(marker, JS_TAG + "\n" + marker, 1)

    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="index.html")
    args = parser.parse_args()
    path = Path(args.file)
    original = path.read_text(encoding="utf-8")
    patched = patch_html(original)
    if patched == original:
        print("T850-Ensemble-Frontend bereits eingebaut.")
        return 0
    path.write_text(patched, encoding="utf-8")
    print("T850-Ensemble-Frontend eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
