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
  dashboard_export_hq.js
  mobile_navigation.css
  mobile_navigation.js
  mobile_content.css
  mobile_content.js
  europe_station_basemap.js
  station_snow_years.js
  station_snow_accumulation.js
  station_snow_explorer.js
  station_snow_explorer.css
  station_jahresanalyse.html
  station_jahresanalyse.js
  station_jahresanalyse.css
  monthly_layout.js
  monthly_climate_bars.js
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
  arktis_temperatur.html
  arktis_temperatur.js
  arktis_era5_maps.js
  arktis_era5_sync.js
  arktis_klimastatistik.js
  arktis_statistik.js
  arktis_temperatur.css
  groenland_stationen.html
  groenland_stationen.js
  groenland_climate.js
  groenland_stationen.css
  eurasia_snow.html
  eurasia_snow.js
  eurasia_snow.css
  snow_maps.js
  ace.html
  ace.js
  ace_spatial.js
  climate_advanced.js
  climate_indices.js
  nao_ao_forecast.js
  ecmwf_teleconnections.js
  nao_ao_maps.js
  climate_indices.css
  stratosphere_temperature.js
  stratosphere_ensemble.js
  stratosphere_chart_visibility.js
  stratosphere_chart_export.js
  stratosphere_joint_comparison.js
  stratosphere_joint_comparison.css
  stratosphere_nasa_common.js
  stratosphere_analysis_forecast.js
  stratosphere_analysis_forecast.css
  stratosphere_comparison_metrics.js
  stratosphere_vertical_profile.js
  stratosphere_chart_visibility.css
  stratosphere_ecmwf_runs.js
  stratosphere_ecmwf_ens.js
  stratosphere_run_trends.js
  stratosphere_reversal_diagnostics.js
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
  saharastaub.html
  saharastaub.css
  saharastaub.js
  saharastaub_extended.js
  satelliten.html
  satelliten.js
  satelliten.css
  satellite_overlay.js
  satellite_lightning.js
  satellite_radar.js
  satellite_view_options.js
  satellite_hd.js
  satellite_isobar_geometry.js
  satellite_isobars.js
  satellite_map_export.js
  satellite_film_export.js
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
  mosmix_vector_export.js
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

# Phase 2: bust old cached Gebietsmittel styles/scripts in published Pages.
# The source index stays intact for unrelated work and its huge file need not
# be rewritten by this update. Only the built artifact receives the new tag.
python - <<'PY'
from pathlib import Path
import re
page=Path("_site/index.html")
html=page.read_text(encoding="utf-8")
for name in ("dashboard_cleanup.css","monthly_climate_bars.js"):
    suffix="20261112-phase2-climate-key-v3"
    expression=re.escape(name)+r"(?:\?v=[A-Za-z0-9_.-]+)?"
    html,count=re.subn(expression,name+"?v="+suffix,html)
    if count!=1:
        raise SystemExit(f"Phase 2 asset reference ambiguous: {name} ({count})")
# Both HQ chart exports and the model-specific exports use the same
# readable source/date imprint regardless of desktop/mobile or dark mode.
html,hq_refs=re.subn(r"dashboard_export_hq[.]js(?:[?]v=[A-Za-z0-9_.-]+)?",
                      "dashboard_export_hq.js?v=20261112-phase2-print-v1",html)
if not hq_refs:
    raise SystemExit("Phase 2: HQ chart exporter is not referenced in the main dashboard")
page.write_text(html,encoding="utf-8")
print("Phase 2: Klimarot & Blau and branded HQ exporter published.")
PY

# Publish only verified ECMWF forecast-derived pressure contours; if its
# independent data workflow has not succeeded yet, keep the satellite
# control visible but explicitly unavailable (never fabricate a pressure map).
if [[ -s data/satellite_mslp/latest.json ]]; then
  mkdir -p _site/data/satellite_mslp
  cp data/satellite_mslp/latest.json _site/data/satellite_mslp/latest.json
  # Fast vector display: preserve full-resolution JSON for original download
  # while serving accurately simplified and cropped pressure paths to browsers.
  python scripts/build_satellite_isobar_preview.py \
    --input data/satellite_mslp/latest.json \
    --output _site/data/satellite_mslp/preview.json
  # 10-minute MSLP isobars are generated from official IFS pressure fields,
  # then pre-contoured and partitioned by hour for instant satellite playback.
  if [[ -s data/satellite_mslp/ten_minute/index.json ]]; then
    python - <<'PY'
