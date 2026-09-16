#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

CSS_TAG = '<link rel="stylesheet" href="sst_europe.css">'
JS_TAG = '<script src="sst_europe.js"></script>'
BUTTON = '  <button class="tab-button" onclick="switchTab(\'sst-europe\')">Meere / SST</button>\n'
PANEL = '''<!-- ================= MEERE / SST ================= -->
<div id="sst-europe" class="tab-content">
  <div class="section-header sst-europe-header">
    <h2>Meere / SST</h2>
    <p>Tägliche Meeresoberflächentemperatur und Abweichung zum Mittel 1991–2020 für Europa und den Nordatlantik.</p>
    <span class="section-status">NASA/JPL MUR SST v4.1 · NOAA OISST 1991–2020</span>
  </div>
  <div class="controls sst-europe-controls">
    <div class="control-group"><label for="sstRegion">Region</label><select id="sstRegion"></select></div>
    <div class="control-group"><label for="sstView">Ansicht</label><select id="sstView"><option value="absolute">SST absolut</option><option value="anomaly">SST-Anomalie</option></select></div>
    <div class="control-group"><label for="sstDate">Datum</label><input id="sstDate" type="date"></div>
    <div class="sst-europe-date-nav" aria-label="SST Datum wechseln">
      <button type="button" id="sstPrevDay">← Vortag</button>
      <button type="button" id="sstLatestDay">Neuester Tag</button>
      <button type="button" id="sstNextDay">Folgetag →</button>
    </div>
    <div class="sst-europe-export">
      <button type="button" id="sstPngDownload" disabled>PNG</button>
      <button type="button" id="sstPdfDownload" disabled>PDF</button>
    </div>
  </div>
  <div class="sst-europe-card">
    <div class="sst-europe-meta"><strong id="sstDataThrough">Datenstand: –</strong><span>Feste Skalen: SST −2…+34 °C · Anomalie −6…+6 °C</span></div>
    <div class="sst-europe-map-shell">
      <img id="sstMapImage" alt="SST-Karte" crossorigin="anonymous">
      <div id="sstStatus" class="sst-europe-status">SST-Archiv wird geladen …</div>
    </div>
    <div class="sst-europe-timeline-wrap">
      <div class="sst-europe-timeline-label">30 Tage</div>
      <div id="sstTimeline" class="sst-europe-timeline" aria-label="SST Zeitachse"></div>
    </div>
    <p class="sst-europe-source">Aktuelle/historische SST: NASA/JPL MUR SST v4.1. Anomalien: MUR minus NOAA OISST-Tagesklimatologie 1991–2020. Land und stärker meereisbedeckte Zellen werden neutral maskiert.</p>
  </div>
</div>

'''


def patch_html(text: str) -> str:
    if all(marker in text for marker in (CSS_TAG, JS_TAG, 'id="sst-europe"', "switchTab('sst-europe')")):
        return text

    if "</head>" not in text:
        raise RuntimeError("Head-Marker für SST-Styles fehlt.")
    if '<div class="mobile-tab-navigation">' not in text:
        raise RuntimeError("Navigation-Marker für SST-Reiter fehlt.")
    script_marker = "<script>\nChart.register(ChartDataLabels);"
    if script_marker not in text:
        raise RuntimeError("Script-Marker für SST-Frontend fehlt.")

    if CSS_TAG not in text:
        text = text.replace("</head>", f"{CSS_TAG}\n</head>", 1)

    if "switchTab('sst-europe')" not in text:
        pattern = re.compile(r'(<div class="tabs">.*?)(</div>\s*<div class="mobile-tab-navigation">)', re.S)
        match = pattern.search(text)
        if not match:
            raise RuntimeError("Navigation-Block für SST-Reiter konnte nicht gefunden werden.")
        replacement = match.group(1) + BUTTON + match.group(2)
        text = text[:match.start()] + replacement + text[match.end():]

    if 'id="sst-europe"' not in text:
        text = text.replace(script_marker, PANEL + JS_TAG + "\n" + script_marker, 1)
    elif JS_TAG not in text:
        text = text.replace(script_marker, JS_TAG + "\n" + script_marker, 1)

    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="index.html")
    args = parser.parse_args()
    path = Path(args.file)
    original = path.read_text(encoding="utf-8")
    patched = patch_html(original)
    if patched == original:
        print("Meere / SST Frontend bereits eingebaut.")
        return 0
    path.write_text(patched, encoding="utf-8")
    print("Meere / SST Frontend eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
