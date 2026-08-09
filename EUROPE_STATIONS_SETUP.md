# Europa-Stationen · Stations-V1

## Was diese Version erzeugt

Der neue Haupt-Tab **Europa-Stationen** zeigt eine helle Europakarte mit Stationsrekorden aus NOAA/NCEI GHCN-Daily.

- TMAX: höchste Tageshöchsttemperatur
- TMIN: niedrigste Tagestiefsttemperatur
- absoluter Stationsrekord
- Rekord eines frei wählbaren Kalendertags
- neue Kalendertagsrekorde im laufenden Jahr
- Rekorddatum, vorheriger Rekord und Differenz
- Stationsname, Land, Höhe, Messbeginn/-ende und Zahl der Messjahre
- Länderfilter und Mindestlänge der Messreihe

Die Frontend-Dateien werden unter `europe_stations/` erzeugt. Die 366 Kalendertage liegen platzsparend als gzip-Dateien unter `europe_stations/calendar/`.

## Erster Lauf

1. Die Dateien aus `index.zip` in das Repository übernehmen.
2. GitHub → **Actions** → **Update Europe station records**.
3. **Run workflow** starten.
4. Beim ersten Lauf `force_baseline = false` lassen.

Der erste Lauf ist deutlich größer: Das Skript streamt den vollständigen GHCN-Daily-Archivbestand, behält aber nur europäische TMAX/TMIN-Daten und schreibt das große Roharchiv nicht auf die GitHub-Platte. Der daraus erzeugte historische Basisbestand wird über GitHub Actions gecacht.

Danach lädt der tägliche Lauf im Wesentlichen nur noch die aktuelle `YYYY.csv.gz`-Jahresdatei. Einmal pro neuem Kalendermonat wird der historische Cache automatisch frisch aufgebaut, damit auch rückwirkende NOAA-Korrekturen regelmäßig einfließen.

## Qualitätsregel

Für die Rekordberechnung werden nur TMAX/TMIN-Werte mit **leerem GHCN Q-FLAG** verwendet. Werte, die eine GHCN-Qualitätsprüfung nicht bestanden haben, werden damit nicht für Rekorde verwendet.

## Datenquelle / Ausbau

Stations-V1 verwendet GHCN-Daily als einheitliche Europa-Basis. Das Frontend-Schema enthält pro Station ein `source`-Feld. Dadurch können später z. B. Deutschland, Frankreich oder Spanien mit DWD-, Météo-France- bzw. AEMET-Daten überschrieben werden, ohne die Kartenlogik neu zu bauen.