import json
from pathlib import Path
p=Path("data/satellite_mslp/ten_minute")
idx=json.loads((p/"index.json").read_text(encoding="utf-8"))
raw=json.loads(Path("data/satellite_mslp/latest.json").read_text(encoding="utf-8"))
assert idx["schema_version"]==2 and idx["run_utc"]==raw["run_utc"]
assert len(idx["hours"]) in (13,19) and idx["time_resolution_minutes"]==10
assert all((p/file).is_file() for file in idx["hours"].values())
# Legacy archives remain publishable until their next genuine ECMWF update.
if "fine_hours" in idx:
    assert idx["fine_interval_hpa"]==2
    assert set(idx["fine_regions"])=={"europe","southwest","central","germany"}
    assert len(idx["fine_hours"])==len(idx["hours"])
    assert all((p/file).is_file() for file in idx["fine_hours"].values())
PY
    cp -R data/satellite_mslp/ten_minute _site/data/satellite_mslp/
  fi
fi

# MOSMIX UI cache version: the main dashboard and the standalone view must
# load the same newly published JS. Merely updating the standalone page is
# insufficient when visitors reach MOSMIX from index.html.
python - <<'PY'
from pathlib import Path
import re
for name in ("index.html","mosmix.html"):
    page=Path("_site")/name
    html=page.read_text(encoding="utf-8")
    updated,count=re.subn(r"mosmix\.js(?:\?v=[A-Za-z0-9_.-]+)?",
                           "mosmix.js?v=20261111-svg-vector-live-v2",html)
    if count:
        page.write_text(updated,encoding="utf-8")
        print(f"MOSMIX cache version in {name}: {count} reference(s)")
    else:
        print(f"MOSMIX: no direct script reference in {name}; dynamic loader unaffected.")
PY

# Phase 1: compact station-year catalogue and independent comparison page.
# Avoid loading 4+ MB of station indices just to show station suggestions.
python scripts/build_station_jahresanalyse_catalog.py _site/station_jahresanalyse_catalog.json
node --check _site/station_jahresanalyse.js
python - <<'PY'
from pathlib import Path
import json
root=Path("_site")
page=root/"index.html"
source=page.read_text(encoding="utf-8")
anchor = '<button class="tab-button" data-nav-group="stations" onclick="switchTab(\'stationProfile\')">Stationsprofil</button>'
addition = '<a class="tab-button" data-nav-group="stations" href="station_jahresanalyse.html">Stations-Jahresdiagramme</a>'
if source.count(anchor)!=1:
    raise SystemExit("Stationsprofil-Navigationsanker fehlt oder ist nicht eindeutig")
source=source.replace(anchor,anchor+"\n          "+addition,1)
page.write_text(source,encoding="utf-8")
catalog=json.loads((root/"station_jahresanalyse_catalog.json").read_text(encoding="utf-8"))
assert catalog["schema"]==1 and catalog["totals"]["temp"]>=50
assert catalog["totals"]["precip"]>=100
assert '["station_jahresanalyse.html","Jahresdiagramme · DWD-Stationen"]' in (root/"mobile_navigation.js").read_text(encoding="utf-8")
assert 'src="station_jahresanalyse.js?v=4"' in (root/"station_jahresanalyse.html").read_text(encoding="utf-8")
print("Jahresanalyse im Desktop- und Handymenü, Datenarchiv geprüft.")
PY

