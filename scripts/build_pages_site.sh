#!/usr/bin/env bash
# Pages artifact schema: ERA5 atmosphere v1
set -euo pipefail

rm -rf _site
mkdir -p _site/data

required_root_files=(
  index.html
  mosmix.html
  datenstatus.html
  dashboard_cleanup.css
  dashboard_theme.css
  dashboard_theme.js
  monthly_layout.js
  stratosphaere.html
  polar_vortex_map.js
  ssw_catalog.js
  zirkulation.html
  blocking.html
  blocking.js
  blocking.css
  isobaren_original.html
  weltweite_isobaren.html
  isobaren_original.js
  synoptic_panel_logic.js
  isobaren_original.css
  synoptic_gallery.js
  synoptic_gallery.css
  dwd_forecast_panel.js
  enso.html
  qbo.html
  mjo.html
  meereis.html
  meereis.js
  meereis.css
  eurasia_snow.html
  eurasia_snow.js
  eurasia_snow.css
  ace.html
  ace.js
  ace_spatial.js
  climate_advanced.js
  climate_indices.js
  climate_indices.css
  stratosphere_temperature.js
  stratosphere_ensemble.js
  stratosphere_ecmwf_runs.js
  stratosphere_winter_stats.js
  stratosphere_gefs_probability.js
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
  wettergefahren_basemap_50m.json
  saisonal_europa.html
  saisonal_europa.js
  saisonal_europa.css
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

# MOSMIX Deutschlandkarte: einen verifizierten, aktuellen Daten-Snapshot direkt
# mit Pages bereitstellen. Damit muss der Browser beim Öffnen keine große
# GitHub-Raw-Datei mehr von einer anderen Domain herunterladen.
# Bei einem temporären GitHub-Ausfall darf Pages trotzdem deployen;
# das Frontend besitzt eigene Rückfallquellen und eine sichtbare Fehlermeldung.
mkdir -p _site/data/mosmix
mosmix_snapshot="_site/data/mosmix/mosmix_ttt.json"
mosmix_source="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/mosmix_ttt.json"
if curl -fsSL --connect-timeout 6 --max-time 100 --retry 1 --max-filesize 120000000 \
  "$mosmix_source" -o "$mosmix_snapshot"; then
  if python - "$mosmix_snapshot" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
obj=json.loads(p.read_text(encoding="utf-8"))
assert obj.get("product")=="DWD MOSMIX-L"
assert len(obj.get("stations",[]))>100
assert len(obj.get("timesteps",[]))>40
assert all(k in obj["stations"][0] for k in ("values","sun1","tx12","tn12"))
import gzip
packed=p.with_suffix(p.suffix+".gz")
with p.open("rb") as source, gzip.open(packed,"wb",compresslevel=7) as dest:
    while True:
        block=source.read(1024*1024)
        if not block: break
        dest.write(block)
assert packed.stat().st_size>0
print("MOSMIX-Deutschlanddatei in Pages eingebunden:",p.stat().st_size,
      "Bytes; komprimiert:",packed.stat().st_size,"Bytes")
PY
  then
    # Manifest zuerst, dann nur die jeweils benötigte Karte pro Tag laden.
    python scripts/build_mosmix_chunks.py "$mosmix_snapshot" _site/data/mosmix
    test -s _site/data/mosmix/manifest.json
    python scripts/audit_mosmix_release.py _site/data/mosmix "$mosmix_snapshot"
    echo "MOSMIX-Deutschlandkarte mit geteilten Tages-/Parameterdateien veröffentlicht."
  else
    rm -f "$mosmix_snapshot" "$mosmix_snapshot.gz"
    echo "WARNUNG: Ungültige MOSMIX-Datei. Frontend nutzt Ersatzquellen."
  fi
else
  rm -f "$mosmix_snapshot" "$mosmix_snapshot.gz"
  echo "WARNUNG: MOSMIX-Snapshot nicht geladen. Frontend nutzt Ersatzquellen."
fi

# Dark Mode muss mit HTML, Stylesheet und Skript gemeinsam ausgeliefert werden.
node --check _site/dashboard_theme.js
# MOSMIX muss auch im Haupt-Website-Deploy syntaktisch valide sein.
node --check _site/mosmix.js
node tests/test_mosmix_world.mjs
node tests/test_mosmix_sun_daily.mjs
node tests/test_mosmix_loader.mjs
node tests/test_mosmix_map_layers.mjs
python -m unittest discover -s tests -p test_mosmix_chunks.py -v
python -m unittest discover -s tests -p test_mosmix_run_compare.py -v
test -s _site/mosmix.html
grep -q 'data-mosmix-standalone="1"' _site/mosmix.html
test -s _site/dashboard_theme.css
test -s _site/dashboard_theme.js
grep -q 'dashboard_theme.css' _site/index.html
grep -q 'dashboard_theme.js' _site/index.html
grep -q 'id="dashboardThemeToggle"' _site/index.html

# Publikationen müssen den neuen SSW-Katalog laden können.
python -m unittest discover -s tests -p test_ssw_catalog.py -v
node --check ssw_catalog.js
node --check stratosphere_ensemble.js
node --check stratosphere_ecmwf_runs.js
node --check stratosphere_winter_stats.js
node --check stratosphere_gefs_probability.js
node --check synoptic_panel_logic.js
node --check isobaren_original.js
node --check synoptic_gallery.js
node --check dwd_forecast_panel.js
node --test tests/test_synoptic_panel_selection.cjs
# Die Seiten dürfen niemals auf Assets verweisen, die im Pages-Build fehlen.
test -s _site/synoptic_gallery.js
test -s _site/synoptic_gallery.css
test -s _site/dwd_forecast_panel.js
grep -q 'data-synoptic-gallery' _site/isobaren_original.html
grep -q 'data-synoptic-gallery' _site/weltweite_isobaren.html
grep -q 'data-dwd-forecast' _site/isobaren_original.html
grep -q 'data-dwd-forecast' _site/weltweite_isobaren.html
python -m unittest discover -s tests -p test_imo_atlantic_probe.py -v
python -m unittest discover -s tests -p test_europe_synoptic_source_audit.py -v
python -m unittest discover -s tests -p test_europe_country_coverage.py -v
python -m unittest discover -s tests -p test_europe_synoptic_viewers.py -v
test -s _site/synoptic_panel_logic.js
test -s _site/ssw_catalog.js
grep -q 'id="sswArchiveCard"' _site/stratosphaere.html
grep -q 'id="stratoEnsembleCard"' _site/stratosphaere.html
grep -q 'id="stratoWinterStatsCard"' _site/stratosphaere.html
grep -q 'id="stratoProbCanvas"' _site/stratosphaere.html
grep -q 'id="stratoModelDiagnostics"' _site/stratosphaere.html
grep -q 'id="windCustomDates"' _site/stratosphaere.html

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
for item in wettergefahren.html wettergefahren.js wettergefahren.css wettergefahren_export.js wettergefahren_basemap.json wettergefahren_basemap_50m.json; do
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

# Eurasia snow observations are stored in the repository and loaded
# from the main branch by the independent NOAA IMS page. No pretend values
# are published if the first background ingestion has not succeeded.
node --check eurasia_snow.js
if [[ -s eurasia_snow/index.json ]]; then
  mkdir -p _site/eurasia_snow
  cp eurasia_snow/index.json _site/eurasia_snow/index.json
  echo "NOAA IMS Eurasien-Schneebedeckung in Pages-Artefakt"
else
  echo "HINWEIS: Erste verifizierte NOAA IMS-Tageswerte noch ausstehend"
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

# Polarwirbelkarte: nur vollständig vorhandene, verifizierte Analyse mitliefern.
# Das neue Modul bleibt bis zum ersten CDS-Erfolg mit ehrlicher Statusmeldung sichtbar.
node --check polar_vortex_map.js
grep -q 'id="polarVortexCard"' _site/stratosphaere.html
if [[ -s data/polar_vortex/current.json && -s data/polar_vortex/polar_vortex_10hpa_current.png ]]; then
  mkdir -p _site/data/polar_vortex
  python - <<'PY'
import json
from pathlib import Path
folder=Path("data/polar_vortex")
meta=json.loads((folder/"current.json").read_text(encoding="utf-8"))
assert meta.get("schema_version")==1 and meta.get("ready") is True
assert meta.get("pressure_hpa")==10 and meta.get("forecast") is False
assert meta.get("image")=="polar_vortex_10hpa_current.png"
assert (folder/"polar_vortex_10hpa_current.png").read_bytes()[:8]==bytes.fromhex("89504e470d0a1a0a")
PY
  cp data/polar_vortex/current.json data/polar_vortex/polar_vortex_10hpa_current.png _site/data/polar_vortex/
  echo "Verifizierte ERA5-Polarwirbelkarte im Pages-Artefakt enthalten."
else
  echo "HINWEIS: Erste ERA5-Polarwirbelkarte noch nicht verfügbar."
fi

# 500-hPa Blocking-Monitor: echte Grafik nur zusammen mit validen Metadaten.
node --check blocking.js
grep -q 'id="blockImage"' _site/blocking.html
if [[ -s data/blocking/current.json && -s data/blocking/blocking_z500_current.png ]]; then
  python - <<'PY'
import json
from pathlib import Path
folder=Path("data/blocking")
meta=json.loads((folder/"current.json").read_text(encoding="utf-8"))
assert meta.get("schema_version")==1 and meta.get("ready") is True
assert meta.get("forecast") is False and meta.get("pressure_hpa")==500
assert meta.get("history_complete") is True and meta.get("days_analysed",0)>=5
assert meta.get("image")=="blocking_z500_current.png"
assert len(meta.get("dates_used",[]))>=5
png=folder/"blocking_z500_current.png"
assert png.read_bytes()[:8]==bytes.fromhex("89504e470d0a1a0a")
PY
  mkdir -p _site/data/blocking
  cp data/blocking/current.json data/blocking/blocking_z500_current.png _site/data/blocking/
  echo "ERA5-Blocking-Karte samt 5-Tage-Diagnose veröffentlicht."
else
  echo "HINWEIS: Erste ERA5-Blocking-Karte noch ausstehend; keine Phantomkarte."
fi

# Originale synoptische Wetterkarten DWD/AEMET/NOAA/ČHMÚ: nur geprüft veröffentlichen.
node --check isobaren_original.js
grep -q 'id="chartGrid"' _site/isobaren_original.html
if [[ -s data/synoptic_charts/index.json ]]; then
  python - <<'PY'
import json
from pathlib import Path
root=Path("data/synoptic_charts")
index=json.loads((root/"index.json").read_text(encoding="utf-8"))
assert index.get("schema_version")==1 and index.get("ready") is True
assert len(index.get("charts",[]))==index.get("chart_count")
for chart in index["charts"]:
    assert chart.get("source_id") in ("dwd","aemet","knmi","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96","noaa_pace","noaa_pacw","noaa_pacfull","noaa_pac24","noaa_pac48","noaa_pac96","chmi","dhmz","imo")
    assert chart["image"].startswith("images/") and chart["image"].endswith(".webp")
    if chart["source_id"] in ("noaa_24","noaa_48","noaa_96"):
        from datetime import datetime,timedelta
        assert datetime.fromisoformat(chart["valid_utc"]) == datetime.fromisoformat(chart["run_utc"]) + timedelta(hours=chart["forecast_hours"])
    if chart["source_id"]=="dhmz":
        assert chart.get("validity_method","").startswith("Printed Croatian")
        assert chart.get("source_url")=="https://prognoza.hr/web_fronte_sutra12.jpg"
    if chart["source_id"]=="imo":
        assert chart.get("map_type")=="isobars_model_forecast_no_fronts"
        assert chart.get("validity_method","").startswith("Printed IMO valid-day caption")
        assert chart.get("source_url","").startswith(("https://en.vedur.is/photos/sjo_atlant_spa/","https://www.vedur.is/photos/sjo_atlant_spa/"))
        from datetime import datetime,timedelta
        assert datetime.fromisoformat(chart["valid_utc"])==datetime.fromisoformat(chart["run_utc"])+timedelta(hours=chart["forecast_hours"])
    if chart["source_id"]=="chmi":
        assert chart.get("validity_method","").startswith("Printed DD.MM.YYYY HH UTC")
        assert chart.get("license_url")=="https://creativecommons.org/licenses/by/4.0/"
    image=root/chart["image"]
    assert image.exists() and image.stat().st_size>18000
    assert image.read_bytes()[:4]==b"RIFF"
PY
  mkdir -p _site/data/synoptic_charts
  cp -a data/synoptic_charts/index.json data/synoptic_charts/images _site/data/synoptic_charts/
  # Obsolete ico_hptfg multi-panel charts must not leak onto the website.
  find _site/data/synoptic_charts/images -type f -name 'dwd_icon_na_*.webp' -delete
  if [[ -s data/synoptic_charts/dwd_tkb.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
root=Path("data/synoptic_charts")
j=json.loads((root/"dwd_tkb.json").read_text(encoding="utf-8"))
assert j["schema_version"]==1 and j["single_map_per_lead"] is True
assert j["products"]==[36,48,60,84,108]
assert j["map_count"]==len(j["maps"])
for m in j["maps"]:
    assert m["source_id"]=="dwd_tkb_original"
    assert m["lead_hours"] in j["products"]
    assert m["source_url"]=="https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/ico_tkboden_na_%03d.png"%m["lead_hours"]
    img=root/m["image"]
    assert img.exists() and img.stat().st_size>18000
    assert img.read_bytes()[:4]==b"RIFF"
PY
    cp data/synoptic_charts/dwd_tkb.json _site/data/synoptic_charts/
    echo "DWD TKB echte Einzel-Isobarenkarten (+36/48/60/84/108 h) veroeffentlicht."
  else
    echo "Keine freigegebenen TKB-Einzelkarten abrufbar; Panel zeigt die Originalquellen."
  fi
  if [[ -s data/synoptic_charts/europe_source_audit.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
p=Path("data/synoptic_charts/europe_source_audit.json")
d=json.loads(p.read_text(encoding="utf-8"))
assert d.get("schema_version")==1 and d.get("no_live_check") is True
assert all(not r.get("reproduction_ready") for r in d.get("providers",[]))
PY
    cp data/synoptic_charts/europe_source_audit.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/rhmz_probe.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
obj=json.loads(Path("data/synoptic_charts/rhmz_probe.json").read_text(encoding="utf-8"))
assert obj["schema_version"]==1 and obj["only_external_links"] is True
assert len(obj["records"])==6
assert all(x["image_reuse_permitted"] is False for x in obj["records"])
PY
    cp data/synoptic_charts/rhmz_probe.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/cyprus_wrf_probe.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
probe=json.loads(Path("data/synoptic_charts/cyprus_wrf_probe.json").read_text(encoding="utf-8"))
assert probe["schema_version"]==1 and probe["no_images_persisted"] is True
assert probe["ready_for_automatic_image_reuse"] is False
assert [r["run_hour_utc"] for r in probe["reports"]]==["00","12"]
PY
    cp data/synoptic_charts/cyprus_wrf_probe.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/worldwide_source_watch.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
data=json.loads(Path("data/synoptic_charts/worldwide_source_watch.json").read_text(encoding="utf-8"))
assert data["schema_version"]==1 and data["source_count"]==9
assert data["no_image_copied"] is True and data["no_automatic_chart_publication"] is True
PY
    cp data/synoptic_charts/worldwide_source_watch.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/russia_kazakhstan_probe.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
obj=json.loads(Path("data/synoptic_charts/russia_kazakhstan_probe.json").read_text(encoding="utf-8"))
assert obj["schema_version"]==1 and obj["no_images_persisted"] is True
assert obj["ready_for_automatic_image_reuse"] is False
assert [x["slot_utc"] for x in obj["russia"]["records"]]==["00","06","12","18"]
PY
    cp data/synoptic_charts/russia_kazakhstan_probe.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/europe_viewer_probe.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
obj=json.loads(Path("data/synoptic_charts/europe_viewer_probe.json").read_text(encoding="utf-8"))
assert obj["schema_version"]==1 and obj["no_auto_ingestion"] is True
assert all(x["ready_for_automatic_charts"] is False for x in obj["sources"])
PY
    cp data/synoptic_charts/europe_viewer_probe.json _site/data/synoptic_charts/
  fi
  if [[ -s data/synoptic_charts/imo_probe.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("data/synoptic_charts/imo_probe.json").read_text(encoding="utf-8"))
assert d["schema_version"]==1 and d["ready_for_automated_chart_ingestion"] is False
PY
    cp data/synoptic_charts/imo_probe.json _site/data/synoptic_charts/

  fi
  echo "Original-Synoptikkarten der Wetterdienste mit UTC-Gültigkeiten veröffentlicht."
else
  echo "HINWEIS: Keine Original-Synoptikkarten publiziert; Seite zeigt transparente Quellenlinks."
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

if [[ -s ace/global.json ]]; then
  mkdir -p _site/ace
  cp ace/global.json _site/ace/global.json
  echo "IBTrACS globale ACE-Daten übernommen."
else
  echo "HINWEIS: IBTrACS-Daten werden durch den globalen ACE-Workflow erzeugt."
fi

if [[ -s ace/spatial/index.json ]]; then
  mkdir -p _site/ace/spatial
  cp ace/spatial/*.json _site/ace/spatial/
  echo "Räumliche ACE-Anomaliekarten (Historienarchiv) veröffentlicht."
else
  echo "HINWEIS: ACE-Kartenarchiv wird beim ersten räumlichen Backfill erzeugt."
fi

touch _site/.nojekyll
echo "Pages-Artefakt erfolgreich gebaut."
echo "Schneehöhenprofile: $(find _site/station_snow_height_profiles -type f -name '*.json' | wc -l) Dateien"
echo "Aktuelle Schneehöhen: $(find _site/station_snow_height_current -type f -name '*.json' | wc -l) Dateien"
echo "Europa-Stationsdaten: $(find _site/europe_stations -type f | wc -l) Dateien"
echo "ERA5-Atmosphäre: $(find _site/era5_europe -type f | wc -l) Dateien"
echo "Dateien gesamt: $(find _site -type f | wc -l)"
du -sh _site
