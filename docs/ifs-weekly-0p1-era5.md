# ECMWF IFS 0,1° · 168-Stunden-Temperaturanomalie

## Methodik

- ECMWF IFS Open Data, originales globales 0,1°-Raster, 00/12 UTC, 2-m-Temperatur. Die 29 zeitlich gleichmäßig verteilten Originalfelder von +0 bis +168 h werden trapezgewichtet gemittelt. Alle GRIB-Zeitstempel, Parameter, Rasterkoordinaten und Prüfsummen werden geprüft. Keine 0,25°-Ersatzprognose.
- Geografisches Fenster: 80° W bis 100° E, 25–85° N, 1801 × 601 Originalrasterpunkte. Die Karte nutzt Natural Earth 50m-Grenzen und einen separat rasterisierten Länder-ID-Layer.
- ERA5 single levels (0,25°), 1991–2020, 2m temperature: je Kalendertag und 00/06/12/18 UTC das Mittel sämtlicher 30 Jahresbeiträge; am 29. Februar acht Schaltjahre. Die genau den IFS-Gültigkeitszeitpunkten entsprechenden Referenzfelder werden gleich gewichtet; erst dann bilinear auf das 0,1°-Raster übertragen. ERA5 ist keine laufzeitabhängig kalibrierte IFS-Modellklimatologie. Höhenunterschiede können besonders im Gebirge systematische Unterschiede erzeugen.
- Fehlende Zeitpunkte, falsche Auflösung, Datenlücken oder fehlende Referenzjahre verhindern Anomalieausgabe. Kein ERA5-Land-Ersatz für Ozeane, keine synthetische Referenz.

## Umsetzung und Freigabe

1. Native IFS-Felder abrufen, Herkunft und komplette Laufzeit nachweisen; vorhandenen GFS-Workflow nicht verändern.
2. Für den ersten echten Lauf die benötigten ERA5-Monate aus allen 30 Jahren aufbauen und validieren. Monatsdateien enthalten Original-Quellprüfsummen, Anzahl der Jahresbeiträge, Koordinaten und Zeitstufen.
3. IFS- und Referenzmittel kombinieren. Separate Karte mit denselben Projektionen und Anomaliefarben, 2100 × 1140 Pixel, 2100 × 1425 Pixel PNG/PDF inklusive Farbskala, CSV-Ländermittel.
4. GitHub-Actions-Pilot testet echte Daten auf Desktop und Mobil; Ergebnisartefakte sind zunächst nicht Teil der Website. Erst bei Erfolg folgt die Veröffentlichung, dauerhafte Referenzablage und jährlicher vollständiger 12-Monats-Backfill.

## Datenquellen

- https://www.ecmwf.int/en/forecasts/datasets/open-data
- https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels
