#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
INDEX=ROOT/"index.html"
BUILD=ROOT/"scripts/build_pages_site.sh"

CSS_TAG='<link rel="stylesheet" href="state_monthly_ensemble.css?v=20261011-1">'
JS_TAG='<script src="state_monthly_ensemble.js?v=20261011-3"></script>'
NAV_ANCHOR='<button class="tab-button" data-nav-group="europe" onclick="switchTab(\'t850-ensembles\')">Ensembles</button>'
NAV_BUTTON='<button class="tab-button" data-nav-group="europe" onclick="switchTab(\'state-monthly-ensemble\')">Monatsausblick</button>'
MARKER='<!-- ================= BUNDESLAND MONATS-ENSEMBLES ================= -->'
NEW_SELECTORS='''    <div class="control-group">
      <label for="stateMonthlyPeriod">Zeitraum</label>
      <select id="stateMonthlyPeriod">
        <option value="month" selected>Laufender Monat</option>
        <option value="season">Meteorologische Jahreszeit</option>
        <option value="year">Laufendes Jahr</option>
      </select>
    </div>
    <div class="control-group">
      <label for="stateMonthlyMetric">Darstellung</label>
      <select id="stateMonthlyMetric">
        <option value="absolute" selected>Temperaturmittel (°C)</option>
        <option value="anomaly">Abweichung 1991–2020 (K)</option>
      </select>
    </div>
'''
VIEW_ANCHOR='    <div class="control-group">\n      <label for="stateMonthlyView">Ansicht</label>'


PANEL=r'''<!-- ================= BUNDESLAND MONATS-ENSEMBLES ================= -->
<div id="state-monthly-ensemble" class="tab-content">
  <div class="section-header state-monthly-header">
    <h2>Monatsausblick · Deutschland & Bundesländer</h2>
    <p>Laufendes 2-m-Temperaturmittel für Monat, Jahreszeit und Jahr: HYRAS-Beobachtungen mit Ensemble-Fortschreibung und Abweichung vom Klimamittel 1991–2020.</p>
    <span class="section-status">HYRAS-DE-TAS · 1991–2020 · Ensemble-Prognose für den laufenden Monat</span>
  </div>

  <div class="controls state-monthly-controls">
    <div class="control-group region">
      <label for="stateMonthlyRegion">Gebiet</label>
      <select id="stateMonthlyRegion"><option>Deutschland</option></select>
    </div>
'''+NEW_SELECTORS+'''    <div class="control-group">
      <label for="stateMonthlyView">Ansicht</label>
      <select id="stateMonthlyView">
        <option value="four" selected>4er-Tafel</option>
        <option value="gefs">GFS / GEFS groß</option>
        <option value="ifs">ECMWF IFS groß</option>
        <option value="aifs">ECMWF AIFS groß</option>
        <option value="icon_eu">ICON-EU EPS groß</option>
      </select>
    </div>
    <button id="stateMonthlyReload" class="state-monthly-secondary" type="button">Neu laden</button>
    <div class="state-monthly-export">
      <button id="stateMonthlyPng" type="button">PNG</button>
      <button id="stateMonthlyPdf" type="button">PDF</button>
    </div>
  </div>

  <div id="stateMonthlyStatus" class="state-monthly-status">Monats-Ensembles werden beim Öffnen geladen …</div>
  <div id="stateMonthlyInfo" class="state-monthly-info"></div>

  <div id="stateMonthlyExportArea" class="state-monthly-export-area">
    <div class="state-monthly-export-head">
      <div>
        <h2 id="stateMonthlyTitle">Deutschland · laufender Monat</h2>
        <p>Laufendes Periodenmittel · Beobachtung + Ensemble-Fortschreibung · Temperatur oder Anomalie</p>
      </div>
    </div>

    <div id="stateMonthlyGrid" class="state-monthly-grid">
      <section class="state-monthly-card" data-model="gefs">
        <div class="state-monthly-model-head"><div><h3>GFS / GEFS</h3><div class="state-monthly-model-meta">Daten werden geladen …</div></div></div>
        <div class="state-monthly-chart-shell"><canvas id="stateMonthlyChart_gefs"></canvas></div>
      </section>
      <section class="state-monthly-card" data-model="ifs">
        <div class="state-monthly-model-head"><div><h3>ECMWF IFS ENS</h3><div class="state-monthly-model-meta">Daten werden geladen …</div></div></div>
        <div class="state-monthly-chart-shell"><canvas id="stateMonthlyChart_ifs"></canvas></div>
      </section>
      <section class="state-monthly-card" data-model="aifs">
        <div class="state-monthly-model-head"><div><h3>ECMWF AIFS ENS</h3><div class="state-monthly-model-meta">Daten werden geladen …</div></div></div>
        <div class="state-monthly-chart-shell"><canvas id="stateMonthlyChart_aifs"></canvas></div>
      </section>
      <section class="state-monthly-card" data-model="icon_eu">
        <div class="state-monthly-model-head"><div><h3>DWD ICON-EU EPS</h3><div class="state-monthly-model-meta">Daten werden geladen …</div></div></div>
        <div class="state-monthly-chart-shell"><canvas id="stateMonthlyChart_icon_eu"></canvas></div>
      </section>
    </div>
    <div id="stateMonthlyLegend" class="state-monthly-legend"></div>
  </div>

  <p class="state-monthly-note">
    Beobachtung und Klimareferenz sind echte HYRAS-DE-TAS-Flächenmittel auf dem 1-km-Gitter.
    Die Ensemble-Prognosen werden in der ersten Version aus mehreren räumlich verteilten Modell-Stützpunkten je Gebiet gemittelt;
    damit ist die Bundesland-Prognose bereits flächenrepräsentativ, aber noch kein natives Modellraster-Flächenmittel.
    Die Abweichung in Kelvin wird für jeden Tag gegen das bis dahin aufgelaufene Klimamittel 1991–2020 berechnet.
    Die Daten werden automatisch viermal täglich aktualisiert.
  </p>
</div>
'''


