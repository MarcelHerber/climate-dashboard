# ERA5-Land Europa – V8.1 · historische Karten in 0,1°

Die Dateien liegen bereits in der richtigen Repository-Struktur. Der vorhandene GitHub-Secret `CDSAPI_KEY` bleibt unverändert.

## Was wurde gegenüber V8 geändert?

Die sichtbaren historischen Europakarten werden **nicht mehr aus dem groben 1,0°-Analyseraster gezeichnet**. Der Workflow baut dafür ein separates, echtes ERA5-Land-Historienarchiv auf dem **0,1°-CDS-Raster** auf.

- aktuelle Karten: weiterhin 0,1°
- historische Karten: jetzt ebenfalls 0,1°
- Temperatur, Niederschlag, Wasserhaushalt und Schnee: historische Karten ab 1950 bis zum letzten abgeschlossenen Jahr
- Bodenfeuchte: 1991–2020
- Absolutwert, Abweichung/Prozent und Perzentil werden im Browser aus dem hochaufgelösten Archiv berechnet
- Top-/Bottom-10, historische Ränge, KPIs und die Klick-Zeitreihen bleiben bewusst auf dem 1,0°-Analyseraster. Dadurch bleibt die Analyse schnell und vergleichbar, während die sichtbare Karte hochaufgelöst ist.

Die 0,1°-Raster werden für die statische GitHub-Pages-Seite kompakt als `uint8 + horizontaler Delta-Prädiktor + gzip` gespeichert. `255` kennzeichnet fehlende Rasterzellen. Die Quantisierung betrifft nur die sichtbare historische Rasterdarstellung; die Analysewerte in `analysis.json` bleiben unverändert.

## Erster Lauf

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

`force` **nicht aktivieren**.

Der Workflow verwendet einen neuen `v8-hires`-Cache mit Fallback auf V8/V7/V6 usw. Die vorhandenen V7/V8-Daten werden wiederverwendet. Für die neuen echten 0,1°-Historienkarten müssen beim **ersten** Lauf allerdings zusätzliche historische CDS-Felder geladen werden. Dieser Lauf kann deshalb wieder deutlich länger dauern. Spätere Läufe für denselben Datenstand verwenden die erzeugten Browser-Packs direkt.

## Ergebnis

Nach erfolgreichem Lauf stehen zusätzlich zur bisherigen Struktur bereit:

- `era5_land_europe/index.json` → `payload_version: 8`
- `era5_land_europe/analysis.json` → weiterhin `payload_version: 3`
- `era5_land_europe/history_0p1/index.json` → Metadaten des hochaufgelösten Archivs
- `era5_land_europe/history_0p1/*.u8.gz` → kompakte echte 0,1°-Rasterarchive
- `era5_land_europe/maps/historical_base.png` → neutrale geografische Basiskarte

Danach wie gewohnt **Update and Deploy** ausführen.
