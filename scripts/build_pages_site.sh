#!/usr/bin/env bash
set -euo pipefail

rm -rf _site
mkdir -p _site/data

required_root_files=(
  index.html
  dekadenrekorde.html
  data.json
  daily_tmax_1881_2026.json
  station_records.json
  station_precip_index.json
  station_climate_days_index.json
  station_heatwaves_index.json
  station_heatwaves_current.json
  update_status.json
)

for file in "${required_root_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "FEHLER: Für GitHub Pages fehlt: $file"
    exit 1
  fi
  cp "$file" _site/
done

required_data_files=(
  data/dwd_decade_records.json
  data/dwd_decade_snow_records.json
)

for file in "${required_data_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "FEHLER: Für GitHub Pages fehlt: $file"
    exit 1
  fi
  cp "$file" "_site/data/$(basename "$file")"
done

# Weltweite GHCN-Stationsdaten sind vorerst nicht Teil der Website.
# Die JSON-Dateien im Repository bleiben erhalten.

touch _site/.nojekyll

echo "Pages-Artefakt erfolgreich gebaut."
echo "Dateien: $(find _site -type f | wc -l)"
echo "Größe:"
du -sh _site