def patch_index(text: str) -> str:
    if CSS_TAG not in text:
        if "</head>" not in text:
            raise RuntimeError("</head> fehlt")
        text=text.replace("</head>",CSS_TAG+"\n</head>",1)

    if "switchTab('state-monthly-ensemble')" not in text:
        if NAV_ANCHOR not in text:
            raise RuntimeError("Ensemble-Navigationsanker fehlt")
        text=text.replace(NAV_ANCHOR,NAV_ANCHOR+"\n          "+NAV_BUTTON,1)

    if MARKER not in text:
        footer='  <footer class="dashboard-footer">'
        if footer not in text:
            raise RuntimeError("Dashboard-Footer fehlt")
        text=text.replace(footer,PANEL+"\n\n"+footer,1)

    # Bereits veröffentlichte Tabs um die neuen Auswahlfelder ergänzen.
    if 'id="stateMonthlyPeriod"' not in text:
        if VIEW_ANCHOR not in text:
            raise RuntimeError("Monats-Ensemble-Auswahl für Zeitraum nicht gefunden")
        text=text.replace(VIEW_ANCHOR,NEW_SELECTORS+VIEW_ANCHOR,1)

    text=text.replace(
        "Laufendes Monatsmittel · Beobachtung + Ensemble-Fortschreibung",
        "Laufendes Periodenmittel · Beobachtung + Ensemble-Fortschreibung · Temperatur oder Anomalie",
        1,
    )
    text=text.replace(
        "Laufendes 2-m-Temperatur-Monatsmittel aus HYRAS-Beobachtungen, fortgeschrieben mit GFS/GEFS, ECMWF IFS, ECMWF AIFS und DWD ICON-EU EPS.",
        "Laufendes 2-m-Temperaturmittel für Monat, Jahreszeit und Jahr: HYRAS-Beobachtungen mit Ensemble-Fortschreibung und Abweichung vom Klimamittel 1991–2020.",
        1,
    )

    # Auch eine bereits vorhandene, ältere Version aktualisieren:
    # Browser-Caches sollen nach der Achsenkorrektur frisches JS laden.
    old_tag=r'<script src="state_monthly_ensemble\.js(?:\?[^"]*)?"></script>'
    if re.search(old_tag,text):
        text=re.sub(old_tag,lambda _: JS_TAG,text,count=1)
    else:
        anchor='<script src="t850_ensembles.js?v=20260922-7"></script>'
        if anchor not in text:
            raise RuntimeError("T850-Scriptanker fehlt")
        text=text.replace(anchor,JS_TAG+"\n"+anchor,1)

    hook='  if(tab==="europeStations") ensureEuropeStationMap();'
    new_hook=hook+'\n  if(tab==="state-monthly-ensemble") window.ensureStateMonthlyEnsembleLoaded?.();'
    if new_hook not in text:
        if hook not in text:
            raise RuntimeError("switchTab-Hook fehlt")
        text=text.replace(hook,new_hook,1)

    return text


def patch_build(text: str) -> str:
    anchor='  t850_ensembles.css\n'
    addition='  state_monthly_ensemble.js\n  state_monthly_ensemble.css\n'
    if "state_monthly_ensemble.js" not in text:
        if anchor not in text:
            raise RuntimeError("build_pages T850-Anker fehlt")
        text=text.replace(anchor,anchor+addition,1)
    return text


def main() -> int:
    original=INDEX.read_text(encoding="utf-8")
    patched=patch_index(original)
    INDEX.write_text(patched,encoding="utf-8")

    build_original=BUILD.read_text(encoding="utf-8")
    BUILD.write_text(patch_build(build_original),encoding="utf-8")

    print("Bundesland-Monatsensemble-Frontend eingebaut.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
