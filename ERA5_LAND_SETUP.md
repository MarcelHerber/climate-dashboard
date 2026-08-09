# ERA5-Land Europa – V7 Historische Karten

Die Dateien liegen bereits in der richtigen Repository-Struktur. Der vorhandene GitHub-Secret `CDSAPI_KEY` bleibt unverändert.

## Neu in V7

- neuer Regler **Kartenjahr** im ERA5-Land-Tab
- aktueller Datenstand weiterhin als hochaufgelöste 0,1°-PNG-Karte
- historische Europakarten auf dem bereits vorhandenen 1,0°-Analyseraster
- Temperatur, Niederschlag, Wasserhaushalt und Schnee: Kartenjahre ab 1950
- Bodenfeuchte: Einzeljahre 1991–2020 plus aktueller Datenstand
- Absolutwert sowie je nach Parameter Abweichung, Prozent vom Mittel oder Perzentil 1991–2020
- Europa-KPIs werden auch für das gewählte historische Kartenjahr neu berechnet
- Klick auf historische Karte öffnet dieselbe Gitterpunktanalyse und markiert das gewählte Kartenjahr im historischen Diagramm
- PNG-Export funktioniert auch für historische Karten

Die historischen Karten werden im Browser aus `analysis.json` gezeichnet. Dadurch müssen **nicht tausende historische PNG-Dateien** ins Repository geschrieben werden und V7 benötigt keine zusätzliche komplette ERA5-Land-Historie gegenüber V6.

## V7 starten

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

`force` **nicht aktivieren**. Der Workflow verwendet den V7-Cache mit Fallback auf den vorhandenen V6-Cache. Wenn V6 bereits erfolgreich aufgebaut wurde, sollten die historischen Daten weitgehend aus dem Cache kommen.

## Ergebnis

Nach erfolgreichem Lauf schreibt:

- `era5_land_europe/index.json` → `payload_version: 7`
- `era5_land_europe/analysis.json` → weiterhin `payload_version: 3`
- `era5_land_europe/maps/historical_base.png` → neutrale Basiskarte für das historische 1°-Raster

Danach wie gewohnt **Update and Deploy** ausführen.
