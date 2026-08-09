# Europa-Stationen · Stations-V3

## Neu in V3

Deutschland wird nicht mehr aus GHCN-Daily dargestellt, sondern direkt aus den täglichen **DWD-CDC-KL-Daten**. Für alle übrigen europäischen Länder bleibt GHCN-Daily zunächst die gemeinsame Basis. Dadurch entstehen auf der Deutschlandkarte keine parallelen DWD-/GHCN-Doppelstationen.

Die V2-Oberfläche bleibt erhalten:

- TMAX/TMIN
- absolute Stationsrekorde
- Kalendertagsrekorde
- Rekordjagd im laufenden Jahr
- neue Rekorde im laufenden Jahr
- Top 20
- Länderfilter, Mindest-Messjahre und Stationssuche

Im Stations-Popup steht jetzt die jeweilige Quelle und die dazugehörige Qualitätsregel.

## Datenquellen

### Deutschland

DWD Climate Data Center, tägliche Klimadaten `daily/kl/`:

- `historical/` für die historische Basis
- `recent/` für das laufende Jahr
- ausgewertet werden `TXK` (Tagesmaximum) und `TNK` (Tagesminimum)
- DWD-Fehlwerte werden verworfen

Die DWD-Stations-ID wird intern als `DWD:xxxxx` gespeichert.

### Übriges Europa

NOAA/NCEI GHCN-Daily bleibt der Fallback. Deutschland (`GM`) wird bereits beim Einlesen aus dem GHCN-Stationssatz entfernt. Für GHCN werden nur TMAX/TMIN mit leerem Q-FLAG für Rekorde verwendet.

## Erster V3-Lauf

GitHub → **Actions** → **Update Europe station records** → **Run workflow**.

Beide Schalter zunächst auf `false` lassen:

- `force_baseline = false`
- `force_dwd_baseline = false`

Der Workflow versucht zuerst, den vorhandenen Stations-V2-GHCN-Cache wiederzuverwenden. Wenn dieser vorhanden ist, muss GHCN nicht erneut komplett aufgebaut werden. Neu aufgebaut wird beim ersten V3-Lauf lediglich der historische DWD-Deutschland-Cache. Dieser wird anschließend zusammen mit dem GHCN-Cache unter einem V3-Cache-Schlüssel gespeichert.

## Spätere tägliche Läufe

Nach erfolgreichem ersten V3-Lauf werden beide historischen Baselines wiederverwendet. Der Workflow liest dann nur noch das laufende GHCN-Jahr und die DWD-`recent`-Dateien neu ein und schreibt `europe_stations/index.json` sowie die 366 Tagesarchive neu.

`force_dwd_baseline = true` ist nur nötig, wenn der historische DWD-Bestand bewusst vollständig neu aufgebaut werden soll. `force_baseline = true` erzwingt sowohl GHCN als auch DWD neu und sollte im Normalbetrieb ausgeschaltet bleiben.

## Payload

`europe_stations/index.json` hat in Stations-V3 `payload_version: 3` und enthält zusätzlich eine `sources`-Übersicht. Der Workflow prüft nach dem Lauf automatisch, dass deutsche Stationen ausschließlich mit `source: "DWD CDC"` enthalten sind.
