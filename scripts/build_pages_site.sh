#!/usr/bin/env bash
# Pages artifact schema: ERA5 atmosphere v1
set -euo pipefail

rm -rf _site
mkdir -p _site/data

required_root_files=(
  index.html
  datenstatus.html
  dashboard_cleanup.css
  monthly_layout.js
  stratosphaere.html
  zirkulation.html
  enso.html
  qbo.html
  mjo.html
  meereis.html
  meereis.js
  meereis.css
  ace.html
  ace.js
  climate_advanced.js
  climate_indices.js
  climate_indices.css
  stratosphere_temperature.js
  stratosphere_ssw_comparison.js
  tiefdruck_tracker.html
  tiefdruck_tracker.css
  tiefdruck_phase.js
  tiefdruck_diagnostics.js
  tiefdruck_cps_compare.js
  tiefdruck_tracker.js
  wettergefahren.html
  wettergefahren.js
  wettergefahren.css
  wettergefahren_export.js
  wettergefahren_basemap.json
  sst_europe.js
  sst_europe.css
  t850_ensembles.js
  t850_ensembles.css
  era5_europe.js
  era5_europe.css
  era5_synoptic.js
  era5_synoptic.css
  state_monthly_ensemble.js
  state_monthly_ensemble.css
  monthly_frequency.js
  mosmix.js
  station_thresholds.js
  dwd_station_daily_map.js
  dwd_station_daily_map.css
  hyras_historical_temperature_1km.js
  dekadenrekorde.html
  jahresextremwerte.html
  feiertagsextremwerte.html
  data.json
  daily_tmax_1881_2026.json
  station_records.json
  station_precip_index.json
  station_climate_days_index.json
  station_heatwaves_index.json
  station_heatwaves_current.json
  station_snow_height_index.json
  station_snow_height_current_index.json
  update_status.json
)

for file in "${required_root_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "FEHLER: Für GitHub Pages fehlt: $file"
    exit 1
  fi
  cp "$file" _site/
done

# Das Layout der Stratosphären-Seite muss trotz ausgeblendeter Heatmap
# seine Erklärung sichtbar im veröffentlichten HTML behalten.
python - <<'PY'
from pathlib import Path
page = Path("_site/stratosphaere.html").read_text(encoding="utf-8")
expected = (
    'id="levelsCard"',
    'class="card method"',
    'id="heatmapCard"',
    'id="sswEventsCard"',
)
positions = [page.find(key) for key in expected]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("FEHLER: Stratosphären-Erklärung ist nicht VOR der versteckten Heatmap.")
for text in ("Warum 60° N und 10 hPa?", "Datengrundlage und Aktualisierung"):
    if text not in page:
        raise SystemExit("FEHLER: Fehlender sichtbarer Erklärtext: "+text)
if "main > section.card.method {display:grid !important;}" not in page:
    raise SystemExit("FEHLER: Sichtbarkeitsregel der Stratosphären-Erklärung fehlt.")
print("Stratosphäre: Erläuterung direkt nach den Winddiagrammen im Pages-Artefakt geprüft.")
PY

# Schneehöhen werden direkt mit GitHub Pages veröffentlicht. Damit hängt der
# Stationsbereich nicht von separaten Raw-GitHub-Requests ab und ein grüner
# Pages-Deploy garantiert, dass Index, Profile und aktuelle Saison zusammenpassen.
required_snow_dirs=(
  station_snow_height_profiles
  station_snow_height_current
)

for dir in "${required_snow_dirs[@]}"; do
  if [[ ! -d "$dir" ]] || [[ -z "$(find "$dir" -maxdepth 1 -type f -name '*.json' -print -quit)" ]]; then
    echo "FEHLER: Für GitHub Pages fehlen Schneehöhen-Dateien in: $dir"
    exit 1
  fi
  cp -a "$dir" _site/
done

# index.html leitet große Stationsdateien normalerweise auf raw.githubusercontent
# um. Für Schnee liegen die Dateien jetzt bewusst im Pages-Artefakt und werden
# deshalb same-origin geladen.
python - <<'PY'
from pathlib import Path