# Optimize the biggest first-use station archive without modifying any values.
# A 13.4 MB indented source index becomes ~4.9 MB as compact JSON; future
# updater runs also write it compactly. This prevents waiting for the next
# scheduled DWD refresh before the published page gets the improvement.
python - <<'PY'
import json
from pathlib import Path
path=Path("_site/station_precip_index.json")
original=path.stat().st_size
payload=json.loads(path.read_text(encoding="utf-8"))
assert payload.get("ready") and len(payload.get("stations") or []) >= 500
with path.open("w",encoding="utf-8") as handle:
    json.dump(payload,handle,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    handle.write("\n")
print("Stationsniederschlag-Index:",original,"->",path.stat().st_size,"Byte (verlustfrei)")
PY
node --check _site/dashboard_export_hq.js
# Reuse the existing validated 1:50m Natural Earth geometry for satellite
# coastlines and borders; local asset avoids a fragile third-party tile server.
python - <<'PY'
import json
from pathlib import Path
src=Path("data/blocking/borders_50m.json")
obj=json.loads(src.read_text(encoding="utf-8"))
assert obj["schema_version"]==1 and len(obj["lines"])>=300
assert obj["coverage_bbox"][0]<=-70 and obj["coverage_bbox"][2]>=35
assert "Natural Earth" in obj["source"]
PY
mkdir -p _site/data/blocking
cp data/blocking/borders_50m.json _site/data/blocking/borders_50m.json
# Fallback for browser CORS: only publish satellite timestamps checked by the
# independent EUMETSAT live probe; never create fake status if absent.
if [[ -s data/satellite_layer_discovery_latest.json ]]; then
  cp data/satellite_layer_discovery_latest.json _site/data/satellite_layer_discovery_latest.json
fi
if [[ -s data/satellite_wms_times.json ]]; then
  cp data/satellite_wms_times.json _site/data/satellite_wms_times.json
  python - <<'PY'
import json
from pathlib import Path
status=json.loads(Path("_site/data/satellite_wms_times.json").read_text(encoding="utf-8"))
assert status.get("schema")==1 and status.get("provider")=="EUMETSAT"
assert all(k in status.get("products",{}) for k in ("geocolour","dust","cloudtype"))
print("EUMETSAT WMS-Status mit tatsächlichen Verifikationen eingebunden.")
PY
else
  echo "Hinweis: Der automatische EUMETSAT-WMS-Check ist noch nicht abgeschlossen."
fi


# Last-good EUMETSAT images: only publish actual verified PNG files and their
# manifest. Never create a placeholder or substitute made-up satellite data.
if [[ -s data/satellite_cache/index.json ]]; then
  mkdir -p _site/data/satellite_cache
  cp data/satellite_cache/index.json _site/data/satellite_cache/index.json
  python - <<'PY'
import json, shutil
from pathlib import Path
source=Path("data/satellite_cache")
target=Path("_site/data/satellite_cache")
doc=json.loads((source/"index.json").read_text(encoding="utf-8"))
assert doc.get("schema")==1 and doc.get("provider")=="EUMETSAT WMS"
count=0
for product, regions in doc.get("entries",{}).items():
    for region,entry in regions.items():
        filename=f"{product}_{region}_{entry['time'].replace('-', '').replace(':', '')}.png"
        assert entry.get("url")==f"./data/satellite_cache/{filename}"
        origin=source/filename
        if not origin.is_file() or not origin.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit(f"Invalid cached satellite image: {filename}")
        shutil.copy2(origin,target/filename)
        count+=1
print(f"EUMETSAT: {count} real last-good PNG snapshots in Pages artifact.")
PY
fi

# Arktischer DMI-Index wird im täglichen Spezialworkflow erzeugt.
# Die erste Veröffentlichung darf nicht durch eine noch ausstehende
# Datenberechnung blockiert werden; die Seite zeigt den Status transparent.
if [[ -s data/arctic80_temperature.json ]]; then
  cp data/arctic80_temperature.json _site/data/arctic80_temperature.json
  python - <<'PY'
import json
from pathlib import Path
obj=json.loads(Path("_site/data/arctic80_temperature.json").read_text(encoding="utf-8"))
assert obj["schema"]==1
assert obj["days"][59]=="02-29"
assert len(obj["days"])==366
assert len(obj["years"])>=60
assert len(obj["reference"]["temperatures"])==366
print("DMI-Temperaturindex als lokale Pages-Datenquelle bereitgestellt:",obj["last_date"])
PY
else
  echo "Hinweis: DMI-Temperaturindex wird noch über täglichen Datenimport erzeugt."
fi
node --check _site/arktis_temperatur.js
node --check _site/arktis_era5_maps.js
node --check _site/arktis_era5_sync.js
node --check tests/test_arctic_era5_archive_ui.cjs
node --test tests/test_arctic_era5_archive_ui.cjs
grep -q 'id="arcticEra5MapPanel"' _site/arktis_temperatur.html
grep -q 'src="arktis_era5_sync.js?v=1"' _site/arktis_temperatur.html
for el in arcticEra5CompareEnabled arcticEra5CompareGrid arcticEra5CompareDate arcticEra5SyncStatus; do
  grep -q "id=\"$el\"" _site/arktis_temperatur.html || { echo "DMI/ERA5 Vergleich fehlt: $el"; exit 1; }
done

# Publish only VERIFIED real Copernicus ERA5 polar-cap fields; never synthetic maps.
if [[ -s data/arctic_era5_maps/index.json ]]; then
  mkdir -p _site/data/arctic_era5_maps
  cp data/arctic_era5_maps/index.json _site/data/arctic_era5_maps/index.json
  python - <<'PY'
import json
import re
import shutil
from pathlib import Path
root=Path("data/arctic_era5_maps")
site=Path("_site/data/arctic_era5_maps")
doc=json.loads((root/"index.json").read_text(encoding="utf-8"))
assert doc.get("schema") in (1,2)
if doc.get("ready") is True:
    assert doc.get("reference_period")=="1991-2020"
    assert doc.get("forecast") is False
    assert doc.get("anomaly_reference")=="monthly_mean_same_calendar_month"
    rows=doc.get("days",[])
    assert rows and all(row["date"]<=doc["latest_date"] for row in rows)
    if doc["schema"] == 2:
        assert doc.get("target_days")==30
        assert doc.get("regions")==[80,70,60]
        assert doc.get("archive_policy") in ("append_only",None)
    files=set()
    for row in rows:
        regions=row.get("regions",{}) if doc["schema"]==2 else {"80":row}
        assert regions
        for region,entry in regions.items():
            assert region in {"80","70","60"}
            assert entry.get("boundary_version") in (2,3)
            for field in ("mean_c","mean_anomaly_k"):
                import math
                assert math.isfinite(float(entry[field]))
            for key in ("temperature_png","anomaly_png"):
                name=entry[key]
                assert re.fullmatch(r"maps/(t2m|anomaly)_(?:(60|70|80)n_)?\d{8}\.png",name)
                files.add(name)
    assert files
    for name in sorted(files):
        path=root/name
        assert path.is_file() and path.stat().st_size>25000
        with path.open("rb") as stream:
            assert stream.read(8)==bytes.fromhex("89504e470d0a1a0a")
        destination=site/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination)
    print("ERA5-Arktisarchiv:",len(rows),"echte Tage,",
          len(files),"geprüfte PNG-Karten","(v"+str(doc["schema"])+")")
