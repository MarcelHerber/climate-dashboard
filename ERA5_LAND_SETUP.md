# ERA5-Land Europa – V5 Wasserhaushalt

Die Dateien liegen bereits in der richtigen Repository-Struktur. Der vorhandene GitHub-Secret `CDSAPI_KEY` wird unverändert weiterverwendet.

## V5 starten

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

`force` beim ersten normalen V5-Lauf **nicht aktivieren**. Der V4-Cache wird übernommen. Der erste V5-Aufbau kann länger dauern, weil Wasserhaushalts-Referenzen 1991–2020 und die historische 1°-Analyse ergänzt werden. Große CDS-Abrufe sind in Blöcke geteilt und werden bei temporären Fehlern automatisch wiederholt.

## Neu in V5

- Gesamtverdunstung (ERA5-Land `total_evaporation`)
- Gesamtabfluss (`runoff`)
- Oberflächenabfluss (`surface_runoff`)
- unterirdischer Abfluss (`sub_surface_runoff`)
- Wasserbilanz **P − E** = Niederschlag minus positive Gesamtverdunstung
- für alle fünf Größen: Absolutwert, Abweichung 1991–2020, Perzentil 1991–2020
- jüngster vollständiger Monat und Sommer JJA/bisher
- Gitterpunktanalyse auf 1° mit Jahresverlauf, Klimamittel, Vergleichsjahr und historischem Rang seit 1950
- Karten bleiben auf 0,1°

## Vorzeichen und Einheiten

ERA5-Land speichert `total_evaporation` nach ECMWF-Konvention bei Verdunstung überwiegend negativ. V5 dreht das Vorzeichen für die Anzeige um, sodass positive mm-Werte intuitiv Wasserabgabe durch Verdunstung bedeuten. Die monatlich gemittelten akkumulierten hydrologischen Größen werden von m/Tag in Monatssummen in mm umgerechnet.

## Cache

Der Workflow verwendet einen V5-Cache mit Fallback auf V4/V3/V2/V1. Ein normaler Lauf ergänzt nur fehlende V5-Bausteine. `--force` löscht bzw. erneuert die jeweiligen Cache-Dateien und sollte nur zur Fehlerbehebung verwendet werden.

## Ergebnis

Nach erfolgreichem Lauf schreibt `era5_land_europe/index.json` `payload_version: 5`. `era5_land_europe/analysis.json` wird auf `payload_version: 2` erweitert.
