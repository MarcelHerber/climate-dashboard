# Europa-Stationen · Stations-V5

## Quellenarchitektur

Stations-V5 erweitert die bestehende Europa-Rekordkarte um **AEMET OpenData für Spanien**. Die nationalen Originalquellen haben Vorrang vor GHCN-Daily:

- Deutschland → **DWD CDC**
- Frankreich → **Météo-France**
- Spanien → **AEMET OpenData**
- übriges Europa → **NOAA GHCN-Daily** als Fallback

Deutschland, Frankreich und Spanien werden bereits beim GHCN-Metadatenimport ausgeschlossen. Dadurch gibt es in diesen Ländern keine parallelen GHCN-/Originalquellen-Doppelstationen.

Die Oberfläche bleibt kompatibel mit Stations-V2/V3/V4: TMAX/TMIN, absolute Stationsrekorde, Kalendertagsrekorde, Rekordjagd im laufenden Jahr, neue Rekorde, Top 20, Länderfilter, Mindest-Messjahre und Stationssuche.

## AEMET API-Key

AEMET OpenData benötigt einen API-Key. Er wird **nicht** in den Code geschrieben, sondern ausschließlich aus dem GitHub Repository Secret gelesen:

`AEMET_API_KEY`

GitHub: **Settings → Secrets and variables → Actions → Repository secrets**.

Der Workflow bricht mit einer klaren Meldung ab, wenn das Secret fehlt. Der Key wird nicht in die erzeugten JSON-Dateien geschrieben und nicht im Log ausgegeben.

## Offizielle AEMET-Endpunkte

V5 verwendet die AEMET-OpenData-Endpunkte:

- Stationsinventar: `valores/climatologicos/inventarioestaciones/todasestaciones`
- tägliche Klimatologien aller Stationen für einen Datumsbereich: `valores/climatologicos/diarios/.../todasestaciones`

AEMET liefert zunächst einen JSON-Antwortumschlag mit einer URL im Feld `datos`; der Workflow lädt anschließend unmittelbar den eigentlichen Datensatz von dieser URL.

Verwendete Felder der Tagesdaten:

- `indicativo` → Stations-ID
- `fecha` → Datum
- `tmax` → Tagesmaximum → Dashboard `TMAX`
- `tmin` → Tagesminimum → Dashboard `TMIN`

Stationsname, Koordinaten und Höhe kommen aus dem AEMET-Stationsinventar. Die AEMET-ID wird intern mit `AEMET:` präfixiert, im Popup aber ohne Präfix angezeigt.

## Historischer Aufbau Spanien

AEMET unterstützt bei den täglichen Klimatologien Zeiträume von bis zu **fünf Jahren pro Anfrage**. Deshalb baut V5 die historische Spanien-Baseline in maximal 5-jährigen Blöcken auf. Der Start ist 1850, der historische Endpunkt ist jeweils das Ende des Vorjahres.

Beispiel für 2026:

`1850–1854`, `1855–1859`, …, `2020–2024`, `2025–2025`

Blöcke ohne Daten werden übersprungen. Bei HTTP 429 oder temporären Serverfehlern arbeitet der Adapter mit Backoff und Wiederholungsversuchen, damit AEMET nicht unnötig aggressiv abgefragt wird.

Der fertige Cache heißt sinngemäß:

`aemet_spain_daily_baseline_through_2025_v1.pkl.gz`

Danach wird das laufende Jahr separat über eine einzelne AEMET-Anfrage aktualisiert. Ein normaler Folgelauf verwendet die historische AEMET-Baseline wieder.

## Qualitätsregel Spanien

Für Rekorde werden nur numerisch lesbare `tmax`- und `tmin`-Werte aus der veröffentlichten AEMET-Tagesklimatologie verwendet. Fehlende, nichtnumerische oder offensichtlich ungültige Temperaturwerte werden verworfen. Im von diesem Endpoint gelieferten Tagesdatensatz wird kein mit GHCN vergleichbarer Q-FLAG vorausgesetzt.

## Erster V5-Lauf

Erst den laufenden V4-Frankreich-Lauf vollständig beenden lassen, damit dessen DWD-/Météo-France-/GHCN-Caches gespeichert sind. Danach die V5-Dateien hochladen und starten:

**Actions → Update Europe station records → Run workflow**

Alle Schalter zunächst auf `false` lassen:

- `force_baseline = false`
- `force_dwd_baseline = false`
- `force_mf_baseline = false`
- `force_aemet_baseline = false`

V5 versucht zuerst, den V4-Cache wiederherzustellen. Damit sollten GHCN, DWD und Météo-France nicht erneut historisch aufgebaut werden. Neu ist beim ersten V5-Lauf hauptsächlich die AEMET-Baseline.