else:
    assert not doc.get("days"),"Invalid ERA5 archive: unready with days"
    print("ERA5-Arktiskarten: Archiv noch ohne verifizierte Tageswerte")
PY
fi
# DMI Greenland monitor: ship both source and verified cache with genuine Greenland station coordinates.
node --check _site/groenland_stationen.js
node --check _site/groenland_climate.js
if [[ -s data/dmi_greenland_records.json ]]; then
  cp data/dmi_greenland_records.json _site/data/dmi_greenland_records.json
  python scripts/build_dmi_greenland_records.py --check
fi
if [[ -s data/dmi_greenland_stations.json ]]; then
  cp data/dmi_greenland_stations.json _site/data/dmi_greenland_stations.json
  python scripts/build_dmi_greenland_stations.py --check
fi
grep -q 'id="grMap"' _site/groenland_stationen.html
grep -q 'src="groenland_stationen.js?v=2"' _site/groenland_stationen.html
grep -q 'src="groenland_climate.js?v=1"' _site/groenland_stationen.html
for element in grClimate grClimateStatus grClimateChart grMapMode grMapRankingList grMapStationRanks; do
  grep -q "id=\"$element\"" _site/groenland_stationen.html || { echo "DMI Grönland fehlt: $element"; exit 1; }
done
node --check tests/test_dmi_greenland_ui.cjs
node --test tests/test_dmi_greenland_ui.cjs
node --check tests/test_dmi_greenland_climate.cjs
node --test tests/test_dmi_greenland_climate.cjs
node --check _site/arktis_klimastatistik.js
node --check tests/test_arctic_longterm_seasons.cjs
node --test tests/test_arctic_longterm_seasons.cjs
node --check _site/arktis_statistik.js
node --check tests/test_arctic_temperature_ui.cjs
grep -q 'window.Arctic80StatsMath' _site/arktis_temperatur.js
node --test tests/test_arctic_temperature_ui.cjs
node --check tests/test_arctic_streaks.cjs
node --test tests/test_arctic_streaks.cjs
node --check tests/test_arctic_extreme_visuals.cjs
node --test tests/test_arctic_extreme_visuals.cjs
# Fail fast when published HTML references a missing Arctic statistics asset.
# Statistics are bundled in arktis_temperatur.js; HTML must load only that script.
if grep -q 'src="arktis_statistik.js' _site/arktis_temperatur.html; then
  echo 'FEHLER: Veraltete externe DMI-Statistikdatei wird noch eingebunden.'
  exit 1
fi
test -s _site/arktis_statistik.js

# Optionalen vorläufigen HYRAS-Monatsstand für Same-Origin-Ladezeit einpacken.
# Ein fehlender Datenbranch blockiert NICHT die historischen Diagramme.
monthly_snapshot="_site/monthly_current_provisional.json"
monthly_source="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-data/monthly_current_provisional.json"
if curl -fsSL --connect-timeout 5 --max-time 40 --retry 1 "$monthly_source" -o "$monthly_snapshot"; then
  if python - "$monthly_snapshot" <<'PY'
import json,sys
from datetime import datetime
data=json.load(open(sys.argv[1],encoding="utf-8"))
assert data["schema"]==1 and data["forecast"] is False
assert len(data["areas"])>=17 and data["data_through"].startswith(data["month"])
assert data["days_observed"]<=data["days_in_month"]
assert all("temp" in data["areas"][k] and "rain" in data["areas"][k] for k in ["Deutschland","Hessen"])
print("Vorläufiger HYRAS-Monat für Pages:",data["month"],data["data_through"])
PY
  then
    echo "HYRAS-Vormonatsstatus für Gebietsmittel eingebunden."
  else
    rm -f "$monthly_snapshot"
    echo "WARNUNG: Vorläufige HYRAS-Monatsdatei ungültig."
  fi
else
  rm -f "$monthly_snapshot"
  echo "HINWEIS: Vorläufige HYRAS-Monatsdatei noch nicht verfügbar."