path = Path("_site/index.html")
text = path.read_text(encoding="utf-8")
entries = [
    '  "station_snow_height_index.json",\n',
    '  "station_snow_height_current_index.json",\n',
    '  "station_snow_height_profiles/",\n',
    '  "station_snow_height_current/",\n',
]
for entry in entries:
    if entry not in text:
        raise SystemExit(f"FEHLER: Snow-Raw-Prefix fehlt in index.html: {entry.strip()}")
    text = text.replace(entry, "", 1)
path.write_text(text, encoding="utf-8")
PY

required_data_files=(
  data/dwd_decade_records.json
  data/dwd_decade_snow_records.json
  data/dwd_decade_pressure_records.json
  data/dwd_annual_extremes.json
  data/dwd_holiday_extremes.json
)

for file in "${required_data_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "FEHLER: Für GitHub Pages fehlt: $file"
    exit 1
  fi
  cp "$file" "_site/data/$(basename "$file")"
done

# Dekadenrekorde · Tagesniederschlag. Die Datenbasis wird in einem separaten
# DWD-RR-Workflow erzeugt und nach erfolgreichem Lauf hier mit veröffentlicht.
if [[ -s data/dwd_decade_precip_records.json ]]; then
  cp data/dwd_decade_precip_records.json _site/data/
  echo "Niederschlags-Dekadenrekorde in Pages-Artefakt übernommen."
else
  echo "HINWEIS: data/dwd_decade_precip_records.json ist noch nicht vorhanden."
fi

# Geschützter Alpenwetter-Bereich: Die URL selbst ist nicht vertraulich.
# Sie wird nach erfolgreichem Cloudflare-Deploy automatisch erzeugt.
if [[ -s data/alpenwetter_endpoint.json ]]; then
  cp data/alpenwetter_endpoint.json _site/data/
  echo "Alpenwetter-Endpunkt in Pages-Artefakt übernommen."
else
  echo "HINWEIS: data/alpenwetter_endpoint.json ist noch nicht vorhanden."
fi

# ERA5 Atmosphäre Europa: Frontend und erzeugte Karten/Indizes werden
# same-origin mit GitHub Pages veröffentlicht.
if [[ ! -s era5_europe/index.json ]]; then
  echo "FEHLER: Für GitHub Pages fehlt: era5_europe/index.json"
  exit 1
fi
if [[ ! -d era5_europe/maps ]] || [[ -z "$(find era5_europe/maps -maxdepth 1 -type f -name '*.png' -print -quit)" ]]; then
  echo "FEHLER: Für GitHub Pages fehlen ERA5-Atmosphärenkarten."
  exit 1
fi
cp -a era5_europe _site/
echo "ERA5-Atmosphäre in Pages-Artefakt übernommen."

# Eigenständige ERA5-Stratosphärendiagnostik: nur verifizierte JSON-Tagesdaten.
# Keine Daten generieren oder extrapolieren; die Quelle wird über GitHub Actions befüllt.
if [[ -s era5_stratosphere/index.json ]]; then
  mkdir -p _site/era5_stratosphere
  cp era5_stratosphere/index.json _site/era5_stratosphere/index.json
  echo "ERA5-Stratosphäre Index in Pages-Artefakt übernommen."
  if [[ -s era5_stratosphere/backfill_status.json ]]; then
    cp era5_stratosphere/backfill_status.json _site/era5_stratosphere/backfill_status.json
    echo "ERA5-Backfillstatus mit realen Abdeckungszahlen veröffentlicht."
  fi
else
  echo "HINWEIS: ERA5-Stratosphäre Index fehlt, Frontend verwendet GitHub-Raw-Fallback."
fi

# Europa-Stationskarte: Der komplette veröffentlichte Datenordner wird benötigt.
# index.html lädt europe_stations/index.json direkt beim Seitenstart; die
# Tages-/Kalenderarchive liegen darunter in europe_stations/calendar/.
if [[ ! -s europe_stations/index.json ]]; then
  echo "FEHLER: Für GitHub Pages fehlt: europe_stations/index.json"
  exit 1
fi
if [[ ! -s europe_stations/calendar/01-01.json.gz ]]; then
  echo "FEHLER: Für GitHub Pages fehlt: europe_stations/calendar/01-01.json.gz"
  exit 1
fi
if [[ ! -s europe_stations/calendar/12-31.json.gz ]]; then
  echo "FEHLER: Für GitHub Pages fehlt: europe_stations/calendar/12-31.json.gz"
  exit 1
fi
cp -a europe_stations _site/

for item in tiefdruck_tracker.html tiefdruck_tracker.js tiefdruck_tracker.css; do
  test -s "_site/$item" || { echo "FEHLER: Tracker-Datei $item fehlt im Pages-Artefakt"; exit 1; }
done
echo "Tiefdruck-Tracker HTML, CSS und JavaScript im Pages-Artefakt enthalten."
for item in wettergefahren.html wettergefahren.js wettergefahren.css wettergefahren_export.js wettergefahren_basemap.json; do
  test -s "_site/$item" || { echo "FEHLER: ICON-EU-Gefahrenmonitor-Datei $item fehlt."; exit 1; }
done
echo "ICON-EU-Gefahrenmonitor HTML, CSS und JavaScript im Pages-Artefakt enthalten."
# Historische Stationstemperaturen werden separat und nur bei Bedarf geladen.
# Vor dem erstmaligen DWD-Backfill bleibt die Funktion mit Statusmeldung sichtbar.
if [[ -d station_threshold_daily ]] && [[ -n "$(find station_threshold_daily -maxdepth 1 -type f -name '*.json' -print -quit)" ]]; then
  cp -a station_threshold_daily _site/
  echo "Stations-Schwellenwerte: $(find _site/station_threshold_daily -type f -name '*.json' | wc -l) Stationsarchive."
else
  echo "HINWEIS: Stations-Schwellenwert-Tagesarchiv wird erst beim DWD-Backfill erzeugt."
fi

# Die NOAA/CPC-Tages- und ENSO-Indizes werden durch einen eigenen
# täglichen Workflow geladen. Vor dem Erstlauf zeigen die Seiten einen
# klaren Archivstatus statt erfundene oder veraltete Indexwerte.
if [[ -s climate_indices/index.json ]]; then
  mkdir -p _site/climate_indices
  cp climate_indices/index.json _site/climate_indices/index.json
  echo "NOAA-Zirkulations- und ENSO-Indizes in Pages-Artefakt übernommen."
else
  echo "HINWEIS: NOAA-Indexarchiv noch nicht erstellt."
fi

# NSIDC daily sea ice v4: compact 1978-present extent and 1991–2020
# climatology. First deploy can render a status until initial backfill finishes.
if [[ -s sea_ice/index.json ]]; then
  mkdir -p _site/sea_ice
  cp sea_ice/index.json _site/sea_ice/index.json
  echo "NSIDC Arktis/Antarktis Daten im Pages-Artefakt enthalten."
else
  echo "HINWEIS: NSIDC-Archiv wird durch den ersten Meereis-Workflow erzeugt."
fi

# Generiere öffentliche Datenstände aus den tatsächlich veröffentlichten
# Archiv-Metadaten. Keine GitHub-API im Browser für die Datenabdeckung nötig.
python -m unittest discover -s tests -p 'test_data_status.py' -v
python - <<'PY'
from pathlib import Path
page=Path("datenstatus.html").read_text(encoding="utf-8")
assert '<script>' in page and '</script>' in page
Path("/tmp/climate-data-status-check.js").write_text(page.split("<script>",1)[1].split("</script>",1)[0], encoding="utf-8")
PY
node --check /tmp/climate-data-status-check.js
python scripts/build_data_status.py --output _site/data/status/status.json
test -s _site/data/status/status.json || { echo "FEHLER: Datenstatus fehlt"; exit 1; }

if [[ -s ace/index.json ]]; then
  mkdir -p _site/ace
  cp ace/index.json _site/ace/index.json
  echo "NHC ACE-Daten übernommen."
else
  echo "HINWEIS: ACE-Daten werden beim ersten HURDAT2-Import erstellt."
fi

touch _site/.nojekyll
echo "Pages-Artefakt erfolgreich gebaut."
echo "Schneehöhenprofile: $(find _site/station_snow_height_profiles -type f -name '*.json' | wc -l) Dateien"
echo "Aktuelle Schneehöhen: $(find _site/station_snow_height_current -type f -name '*.json' | wc -l) Dateien"
echo "Europa-Stationsdaten: $(find _site/europe_stations -type f | wc -l) Dateien"
echo "ERA5-Atmosphäre: $(find _site/era5_europe -type f | wc -l) Dateien"
echo "Dateien gesamt: $(find _site -type f | wc -l)"
du -sh _site
