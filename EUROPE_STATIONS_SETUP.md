# Europa-Stationen · Stations-V4

## Neu in V4

Frankreich wird im Europa-Stationsmodul nicht mehr aus GHCN-Daily dargestellt, sondern direkt aus den offenen täglichen Klimadaten von **Météo-France**. Deutschland bleibt bei **DWD CDC**, für alle übrigen europäischen Länder bleibt **GHCN-Daily** der Fallback.

Damit gilt jetzt:

- Deutschland → DWD CDC
- Frankreich → Météo-France
- übriges Europa → GHCN-Daily

Deutsche und französische GHCN-Stationen werden bereits beim GHCN-Metadatenimport ausgeschlossen. Dadurch entstehen keine parallelen GHCN-/Originalquellen-Doppelstationen in diesen beiden Ländern.

Die komplette Stations-V2/V3-Oberfläche bleibt erhalten: TMAX/TMIN, absolute Stationsrekorde, Kalendertagsrekorde, Rekordjagd im laufenden Jahr, neue Rekorde, Top 20, Länderfilter, Mindest-Messjahre und Stationssuche.

## Datenquelle Frankreich

Verwendet werden die offiziellen offenen Datensätze von Météo-France auf meteo.data.gouv.fr / data.gouv.fr:

- `Données climatologiques de base - quotidiennes`
- `Données climatologiques de base - quotidiennes - stations complémentaires`

Der Workflow liest die Ressourcenlisten dynamisch über die data.gouv.fr-Dataset-API und wählt nur die täglichen `RR-T-Vent.csv.gz`-Dateien für das französische Mutterland einschließlich Korsika aus. Damit ist kein Météo-France-API-Key nötig.

Ausgewertet werden:

- `TX` → Tagesmaximum → Dashboard `TMAX`
- `TN` → Tagesminimum → Dashboard `TMIN`
- `NUM_POSTE` → 8-stellige Météo-France-Stations-ID
- `NOM_USUEL`, `LAT`, `LON`, `ALTI` → Stationsmetadaten

Die Météo-France-ID wird intern als `MF:xxxxxxxx` gespeichert, im Popup aber ohne Präfix angezeigt.

### Qualitätsregel Frankreich

Für TX/TN werden Météo-France-Qualitätscodes 0, 1 und 9 akzeptiert. Code 2 (`donnée douteuse en cours de vérification`) wird nicht für Rekorde verwendet. Bei älteren vorhandenen Werten ohne Qualitätscode wird der Wert akzeptiert.

## Historischer Aufbau

Der historische Frankreich-Bestand wird einmalig aus den nach Département und Zeitraum getrennten Météo-France-Dateien aufgebaut. Die Ressourcen umfassen je nach Station die historischen Blöcke vor 1950, ab 1950 sowie den aktuellen Zweijahresblock. Beim Basisaufbau werden nur Daten bis zum Ende des Vorjahres übernommen.

Der fertige Cache heißt sinngemäß:

`meteofrance_daily_baseline_through_2025_v1.pkl.gz`

Beim täglichen Lauf wird anschließend nur noch der Ressourcenblock gelesen, der das aktuelle Jahr enthält.

## Erster V4-Lauf

GitHub → **Actions** → **Update Europe station records** → **Run workflow**.

Alle Schalter zunächst auf `false` lassen:

- `force_baseline = false`
- `force_dwd_baseline = false`
- `force_mf_baseline = false`

Der V4-Workflow versucht zuerst, den vorhandenen V3-Cache wiederzuverwenden. Dadurch sollten GHCN und DWD nicht erneut historisch aufgebaut werden. Neu ist beim ersten V4-Lauf hauptsächlich die Météo-France-Baseline.

`force_mf_baseline = true` ist nur nötig, wenn Frankreich bewusst vollständig neu aufgebaut werden soll. `force_baseline = true` erzwingt alle drei historischen Baselines und sollte im Normalbetrieb ausgeschaltet bleiben.

## Payload und Prüfung

`europe_stations/index.json` hat in Stations-V4 `payload_version: 4`.

Der Workflow prüft automatisch:

- DWD-Stationen sind vorhanden
- Météo-France-Stationen sind vorhanden
- GHCN-Stationen sind vorhanden
- alle deutschen Stationen haben `source: "DWD CDC"`
- alle französischen Stationen haben `source: "Météo-France"`
- Deutschland und Frankreich enthalten keine GHCN-Fallbackstationen mehr

Die Frontend-Tagesarchive bleiben unter `europe_stations/calendar/MM-DD.json.gz` kompatibel mit der bisherigen Kartenlogik.

## V4.1 – Versionssicherer Workflow

Der Workflow prüft vor dem Datenlauf, ob `update-europe-station-records.yml` und `scripts/update_europe_station_records.py` dieselbe Payload-Version verwenden. Der alte Ordner `europe_stations/` wird vor der Neuberechnung entfernt, damit keine veraltete `index.json` einen neuen Lauf verfälschen kann. Am Ende werden Payload-Version und Stationszahlen je Quelle ausdrücklich ausgegeben.