fi

# Zwei Monatsstände parallel halten: der gerade laufende Monat und der vorige,
# bis alle dazugehörigen offiziellen DWD-Monatswerte vorliegen.
monthly_history="_site/monthly_provisional_history.json"
monthly_history_url="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-data/monthly_provisional_history.json"
if curl -fsSL --connect-timeout 5 --max-time 40 --retry 1 "$monthly_history_url" -o "$monthly_history"; then
  if python - "$monthly_history" <<'PY'
import json,sys
history=json.load(open(sys.argv[1],encoding="utf-8"))
assert history["schema"]==1 and history["forecast"] is False
assert isinstance(history["months"],list) and history["months"]
for month in history["months"]:
    assert month["schema"]==1 and month["forecast"] is False
    assert month["month"]==month["data_through"][:7]
    assert len(month["areas"])>=17
print("HYRAS-Beobachtungsmonate:",[month["month"] for month in history["months"]])
PY
  then
    echo "Vorläufige Monats-Historie für Pages eingebunden."
  else
    rm -f "$monthly_history"
    echo "WARNUNG: Vorläufige Monats-Historie ungültig; Rohdaten-Fallback bleibt aktiv."
  fi
else
  rm -f "$monthly_history"
  echo "HINWEIS: Vorläufiges Monatsarchiv noch nicht erzeugt."
fi

# Der HYRAS-Balken muss im historischen Chart selbst eingebaut sein.
python - <<'PY'
from pathlib import Path
s=Path("_site/index.html").read_text(encoding="utf-8")
for marker in ("function observedMonthlyBar(", "function observedMonthlyHatch(", 'id="monthlyObservedChartNote"', 'label:`${observed.year} vorläufig'):
    assert marker in s, "Vorläufiger HYRAS-Monatsbalken fehlt: "+marker
assert "monthly_provisional.js" not in s, "Veraltetes separates Overlay noch geladen"
print("HYRAS-Vormonat im Gebietsmittel-Hauptdiagramm verankert.")
PY

# Saharastaub ist direkt im Menü „Sonstiges“ eingebunden (Desktop und Mobil).
# Kein globaler Header-Banner und kein separater Menüeintrag unter Europa.
python - <<'PY'
from pathlib import Path
page=Path("_site/index.html").read_text(encoding="utf-8")
nav=Path("_site/mobile_navigation.js").read_text(encoding="utf-8")
assert "window.location.href='saharastaub.html'" in page
assert 'data-nav-group="misc" type="button" onclick="window.location.href=\'saharastaub.html\'"' in page
assert '["saharastaub.html","Sonstiges · Saharastaub-Monitor (ICON-ART-EU)"]' in page
assert 'name:"Sonstiges",items:' in nav
assert nav.count('["saharastaub.html","Saharastaub · ICON-ART"]')==1
assert "saharastaub-quicklink" not in page
print("Saharastaub ist ausschließlich im Menü Sonstiges verlinkt.")
PY

# Ein einziges Handymenü auf allen veröffentlichten HTML-Seiten.
# Desktop bleibt unverändert; keine individuellen Seiteninhalte werden verändert.
python scripts/inject_mobile_navigation.py _site
node --check _site/satelliten.js
node --check _site/satellite_overlay.js
node --check _site/satellite_lightning.js
node --check _site/satellite_radar.js
node --check _site/satellite_view_options.js
node --check _site/satellite_hd.js
node --check _site/satellite_isobars.js
node --check _site/satellite_film_export.js
node --test tests/test_satellite_isobars.cjs
node --test tests/test_satellite_film_export.cjs
node --test tests/test_satellite_overlay.cjs
node --test tests/test_satelliten_ui.cjs
node --test tests/test_satellite_phase12.cjs
node --test tests/test_satellite_source_alignment.cjs
node --test tests/test_satellite_hd.cjs
node --test tests/test_satellite_film.cjs
grep -Eq 'src="satelliten[.]js([?][^"]*)?"' _site/satelliten.html
node --check _site/saharastaub.js
node --test tests/test_saharastaub_ui.cjs
node --test tests/test_monthly_observed_chart.cjs
node --check _site/mobile_navigation.js
node --test tests/test_hyras_current_month_ui.cjs
node --test tests/test_mobile_navigation.cjs
node --check _site/mobile_content.js
node --test tests/test_mobile_content.cjs
python -m unittest discover -s tests -p test_mobile_navigation_build.py -v
test -s _site/mobile_navigation.css
test -s _site/mobile_navigation.js
test -s _site/mobile_content.css
test -s _site/mobile_content.js
python - <<'PY'
from pathlib import Path
pages=sorted(Path("_site").glob("*.html"))
assert len(pages)>=20, f"Zu wenige veröffentlichte HTML-Seiten: {len(pages)}"
for p in pages:
    text=p.read_text(encoding="utf-8")
    assert text.count('mobile_navigation.css')==1,(p,'mobile CSS missing/duplicate')
    assert text.count('mobile_navigation.js')==1,(p,'mobile JS missing/duplicate')
    assert text.count('mobile_content.css')==1,(p,'mobile chart CSS missing/duplicate')
    assert text.count('mobile_content.js')==1,(p,'mobile chart JS missing/duplicate')