`force_aemet_baseline = true` ist nur sinnvoll, wenn Spanien bewusst komplett neu aufgebaut werden soll. `force_baseline = true` erzwingt alle historischen Baselines und sollte im Normalbetrieb ausgeschaltet bleiben.

## Payload und automatische Prüfung

`europe_stations/index.json` verwendet in Stations-V5 `payload_version: 5`.

Der Workflow prüft am Ende automatisch:

- DWD-Stationen vorhanden und Deutschland ausschließlich DWD
- Météo-France-Stationen vorhanden und Frankreich ausschließlich Météo-France
- AEMET-Stationen vorhanden und Spanien ausschließlich AEMET OpenData
- GHCN-Fallbackstationen vorhanden
- keine GHCN-Doppelstationen in Deutschland, Frankreich oder Spanien
- Tagesarchive `01-01` und `12-31` vorhanden

Die 366 Tagesarchive bleiben unter `europe_stations/calendar/MM-DD.json.gz` kompatibel mit der bisherigen Kartenlogik.

## Météo-France Schnellpass-Cache (V5.2)

Die historische Frankreich-Baseline arbeitet jetzt bewusst ohne dreifache Wiederholung innerhalb desselben Laufs:

- jede noch fehlende Météo-France-Ressource wird pro Workflow-Lauf genau **einmal** heruntergeladen und gelesen;
- erfolgreiche Ressourcen werden sofort als eigener Cache-Shard gespeichert;
- fehlerhafte/trunkierte gzip-Ressourcen werden nur im Fehlerbericht notiert;
- der Job darf bei verbleibenden Fehlern rot enden, der Cache wird mit `if: always()` trotzdem gesichert;
- beim nächsten Lauf werden alle vorhandenen Shards übersprungen und damit automatisch nur die noch fehlenden/problematischen Ressourcen erneut einmal versucht.

Beispiel: Sind nach dem ersten Schnellpass 383/423 Ressourcen sauber, werden beim nächsten Lauf nur noch die 40 fehlenden Ressourcen geladen. Dadurch kostet eine reproduzierbar defekte Datei nicht drei Downloads im selben langen Erstlauf. Für die laufenden Jahresdaten bleibt die separate Retry-Logik erhalten.

## Getrennte Baseline-Workflows (empfohlen)

Damit ein Fehler eines nationalen Dienstes keine bereits berechnete Historie eines anderen Landes wiederholt, sind DWD und Météo-France getrennt.

### 1. Nur DWD

GitHub Actions → **Update DWD station cache** → Run workflow → `force=false`.

Der Job ruft ausschließlich DWD CDC auf. Er verarbeitet die historischen KL-ZIPs bis zum Vorjahr und erzeugt/prüft den DWD-Baseline-Cache. GHCN, Météo-France, AEMET und die Website-Ausgabe werden dabei nicht berechnet.

### 2. Nur Météo-France

Danach GitHub Actions → **Update Météo-France station cache** → Run workflow → `force=false`.

Der Job ruft ausschließlich die Météo-France-Ressourcen auf. Erfolgreiche Frankreich-Ressourcen werden einzeln gecacht. Scheitert der Job an einzelnen Ressourcen, wird der Cache trotzdem gespeichert; beim nächsten Lauf werden vorhandene Einzelcaches wiederverwendet und nur fehlende/problematische Dateien neu versucht.

### 3. Europa-Daten zusammenführen

Erst wenn die gewünschten Länderbaselines vorliegen, **Update Europe station records** starten. Der Gesamtworkflow kann die getrennten DWD-/Frankreich-Caches wiederverwenden und erzeugt daraus die Dateien unter `europe_stations/`.

**Wichtig:** `force=true` bei den Länder-Workflows nur verwenden, wenn absichtlich alles neu geladen werden soll. Normal immer `false`.

## Zwischenveröffentlichung Deutschland + Frankreich

Workflow: **Publish Germany + France station records** (`.github/workflows/publish-de-fr-stations.yml`).

Dieser Workflow baut **keine historischen Baselines neu auf**. Er stellt den vorhandenen DWD-Historical-Cache und den letzten erfolgreich gespeicherten Météo-France-Einzelcache wieder her, setzt daraus `europe_stations/` zusammen und committet die Frontend-Daten. Ein unvollständiger Frankreich-Zwischenstand blockiert die Veröffentlichung nicht; die Abdeckung wird in `europe_stations/index.json` unter `coverage` dokumentiert.

Standardmäßig werden vor dem Publish die Daten des laufenden Jahres aus DWD recent und Météo-France current aktualisiert. Für einen besonders schnellen reinen Historical-Publish kann `include_current_year=false` gewählt werden.
