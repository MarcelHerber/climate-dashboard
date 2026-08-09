# Europa-Stationen · Stations-V2

## Was diese Version zeigt

Der Haupt-Tab **Europa-Stationen** nutzt die in Stations-V1 erzeugten GHCN-Daily-Daten weiter. Für V2 ist **kein neuer historischer Basisaufbau** nötig.

Neu im Frontend:

- Top-20-Ranking für die aktuell gewählte Rekordansicht
- Rekordjagd für einen frei gewählten Kalendertag: aktueller Jahreswert gegen bisherigen Tagesrekord
- Anzeige des Abstands zum Rekord, eingestellter Rekorde und gebrochener Rekorde
- Stationssuche nach Name, Stations-ID oder Land
- Klick auf einen Ranking-Eintrag springt direkt zur Station und öffnet das Popup
- neue Rekorde des laufenden Jahres mit Länder-Ranking
- europäischer Extremwert des gewählten Kalendertags sowie Extremwert des laufenden Jahres, sofern für diesen Tag bereits Daten vorliegen
- weiterhin Länderfilter und Mindestlänge der Messreihe

Die helle Karte verwendet OpenStreetMap-Daten im CARTO-Light-Stil. Die Stationsdaten liegen unter `europe_stations/`; die 366 Kalendertage werden platzsparend als gzip-Dateien unter `europe_stations/calendar/` gespeichert.

## Datenworkflow

Der bestehende Workflow **Update Europe station records** bleibt kompatibel. Er erzeugt weiterhin den Stations-Payload und die 366 Tagesarchive, die Stations-V2 direkt lesen kann.

Beim ersten Datenlauf:

1. GitHub → **Actions** → **Update Europe station records**.
2. **Run workflow** starten.
3. `force_baseline = false` lassen.

Nach einem bereits erfolgreichen Stations-V1-Erstlauf muss für die neuen V2-Oberflächenfunktionen kein historischer Neuaufbau erzwungen werden. Der vorhandene Cache kann weiterverwendet werden.

## Qualitätsregel

Für die Rekordberechnung werden nur TMAX/TMIN-Werte mit **leerem GHCN Q-FLAG** verwendet. Werte, die eine GHCN-Qualitätsprüfung nicht bestanden haben, werden nicht für Rekorde verwendet.

## Datenquelle / späterer Ausbau

GHCN-Daily bleibt zunächst die einheitliche Europa-Basis. Das Frontend-Schema enthält pro Station ein `source`-Feld. Dadurch können später Deutschland, Frankreich oder Spanien mit DWD-, Météo-France- bzw. AEMET-Daten überschrieben werden, ohne die Karten- und Rankinglogik neu zu bauen.