print(f"Mobile Kategoriennavigation: alle {len(pages)} HTML-Seiten geprüft.")
PY

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
node tests/test_current_station_daily_ui.mjs
node --check _site/mosmix_vector_export.js
node tests/test_mosmix_vector_exports.mjs
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
node --check stratosphere_chart_visibility.js
node --check stratosphere_chart_export.js
node --check stratosphere_joint_comparison.js
node --check stratosphere_nasa_common.js
node --check stratosphere_analysis_forecast.js
node --check stratosphere_comparison_metrics.js
node --check stratosphere_vertical_profile.js
node --test tests/test_strato_extended_analytics.cjs
node --test tests/test_stratosphere_joint_comparison.cjs
node --test tests/test_stratosphere_chart_visibility.cjs
node --check stratosphere_ecmwf_runs.js
node --check stratosphere_ecmwf_ens.js
node --check stratosphere_run_trends.js
node --test tests/test_stratosphere_run_trends.cjs
node --check stratosphere_reversal_diagnostics.js
node --test tests/test_stratosphere_reversal_diagnostics.cjs
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
test -s _site/stratosphere_chart_visibility.js
test -s _site/stratosphere_chart_export.js
test -s _site/stratosphere_joint_comparison.js
test -s _site/stratosphere_joint_comparison.css
test -s _site/stratosphere_nasa_common.js
test -s _site/stratosphere_analysis_forecast.js
test -s _site/stratosphere_analysis_forecast.css
test -s _site/stratosphere_comparison_metrics.js
test -s _site/stratosphere_vertical_profile.js
grep -q 'id="stratoHistoryForecastCanvas"' _site/stratosphaere.html
grep -q 'id="stratoMetricDiffChart"' _site/stratosphaere.html
grep -q 'id="stratoVerticalHeatmap"' _site/stratosphaere.html
test -s _site/stratosphere_chart_visibility.css
grep -q 'stratosphere_chart_visibility.js' _site/stratosphaere.html
grep -q 'stratosphere_chart_export.js' _site/stratosphaere.html
grep -q 'stratosphere_joint_comparison.js' _site/stratosphaere.html
grep -q 'id="stratoJointCanvas"' _site/stratosphaere.html
grep -q 'id="stratoWinterStatsCard"' _site/stratosphaere.html
grep -q 'id="stratoProbCanvas"' _site/stratosphaere.html
grep -q 'id="stratoEpsTab"' _site/stratosphaere.html
grep -q 'id="stratoCompareCanvas"' _site/stratosphaere.html
grep -q 'id="stratoGefsCycle"' _site/stratosphaere.html
grep -q 'id="stratoEpsCycle"' _site/stratosphaere.html
grep -q 'id="stratoCompareHour"' _site/stratosphaere.html
test -s _site/stratosphere_run_trends.js
grep -q 'stratosphere_run_trends.js' _site/stratosphaere.html
grep -q 'id="stratoTrendCanvas"' _site/stratosphaere.html
grep -q 'id="stratoTrendModel"' _site/stratosphaere.html
grep -q 'id="stratoTrendValid"' _site/stratosphaere.html
grep -q 'id="stratoTrendCsv"' _site/stratosphaere.html
grep -q 'id="stratoHeatmap"' _site/stratosphaere.html
grep -q 'id="stratoHeatTable"' _site/stratosphaere.html
grep -q 'id="stratoHeatStatus"' _site/stratosphaere.html
grep -q 'id="stratoHeatDetail"' _site/stratosphaere.html
grep -q 'id="stratoHeatPng"' _site/stratosphaere.html
grep -q 'id="stratoHeatCsv"' _site/stratosphaere.html
test -s _site/stratosphere_reversal_diagnostics.js
grep -q 'stratosphere_reversal_diagnostics.js' _site/stratosphaere.html
grep -q 'id="stratoReversalDiagnostics"' _site/stratosphaere.html
grep -q 'id="stratoDiagOnset"' _site/stratosphaere.html
grep -q 'id="stratoDiagDuration"' _site/stratosphaere.html
grep -q 'id="stratoDiagCsv"' _site/stratosphaere.html
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

# The newly generated individual-year archive may not be committed yet.
# Keep all existing snow visualizations deployable while its backfill runs.
if [[ -d station_snow_height_years ]] && [[ -n "$(find station_snow_height_years -maxdepth 1 -type f -name '*.json' -print -quit)" ]]; then
  cp -a station_snow_height_years _site/
  echo "Schneehöhen-Jahreskurven in Pages-Artefakt übernommen."
