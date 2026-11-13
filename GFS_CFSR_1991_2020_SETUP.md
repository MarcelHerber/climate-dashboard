# GFS-Analyse Europa · CFSR/CFSv2 1991–2020

## Definition

Die GFS-Temperaturkarte nutzt ausschließlich die operationellen GFS-Analysefelder
zur Vorhersagestunde f000 für 00, 06, 12 und 18 UTC. Die tägliche 2-m-Temperatur
ist das arithmetische Mittel dieser vier analysierten Werte. Ein unvollständiger
Tag wird nicht veröffentlicht. Es handelt sich um modellgestützte Analysen und
nicht um reine Beobachtungsmessungen.

Die NOAA-CPC-Beobachtungsseite bleibt unabhängig. Das GFS-Raster hat
0,5° Auflösung und wird zur Zuordnung zu denselben Ländermasken um eine halbe
Rasterzelle verschoben. Die physikalische Auflösung erhöht sich dadurch nicht.

## Referenz 1991–2020

Es ist eine tagesgenaue Normaltemperatur aus historischen NOAA-Analysen erforderlich:
- 1991–März 2011: CFSR TMP2M 00/06/12/18 UTC, Vorlauf 0.
- April 2011–2020: CFSv2 TMP2M 00/06/12/18 UTC, Vorlauf 0.
- 2-m-Temperatur ist ein Modellfeld (bei CFSR nicht zwingend direkt analysiert), kein Stationsmesswert; ein kurzer f000-Spin-up ist möglich.
- 30 vollständige Jahre, 365 Tage pro Jahr ohne den 29. Februar.
- Mittelwert derselben vier Tageszeiten; fünftägig zyklisch geglättete
  Tagesnormaltemperatur; für 29. Februar Interpolation zwischen 28.02. und 01.03.

Historische Quellen:
- NOAA NCEI: https://www.ncei.noaa.gov/products/weather-climate-models/climate-forecast-system
- NCAR CFSR: https://gdex.ucar.edu/datasets/d093000/
- NCAR CFSv2: https://gdex.ucar.edu/datasets/d094000/
- NOAA GFS: https://www.nco.ncep.noaa.gov/pmb/products/gfs/

## Verifizierte jährliche Quelldateien

Für die Referenz ist pro Jahr eine überprüfte Datei
gfs_analysis_europe/reference_sources/t2m_6h_YYYY.npz erforderlich.
Die Daten müssen aus offiziellen CFSR- oder CFSv2-Archiven kommen und
die originale Quellprüfsumme dokumentieren.

Jede Datei enthält:
- temp_c: Array (365, 4, 76, 140) in °C.
- dates: die 365 ISO-Kalendertage ohne 29. Februar.
- metadata_json: Produkt CFSR/CFSv2 (2011 geteilt), Jahr,
  Stunden [0,6,12,18], forecast_hour=0 und 12 offizielle Monatsdateien
  mit URLs und SHA-256-Prüfsummen.

Import (je Jahr aus zwölf NCEI-Monatsdateien, ca. 0,5–1 GB Originalgröße
je Monat):

\`\`\`bash
python scripts/import_cfsr_cfsv2_1991_2020.py --year 1991
\`\`\`

Erst wenn alle 30 Jahresdateien vorliegen, erzeugt
python scripts/build_gfs_cfsr_1991_2020.py
das geprüfte Archiv gfs_analysis_europe/climatology_1991_2020.npz.
Der tägliche GFS-Generator prüft Metadaten und vollständige 30 Jahre.
Ohne diese geprüfte Klimatologie veröffentlicht er ausdrücklich
KEINE GFS/CFSR-Anomalie, sondern nur die absolute Temperatur.

## Qualitätssicherung

Automatischer GitHub-Actions-Lauf:
.github/workflows/update-gfs-analysis-europe.yml

- Prüft den offiziellen NOMADS-GFS-Filter mit den vier f000-Analysen pro Tag.
- Validiert Parameter, Prognosevorlauf, Zeitstempel, Raster und Wertebereich.
- Speichert nur vollständige reale Analysetage.
- Prüft historische Referenz und Anomalien unabhängig.
- Testet Karten, Länderwerte und Exporte mit echten GFS-Daten auf Desktop und Handy.

Das kurze NOAA-NOMADS-Dreharchiv bietet keinen vollständigen historischen
Monat. Für ältere Zeiträume ist ein ergänzender GFS-Archivimport notwendig;
fehlende Tage dürfen nicht ergänzt oder als vollständiger Monat bezeichnet werden.


## 30-Jahre-Backfill auf GitHub Actions

Der Workflow `.github/workflows/backfill-cfsr-cfsv2-1991-2020.yml`
ist auf `main` registriert, damit er auf GitHub manuell aufgerufen werden kann.

- GitHub → **Actions** → **CFSR/CFSv2 1991–2020 · verified historical 2m reference**
  → **Run workflow**; unbedingt den Branch
  `feature/gfs-cfsr-1991-2020-europe-20261113` auswählen.
- Ein normaler Push führt nur sehr kurze Unit- und NCEI-GRIB2-Quellentests aus.
  **Er startet nicht** den ressourcenintensiven 360-Monats-Download.
- Der manuelle Gesamtlauf importiert 30 Jahrgänge (maximal zwei gleichzeitig),
  bewahrt Originaldatei-URLs und SHA-256-Prüfsummen auf, prüft die
  365×4×76×140-Datenfelder je Jahr und verweigert jedes unvollständige Jahr.
- Erst nach vollständigem Erfolg entstehen die überprüften Tagesnormale.
  Das Finale speichert das Referenz-Artefakt und committet es ausschließlich
  auf den GFS-Entwicklungsbranch, nicht auf die veröffentlichte `main`-Seite.
- Erst nach unabhängiger Prüfung, PR-Merge und dem nächsten gültigen
  täglichen GFS-Lauf können die Anomalien auf der veröffentlichten Website
  angezeigt werden.

**Wichtig:** Der erfolgreiche Test von GRIB2-Signaturen oder synthetischen
Gitterwerten bedeutet nicht, dass der 30-jährige Rücklauf abgeschlossen ist.
Die NCEI-Archive umfassen hunderte GB; Netzwerkunterbrechungen,
Archivdefekte oder die f000-Zeitmetadaten können einzelne Jahrgänge blockieren.
Fehlende Referenzwerte werden in keinem Fall synthetisch ersetzt.
