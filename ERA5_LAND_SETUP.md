# ERA5-Land Europa – V5 Wasserhaushalt

Die Dateien im ZIP liegen bereits in der richtigen Repository-Struktur. Der vorhandene GitHub-Secret `CDSAPI_KEY` wird unverändert weiterverwendet.

## V5 starten

Nach dem Hochladen:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

Die Option **force** beim ersten normalen V5-Lauf bitte **nicht aktivieren**. Der Workflow stellt zuerst den vorhandenen V4-Cache wieder her und ergänzt nur die neuen Wasserhaushaltsdaten.

Der erste V5-Lauf kann deutlich länger dauern als ein späteres Monatsupdate, weil für die neuen Parameter die 1991–2020-Referenz sowie die 1°-Historie seit 1950 aufgebaut werden. Große CDS-Abfragen sind in 10-Jahres-Blöcke zerlegt und werden bei temporären CDS-Fehlern automatisch bis zu dreimal versucht.

## Neu in V5

- Gesamtverdunstung (ERA5-Land `total_evaporation`), als positive Wasserabgabe in mm dargestellt
- Gesamtabfluss (`runoff`)
- Oberflächenabfluss (`surface_runoff`)
- unterirdischer Abfluss (`sub_surface_runoff`)
- abgeleitete Wasserbilanz **P−E = Niederschlag − Gesamtverdunstung**
- je Parameter: Absolutwert, Abweichung 1991–2020 und empirisches Perzentil 1991–2020
- Karten für jüngsten vollständigen Monat und Sommer bisher/JJA
- Integration aller Wasserhaushaltsparameter in die V4-Gitterpunktanalyse
- historische Gitterpunktreihe und Rang seit 1950
- Vergleichsjahr wie bisher frei wählbar

## Einheiten und Vorzeichen

Die monatlich gemittelten akkumulierten hydrologischen ERA5-Land-Größen werden als effektive Meter Wasseräquivalent pro Tag geliefert. Das Skript multipliziert mit der Zahl der Kalendertage und mit 1000 und stellt die Ergebnisse als **mm pro Monat bzw. Zeitraum** dar.

ERA5-Land verwendet für akkumulierte Flüsse die ECMWF-Konvention „positiv nach unten“. `total_evaporation` ist deshalb bei Verdunstung normalerweise negativ. Im Dashboard wird das Vorzeichen umgedreht, sodass **positive Verdunstungswerte einen Wasserverlust von der Oberfläche** bedeuten.

Die Wasserbilanz ist rein diagnostisch als **Niederschlag minus Gesamtverdunstung** definiert. Negative Werte bedeuten ein rechnerisches Defizit, positive Werte einen Überschuss; Speicherung, Abfluss und andere Bilanzterme sind darin nicht vollständig geschlossen.

## Datenstruktur

Der Workflow aktualisiert:

- `era5_land_europe/index.json` → `payload_version: 5`
- `era5_land_europe/analysis.json` → `payload_version: 2`
- zusätzliche Karten-PNGs unter `era5_land_europe/maps/`

Die sichtbaren Karten bleiben 0,1°. Die historische Klickanalyse bleibt auf einem kompakten 1,0°-Landraster.

## Bestehende Funktionen bleiben erhalten

- Temperatur und Niederschlag
- alle vier Bodenfeuchteschichten (0–7, 7–28, 28–100, 100–289 cm)
- Bodenfeuchte-Perzentile
- Klickanalyse mit Monatsverlauf
- historische Einordnung
- Vergleichsjahr
- PNG-Download der ERA5-Land-Karten