else
  echo "HINWEIS: Schneehöhen-Jahreskurven noch nicht aufgebaut; aktuelle Saison und Klimamittel bleiben verfügbar."
fi

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
    '  "station_snow_height_years/",\n',
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
# Ergänzte Dekadenrekorde werden als separate, optional erzeugte Archive
# kopiert; die bestehende Seite funktioniert während des Erstaufbaus weiter.
for extra_file in data/dwd_decade_extra_kl.json data/dwd_decade_extra_rr.json; do
  if [[ -s "$extra_file" ]]; then
    cp "$extra_file" _site/data/
    echo "Dekaden-Zusatzrekorde veröffentlicht: $extra_file"
  fi
done
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

# Stationsrekord-Hintergrund: Das lokale, von Drittkachelservern unabhängige
# Natural-Earth-Kartenmaterial muss im Pages-Artefakt verfügbar bleiben.
test -s _site/wettergefahren_basemap.json || {
  echo "FEHLER: Lokaler Europa-Hintergrund wettergefahren_basemap.json fehlt"
  exit 1
}
node --check _site/station_snow_years.js
node --check _site/station_snow_accumulation.js
node --check _site/station_snow_explorer.js
node --test tests/test_station_snow_explorer.cjs
node --test tests/test_station_snow_years.cjs
node --test tests/test_station_snow_accumulation.cjs
node --test tests/test_station_snow_coverage.cjs
grep -q 'stationSnowCumChart' _site/index.html
grep -q 'station_snow_accumulation.js' _site/index.html
grep -q 'stationSnowYearsList' _site/index.html
grep -q 'station_snow_years.js' _site/index.html
grep -q 'station_snow_explorer.js' _site/index.html
grep -q 'station_snow_explorer.css' _site/index.html
node --check _site/europe_station_basemap.js
node --test tests/test_europe_station_basemap.cjs
grep -q 'europe_station_basemap.js' _site/index.html
grep -q 'europeStationBasemapStatus' _site/index.html

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
fi

# Only publish CPC forecasts when the official CSV ingestion passed its checks.
# The browser must show an explicit unavailable state until a verified run exists.
if [[ -s data/nao_ao_forecast/latest.json ]]; then
  python - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("data/nao_ao_forecast/latest.json").read_text(encoding="utf-8"))
assert d["schema"]==1 and d["ready"] is True
for key in ("nao","ao"):
    entry=d["indices"][key]
    assert len(entry["latest"]["mean"])==16
    assert len(entry["latest"]["members"])==31
    assert len(entry["latest"]["probability"]["negative"])==16
    assert entry["observations"]
print("NOAA/CPC Ensemble-Archiv geprüft.")
PY
  mkdir -p _site/data/nao_ao_forecast
  cp data/nao_ao_forecast/latest.json _site/data/nao_ao_forecast/latest.json
fi

# IFS ENS spatial context: publish only actual verified PNGs from ECMWF Open Data.
if [[ -s data/nao_ao_forecast/ecmwf_maps/index.json ]]; then
  python - <<'PY'
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
root=Path("data/nao_ao_forecast/ecmwf_maps")
doc=json.loads((root/"index.json").read_text(encoding="utf-8"))
assert doc.get("schema")==1 and doc.get("ready") is True
assert doc.get("is_anomaly") is False and doc.get("is_index_forecast") is False
assert doc.get("parameter")=="absolute_geopotential_height"
assert doc.get("unit")=="gpm" and doc.get("licence")=="CC BY 4.0"
assert len(doc.get("maps",[]))==6
assert {(int(x["level_hpa"]),int(x["step_hours"])) for x in doc["maps"]}=={
 (h,t) for h in (500,1000) for t in (72,144,240)
}
for row in doc["maps"]:
 p=root/row["file"]
 assert p.name==f'ifs_ens_gh_{row["level_hpa"]}hpa_f{row["step_hours"]:03d}.png'
 assert p.is_file() and p.stat().st_size>50000
 assert p.read_bytes()[:8]==bytes.fromhex("89504e470d0a1a0a")
