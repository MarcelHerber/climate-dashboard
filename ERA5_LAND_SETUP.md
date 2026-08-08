# ERA5-Land Europa – V6 Schnee & Schneewasser

Die Dateien liegen bereits in der richtigen Repository-Struktur. Der vorhandene GitHub-Secret `CDSAPI_KEY` wird unverändert weiterverwendet.

## V6 starten

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

`force` beim ersten V6-Lauf **nicht aktivieren**. Der Workflow stellt zunächst den vorhandenen V5-Cache wieder her und ergänzt nur die neuen Schnee-Bausteine. Temporäre CDS-Fehler werden weiterhin automatisch wiederholt.

## Neu in V6

- Schneehöhe (`snow_depth`) in cm
- Schneewasseräquivalent (`snow_depth_water_equivalent`) in mm Wasseräquivalent
- Schneebedeckung (`snow_cover`) in %
- für alle drei Größen: Absolutwert, Abweichung 1991–2020 und Perzentil 1991–2020
- jüngster vollständiger Monat und Sommer JJA/bisher
- 0,1°-Europakarten
- 1°-Gitterpunktanalyse mit Jahresverlauf, Klimamittel, Vergleichsjahr und historischem Rang seit 1950

Schneehöhe, Schneewasseräquivalent und Schneebedeckung sind Zustandsgrößen. Bei Zeiträumen mit mehreren Monaten wird deshalb ein nach Kalendertagen gewichtetes Mittel gebildet und **keine Summe**.

## Bestehende V5-Funktionen bleiben erhalten

Temperatur, Niederschlag, vier Bodenfeuchteschichten, Verdunstung, Gesamt-/Oberflächen-/Untergrundabfluss und Wasserbilanz P − E bleiben vollständig enthalten.

## Cache

Der Workflow verwendet nun einen V6-Cache mit Fallback auf V5/V4/V3/V2/V1. Dadurch müssen die bereits erfolgreich aufgebauten V5-Referenzen nicht erneut heruntergeladen werden. `--force` sollte nur zur gezielten Fehlerbehebung verwendet werden.

## Ergebnis

Nach erfolgreichem Lauf schreibt:

- `era5_land_europe/index.json` → `payload_version: 6`
- `era5_land_europe/analysis.json` → `payload_version: 3`

Danach wie gewohnt **Update and Deploy** ausführen, damit die neue Oberfläche auf GitHub Pages veröffentlicht wird.
