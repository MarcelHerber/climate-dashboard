# ERA5-Land Europa – V4 Gitterpunktanalyse

Die Dateien im ZIP sind bereits in der richtigen Repository-Struktur angeordnet. Der vorhandene GitHub-Secret `CDSAPI_KEY` wird unverändert weiterverwendet.

## V4 starten

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

Beim ersten V4-Lauf wird der V3-Cache weiterverwendet. Neu aufgebaut werden die Daten für die interaktive Gitterpunktanalyse. Weil dafür zusätzliche Monatsreferenzen und historische Temperatur-/Niederschlagswerte seit 1950 benötigt werden, kann dieser erste Lauf deutlich länger dauern. Der Workflow hat dafür ein Zeitlimit von 300 Minuten.

## Neu in V4

- sichtbare Europakarten weiterhin auf dem ERA5-Land-CDS-Gitter 0,1°
- Klick direkt auf die Karte wählt den nächstgelegenen Land-Analysepunkt auf einem kompakten 1,0°-Raster
- Jahresverlauf des aktuellen Jahres gegen 1991–2020
- Temperatur, Niederschlag und alle vier Bodenfeuchteschichten
- historischer Rang für den gewählten Kartenzeitraum
- Temperatur und Niederschlag: Rang und Verlauf seit 1950
- Bodenfeuchte: Einordnung aus den Einzeljahren 1991–2020 plus aktuellem Jahr
- frei wählbares Vergleichsjahr
- aktueller Wert, Klimamittel, Abweichung bzw. Prozent vom Mittel und Perzentil/Rang
- zwei Punktdiagramme: Monatsverlauf und historische Entwicklung

## Datenstruktur

Der Workflow erzeugt zusätzlich:

`era5_land_europe/analysis.json`

Die Datei enthält nur ein ausgedünntes 1°-Analyseraster, damit die Website trotz historischer Zeitreihen schnell bleibt. Die Karten-PNGs selbst bleiben hochauflösend.

## Bodenfeuchteschichten

- Layer 1: 0–7 cm
- Layer 2: 7–28 cm
- Layer 3: 28–100 cm
- Layer 4: 100–289 cm

Die Bodenfeuchte wird als volumetrischer Bodenwassergehalt in m³/m³ dargestellt. Die Kartenperzentile bleiben rasterzellenweise auf Basis 1991–2020.

## Update von V3 auf V4

Die bereits erzeugten Dateien unter `era5_land_europe/` sind bewusst nicht Bestandteil dieses ZIPs. Dadurch werden vorhandene V3-Karten beim Hochladen nicht überschrieben. Der nächste erfolgreiche ERA5-Land-Workflow erzeugt `analysis.json`, aktualisiert die Karten und schreibt `payload_version: 4`.