print("ECMWF spatial forecast maps validated: 6 real PNGs")
PY
  mkdir -p _site/data/nao_ao_forecast/ecmwf_maps
  cp data/nao_ao_forecast/ecmwf_maps/*.png data/nao_ao_forecast/ecmwf_maps/index.json _site/data/nao_ao_forecast/ecmwf_maps/
fi

# ECMWF ENS NAO/AO projection: serve only verified real 50-member dataset.
if [[ -s data/nao_ao_forecast/ecmwf_indices.json ]]; then
  python - <<'PY'
import json
from pathlib import Path
p=Path("data/nao_ao_forecast/ecmwf_indices.json")
obj=json.loads(p.read_text(encoding="utf-8"))
assert obj.get("schema")==1 and obj.get("ready") is True
assert obj.get("expected_members")==50 and obj.get("is_official_cpc") is False
assert obj.get("nao_is_cpc_exact_method") is False
for key in ("nao","ao"):
 row=obj["indices"][key]
 assert len(row["members"])==50 and len(row["mean"])==16
 assert all(n==50 for n in row["member_count"])
 assert row["quality"]["holdout_correlation"]>=0.55
print("ECMWF EPS 50-member EOF forecast validated for Pages.")
PY
  mkdir -p _site/data/nao_ao_forecast
  cp data/nao_ao_forecast/ecmwf_indices.json _site/data/nao_ao_forecast/ecmwf_indices.json
fi
node --check _site/ecmwf_teleconnections.js

# NOAA/CPC extended archive as before.
if [[ -s climate_indices/index.json ]]; then
  echo "NOAA-Zirkulations- und ENSO-Indizes in Pages-Artefakt übernommen."
else
  echo "HINWEIS: NOAA-Indexarchiv noch nicht erstellt."
fi

# Eurasia snow observations are stored in the repository and loaded
# from the main branch by the independent NOAA IMS page. No pretend values
# are published if the first background ingestion has not succeeded.
node --check eurasia_snow.js
node --check snow_maps.js
node --test tests/test_snow_maps.cjs
if [[ -s eurasia_snow/index.json ]]; then
  mkdir -p _site/eurasia_snow
  cp eurasia_snow/index.json _site/eurasia_snow/index.json
  echo "NOAA IMS Eurasien-Schneebedeckung in Pages-Artefakt"
else
  echo "HINWEIS: Erste verifizierte NOAA IMS-Tageswerte noch ausstehend"
fi

# Beide Schneekarten und ihre Gültigkeiten gehören in dasselbe Pages-Artefakt.
if [[ -s eurasia_snow/maps/index.json ]]; then
  python - <<'PY'
import json, struct
from pathlib import Path
root = Path('eurasia_snow/maps')
doc = json.loads((root / 'index.json').read_text())
assert doc['schema'] == 1 and doc['reference_period'] == [2001, 2020]
assert doc['maps']
for row in doc['maps']:
    kinds = ('cover', 'anomaly', 'europe_cover', 'europe_anomaly') if row.get('version', 0) >= 3 else ('cover', 'anomaly')
    for kind in kinds:
        assert row[kind] == f"images/{row['date']}_{kind}.png"
        data = (root / row[kind]).read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR'
        width, height, depth, color = struct.unpack('>IIBB', data[16:26])
        min_width, min_height = (2400, 1400) if kind.startswith('europe_') else (3000, 900)
        assert width >= min_width and height >= min_height and depth == 8 and color == 2
assert doc['latest'] == max(row['date'] for row in doc['maps'])
print('IMS-Schneekarten: vollständige opake Kartenpaare geprüft')
PY
  mkdir -p _site/eurasia_snow
  cp -a eurasia_snow/maps _site/eurasia_snow/
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

# Phase 1: compact additional large public JSON files without touching raw archives.
# JSON parsing is checked before/after; no station, value or date is omitted.
python - <<'PY'
import json
from pathlib import Path
site=Path("_site")
names=(
  "data.json",
  "daily_tmax_1881_2026.json",
  "station_records.json",
  "station_climate_days_index.json",
  "station_heatwaves_index.json",
  "station_snow_height_additional_index.json",
)
saved=0
for name in names:
    p=site/name
    if not p.is_file() or p.stat().st_size<500_000:
        continue
    original=p.read_bytes()
    parsed=json.loads(original.decode("utf-8-sig"))
    compact=(json.dumps(parsed,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n").encode("utf-8")
    if len(compact)>=len(original):
        continue
    assert json.loads(compact)==parsed, f"JSON equivalence failed: {name}"
    p.write_bytes(compact)
    saved+=len(original)-len(compact)
    print(f"Compacted published archive {name}: {len(original):,} -> {len(compact):,} bytes")
print(f"Additional JSON transfer savings (raw): {saved:,} bytes")
PY

touch _site/.nojekyll
echo "Pages-Artefakt erfolgreich gebaut."
echo "Schneehöhenprofile: $(find _site/station_snow_height_profiles -type f -name '*.json' | wc -l) Dateien"
echo "Aktuelle Schneehöhen: $(find _site/station_snow_height_current -type f -name '*.json' | wc -l) Dateien"
echo "Europa-Stationsdaten: $(find _site/europe_stations -type f | wc -l) Dateien"
echo "ERA5-Atmosphäre: $(find _site/era5_europe -type f | wc -l) Dateien"
echo "Dateien gesamt: $(find _site -type f | wc -l)"
du -sh _site

