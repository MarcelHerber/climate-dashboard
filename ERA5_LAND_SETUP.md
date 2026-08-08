# ERA5-Land Europa – einmalige Einrichtung

Die Dateien in diesem Paket sind bereits in der richtigen Repository-Struktur angeordnet.

## 1. Copernicus/ECMWF-Zugang

1. Im Copernicus Climate Data Store (CDS) anmelden bzw. registrieren.
2. Die Datensatzseite **ERA5-Land monthly averaged data from 1950 to present** öffnen.
3. Die Lizenz/Nutzungsbedingungen dieses Datensatzes einmal im CDS akzeptieren.
4. Unter der CDS-API-Seite den persönlichen **Personal Access Token** kopieren.

## 2. GitHub Secret anlegen

Im Repository:

**Settings → Secrets and variables → Actions → New repository secret**

Name:

`CDSAPI_KEY`

Wert: nur der persönliche CDS Personal Access Token.

Der Token gehört niemals in `index.html`, das Python-Skript oder eine öffentliche Datei.

## 3. Ersten Lauf starten

**Actions → ERA5-Land Europa aktualisieren → Run workflow**

Beim ersten Lauf werden die benötigten 1991–2020-Klimatologien für die aktuell benötigten Monate erzeugt und im Actions-Cache abgelegt. Daher dauert der erste Lauf deutlich länger als spätere Aktualisierungen.

Danach schreibt der Workflow nur die kleinen fertigen Webprodukte nach:

- `era5_land_europe/index.json`
- `era5_land_europe/maps/*.png`

Die Website lädt diese Dateien direkt aus dem `main`-Branch. Deshalb muss nach einem späteren ERA5-Land-Datenupdate nicht jedes Mal GitHub Pages neu gebaut werden.

## Umfang V2

- Europa, 72°N–34°N und 25°W–45°E
- ERA5-Land 0,1° CDS-Gitter
- 2-m-Temperatur
  - absolut
  - Abweichung 1991–2020
- Niederschlag
  - Summe in mm
  - Prozent vom Mittel 1991–2020
- Bodenfeuchte, Schicht 1 (0–7 cm)
  - volumetrischer Bodenwassergehalt in m³/m³
  - Abweichung gegenüber 1991–2020
- jüngster sicher verfügbarer vollständiger Monat
- Sommer (JJA) bis zum jüngsten vollständig verfügbaren Monat

Hinweis: ERA5-Land ist ein Landprodukt. Meeresflächen bleiben in den Karten leer.


## Update von V1 auf V2

`era5_land_europe/index.json` und die vorhandenen Karten sind bewusst nicht Teil dieses Update-ZIPs. Sie sind bereits vom V1-Workflow erzeugte Ausgabedateien und sollen beim Hochladen nicht zurückgesetzt werden. Der nächste erfolgreiche V2-Workflow ergänzt/aktualisiert sie automatisch.

Der vorhandene V1-Cache für Temperatur und Niederschlag wird beim ersten V2-Lauf wiederverwendet. Neu heruntergeladen werden im Wesentlichen die Bodenfeuchtefelder und deren 1991–2020-Klimatologien für die aktuell benötigten Monate. Nach dem erfolgreichen V2-Lauf enthält `era5_land_europe/index.json` `payload_version: 2`.
