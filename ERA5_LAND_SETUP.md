# ERA5-Land Europa – Einrichtung und V3-Update

Die Dateien in diesem Paket sind bereits in der richtigen Repository-Struktur angeordnet.

## Copernicus/ECMWF-Zugang

Der vorhandene GitHub-Secret `CDSAPI_KEY` wird unverändert weiterverwendet. Wenn V1/V2 bereits funktioniert, ist keine neue CDS-Einrichtung nötig.

## V3 starten

Nach dem Hochladen der Dateien:

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

Beim ersten V3-Lauf werden zusätzlich die historischen 1991–2020-Einzeljahre der vier Bodenfeuchteschichten für die aktuell benötigten Monate geladen. Diese Einzeljahre werden benötigt, um echte Gitterpunkt-Perzentile zu berechnen. Der V2-Cache für Temperatur/Niederschlag wird weiterverwendet.

## Umfang V3

- Europa, 72°N–34°N und 25°W–45°E
- ERA5-Land 0,1° CDS-Gitter
- 2-m-Temperatur
  - absolut
  - Abweichung 1991–2020
- Niederschlag
  - Summe in mm
  - Prozent vom Mittel 1991–2020
- Bodenfeuchte in allen vier ERA5-Land-Modellschichten
  - 0–7 cm
  - 7–28 cm
  - 28–100 cm
  - 100–289 cm
- je Bodenschicht
  - volumetrischer Bodenwassergehalt in m³/m³
  - Abweichung gegenüber 1991–2020
  - Perzentil / Dürreklasse gegenüber den 30 Einzeljahren 1991–2020
- jüngster sicher verfügbarer vollständiger Monat
- Sommer (JJA) bis zum jüngsten vollständig verfügbaren Monat

## Perzentil-Klassen

Die Perzentile werden rasterzellenweise aus den 30 Referenzjahren 1991–2020 berechnet. Für einen laufenden Sommer wird derselbe Teilzeitraum jedes Referenzjahres verwendet (z. B. Juni–Juli gegen Juni–Juli 1991–2020).

- P ≤ 5: extrem trocken
- P 5–10: sehr trocken
- P 10–20: trocken
- P 20–30: eher trocken
- P 30–70: normal
- P 70–80: eher feucht
- P 80–90: feucht
- P 90–95: sehr feucht
- P > 95: extrem feucht

Hinweis: ERA5-Land ist ein Landprodukt. Meeresflächen bleiben in den Karten leer.

## Update von V2 auf V3

`era5_land_europe/index.json` und vorhandene Karten sind bewusst nicht Teil dieses ZIPs. Der nächste erfolgreiche Workflow ersetzt/ergänzt sie automatisch und schreibt `payload_version: 3`.
