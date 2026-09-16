# Meere / SST – Europa

**Datum:** 2026-09-16  
**Status:** Design-Spezifikation für Stufe 1  
**Repository:** `MarcelHerber/climate-dashboard`

## 1. Ziel

Das Climate Dashboard erhält einen neuen eigenständigen Hauptreiter **„Meere / SST“**. Stufe 1 stellt tägliche Meeresoberflächentemperaturen (SST) und tägliche SST-Anomalien für fünf feste europäische bzw. nordatlantische Regionen bereit. Die Darstellung soll bewusst meteorologisch-clean bleiben und sich optisch in das bestehende Dashboard einfügen.

Der Bereich wird von Anfang an so aufgebaut, dass spätere Animationen für 7, 30 und 90 Tage sowie frei wählbare Zeiträume ohne Umbau des Archivs ergänzt werden können.

## 2. Datenquellen

### 2.1 Aktuelle und historische Tages-SST

Primärquelle ist **NASA/JPL MUR SST v4.1** (`MUR-JPL-L4-GLOB-v4.1`).

- globales GHRSST Level-4-Produkt
- räumliche Auflösung: 0,01°
- tägliche Felder
- verfügbar seit 2002-05-31
- Variable: `analysed_sst` in Kelvin
- zusätzliche Felder u. a. `mask`, `sea_ice_fraction`, `analysis_error`
- Zugriff bevorzugt über NASA Earthdata / PO.DAAC Harmony-Subset oder `earthaccess`

Offizielle Produktseite: `https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1`

### 2.2 Klimareferenz

Referenz ist die **NOAA/NCEI OISST 1991–2020 SST-Normale**.

- Basis: NOAA Daily Optimum Interpolation SST (OISST)
- Referenzperiode: 1991–2020
- räumliche Auflösung: 0,25°
- globale tägliche Klimatologie
- NetCDF
- NCEI Accession 0282469

Offizielle Quelle: `https://www.ncei.noaa.gov/archive/archive-management-system/OAS/bin/prd/jquery/accession/details/282469`

### 2.3 Anomalieberechnung

Für einen Kalendertag `D` gilt:

```text
SST-Anomalie(D) = MUR-SST(D) - OISST-Tagesnormal 1991–2020(D)
```

Die OISST-Tagesnormale wird auf das benötigte MUR-Gitter interpoliert. Die Interpolation darf keine Werte über Land in Meereszellen hineinziehen. Nach der Interpolation wird immer erneut mit der MUR-Wasser-/Landmaske maskiert.

Für den 29. Februar wird ausschließlich ein vorhandener 29.-Februar-Normalwert verwendet. Falls die gewählte NOAA-Datei keinen expliziten 29. Februar enthält, wird der Referenzwert reproduzierbar als Mittel aus 28. Februar und 1. März erzeugt und im Manifest dokumentiert.

## 3. Regionen

Stufe 1 enthält fünf feste Kartenausschnitte. Die Bounds liegen zentral in einer Konfigurationsdatei und werden nicht im Frontend dupliziert.

| ID | Name | Länge | Breite |
|---|---|---|---|
| `europe` | Europa gesamt | 30°W bis 45°E | 30°N bis 72°N |
| `mediterranean` | Mittelmeer | 6°W bis 38°E | 29°N bis 47°N |
| `north_baltic` | Nordsee + Ostsee | 12°W bis 32°E | 48°N bis 66°N |
| `north_atlantic` | Nordatlantik | 60°W bis 20°E | 25°N bis 70°N |
| `nordic_seas` | Nordmeer / Skandinavien | 45°W bis 50°E | 55°N bis 82°N |

Der Nordmeer-Ausschnitt umfasst insbesondere Island, Grönlandsee, Norwegische See, Barentssee und Skandinavien.

Die Bounds gelten als Startwerte und liegen bewusst in Konfiguration, damit spätere Feinjustierungen ohne Änderung der Datenlogik möglich sind.

## 4. Ansichten und Skalen

### 4.1 Absolute SST

- Einheit: °C
- feste Skala in Stufe 1: **−2 bis +34 °C**
- identische Skala für alle Regionen
- spätere regionsabhängige Skalen bleiben möglich, sind aber nicht Teil von Stufe 1

### 4.2 SST-Anomalie

- Einheit: °C bzw. K-Differenz
- feste symmetrische Skala: **−6 bis +6 °C**
- identische Grenzen für alle Regionen und Tage
- unterhalb −6 und oberhalb +6 werden Endfarben verwendet
- Nullpunkt neutral

### 4.3 Maskierung

- Land: hellgrau / neutral
- Meer: Datenfarbe
- keine Städte oder Stationsmarker in Stufe 1
- Küstenlinien und Ländergrenzen dezent
- Meereis-bedeckte Zellen werden nicht als normale offene SST interpretiert; Zellen oberhalb eines konfigurierbaren `sea_ice_fraction`-Schwellwerts werden neutral maskiert. Startwert: 0,15.

## 5. Kartendesign

Die Karten bleiben bewusst clean.

Pflichtelemente:

- Kartenausschnitt
- Küstenlinien
- dezente Ländergrenzen
- Titel
- Datum
- Datenquelle
- Einheit / Farbskala
- bei Anomalien: Hinweis `Referenz 1991–2020`

Keine Städte, Pfeile, Extremwertmarker oder automatische Text-Annotations in Stufe 1.

Das Frontend legt Titel, Datum und Legende möglichst als HTML/Canvas-Overlay über die Rasterdarstellung. Dadurch können dieselben Archivbilder für Bildschirmdarstellung, PNG- und PDF-Export verwendet werden.

## 6. Frontend

### 6.1 Hauptnavigation

Neuer Hauptreiter:

```text
Meere / SST
```

### 6.2 Steuerelemente

Stufe 1 enthält:

- Region-Auswahl mit den fünf festen Regionen
- Ansicht: `SST absolut` / `SST-Anomalie`
- Datumsfeld
- `← Vortag`
- `Heute / neuester verfügbarer Tag`
- `Folgetag →`
- 30-Tage-Zeitleiste
- PNG-Download
- PDF-Download

### 6.3 30-Tage-Zeitleiste

- zeigt die letzten 30 verfügbaren Kalendertage um das gewählte Datum
- lädt keine 30 Vorschaubilder
- nur Datumsmarker / kompakte Tagesfelder
- gewählter Tag klar markiert
- Klick wechselt direkt auf den Tag
- fehlende Tage werden deaktiviert markiert

### 6.4 Statusinformationen

Oberhalb oder unterhalb der Karte:

- `Datenstand: YYYY-MM-DD`
- `Quelle: NASA/JPL MUR SST v4.1`
- bei Anomalie zusätzlich `Referenz: NOAA OISST 1991–2020`

### 6.5 Fehlende Daten

Es wird niemals eine leere oder veraltete Karte stillschweigend als aktueller Tag angezeigt.

Mögliche Zustände:

- Datum verfügbar → Karte anzeigen
- Datum fehlt → klarer Hinweis `Für dieses Datum liegt keine SST-Karte vor.`
- neuester Tag noch nicht vollständig → letzten vollständig publizierten Tag anzeigen und dessen Datum nennen

## 7. Archiv

### 7.1 Zeitraum

Rückwirkender Aufbau ab:

```text
2020-01-01
```

Danach tägliche Fortschreibung.

### 7.2 Trennung vom Hauptbranch

Der Hauptbranch enthält nur:

- Frontend-Code
- Konfiguration
- kleine Manifest-/Indexdateien
- optional aktuelle Preview-Dateien

Historische Karten liegen auf einem separaten Veröffentlichungszweig, vorgesehen:

```text
sst-archive
```

Damit wird das Hauptrepository nicht durch tausende Binärdateien aufgebläht.

### 7.3 Archivformat

Für die Webanzeige wird pro Region, Ansicht und Tag nur **eine komprimierte Web-Rasterdatei** gespeichert, bevorzugt WebP. PNG und PDF werden nicht zusätzlich für jeden Archivtag persistiert, sondern beim Download aus der geladenen Darstellung erzeugt.

Vorgabe für Stufe 1:

- aktuelle Karten: höhere Renderauflösung
- historische Web-Karten: für Bildschirmdarstellung optimierte Auflösung
- keine dauerhafte Speicherung der MUR-Rohdaten nach erfolgreicher Kartenproduktion
- keine dauerhafte Speicherung identischer Klimareferenzdateien pro Job

Ein Storage-Guard protokolliert die resultierende Archivgröße. Sollte der Archivzweig durch den Backfill unvertretbar groß werden, wird vor einer weiteren Qualitätssteigerung zuerst das Rasterformat bzw. die Archivauflösung optimiert; der Hauptbranch bleibt davon unberührt.

### 7.4 Dateistruktur

Vorgesehen:

```text
sst-archive/
  manifest.json
  2020/
    01/
      europe/
        absolute/
          2020-01-01.webp
        anomaly/
          2020-01-01.webp
      mediterranean/
      north_baltic/
      north_atlantic/
      nordic_seas/
  2021/
  ...
```

Falls sich beim Speicher-Prototyp zeigt, dass eine alternative physische Ablage deutlich kleiner ist, darf die interne Struktur geändert werden. Die öffentliche Manifest-Schnittstelle bleibt stabil.

## 8. Manifest-Schnittstelle

Das Frontend soll keine Dateipfade selbst erraten. Ein Manifest bildet die öffentliche Schnittstelle zwischen Builder und Website.

Beispiel:

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-16T06:00:00Z",
  "data_through": "2026-09-14",
  "archive_start": "2020-01-01",
  "source": {
    "sst": "MUR-JPL-L4-GLOB-v4.1",
    "reference": "NOAA OISST 1991-2020"
  },
  "scales": {
    "absolute": [-2, 34],
    "anomaly": [-6, 6]
  },
  "regions": {
    "europe": {
      "label": "Europa gesamt",
      "bounds": [-30, 30, 45, 72]
    }
  },
  "available_dates": ["2020-01-01", "..."]
}
```

Für große Datumslisten kann `available_dates` später durch Jahres-/Monatsindizes ersetzt werden, ohne das visuelle Frontend grundlegend zu ändern.

## 9. Datenpipeline

### 9.1 Tageslauf

Geplanter Ablauf:

1. neuestes bereits publiziertes SST-Datum lesen
2. bei PO.DAAC den neuesten vollständig verfügbaren MUR-Tag bestimmen
3. benötigte MUR-Subsets laden
4. Kelvin → Celsius
5. passende OISST-Tagesnormale 1991–2020 laden bzw. aus lokalem Workflow-Cache lesen
6. OISST auf Zielgitter interpolieren
7. Land-/Meereis-Masken anwenden
8. Anomalie berechnen
9. fünf Regionskarten für absolute SST rendern
10. fünf Regionskarten für Anomalien rendern
11. Ausgaben validieren
12. Manifest aktualisieren
13. **erst nach erfolgreicher Gesamtvalidierung publizieren**

Ein Tag gilt erst als veröffentlicht, wenn alle zehn benötigten Karten (5 Regionen × 2 Ansichten) valide vorhanden sind.

### 9.2 Aktualisierungsfrequenz

Der Workflow kann täglich laufen. Wegen der Latenz von MUR darf er nicht annehmen, dass das heutige Datum bereits verfügbar ist. Er veröffentlicht den neuesten tatsächlich vollständigen MUR-Tag.

### 9.3 Authentifizierung

MUR-Zugriff wird über NASA Earthdata realisiert. Zugangsdaten bzw. Token liegen ausschließlich als GitHub Actions Secret vor und niemals im Repository.

Vorgesehene Secret-Strategie:

- bevorzugt Earthdata-Token, sofern der verwendete Client dies stabil unterstützt
- alternativ `EARTHDATA_USERNAME` + `EARTHDATA_PASSWORD`

Die Klimareferenz wird, soweit möglich, über frei zugängliche NOAA/NCEI-Downloads bezogen und workflowseitig gecacht.

## 10. Backfill 2020 bis heute

Der historische Aufbau wird nicht als ein einzelner gigantischer Job ausgeführt.

Vorgabe:

- Batch-Verarbeitung nach Monat oder begrenzten Datumsblöcken
- Resume-fähig
- vorhandene valide Dateien überspringen
- Fehler in einem Tag dürfen nicht bereits abgeschlossene Monate zerstören
- Backfill-Manifest wird erst nach validierten Batches erweitert

Der Backfill muss jederzeit ohne Verlust bereits produzierter Daten fortgesetzt werden können.

## 11. Workflow-Struktur

Vorgesehene Dateien:

```text
scripts/sst/
  config.py
  sources.py
  climatology.py
  processing.py
  render.py
  manifest.py
  build_daily.py
  backfill.py

.github/workflows/
  update-sst-europe.yml
  backfill-sst-europe.yml

tests/
  test_sst_config.py
  test_sst_climatology.py
  test_sst_processing.py
  test_sst_manifest.py
  test_sst_render.py
```

Die genaue Dateiteilung kann beim Implementierungsplan an vorhandene Repo-Konventionen angepasst werden. Datenquelle, Verarbeitung, Rendering und Manifest bleiben logisch getrennte Komponenten.

## 12. Vorbereitung für Animationen

Animationen sind **nicht Teil von Stufe 1**, aber das Archiv muss sie ermöglichen.

Spätere Modi:

- 7 Tage
- 30 Tage
- 90 Tage
- freier Start-/Endzeitraum

Dafür müssen:

- alle Tageskarten eine identische Pixelgeometrie je Region besitzen
- Farbskalen fest sein
- Titel-/Legendenpositionen stabil sein
- das Manifest lückenhafte Tage eindeutig melden

Die spätere MP4-Erzeugung kann sich konzeptionell am bereits vorhandenen HYRAS-Animationspfad orientieren.

## 13. Export

### PNG

Der Browser erzeugt ein exportierbares Canvas aus:

- Kartenraster
- Titel
- Datum
- Farbskala
- Quellenangabe

### PDF

PDF wird aus derselben zusammengesetzten Darstellung erzeugt, damit PNG und PDF optisch identisch sind.

Es werden keine separaten PDFs für jeden historischen Tag im Archiv gespeichert.

## 14. Fehlerbehandlung und Publikationssicherheit

Pflichtprüfungen vor Publikation:

- MUR-Feld vorhanden und nicht leer
- plausible Dimensionen
- mindestens ein gültiger Meerespixel pro Region
- Wertebereich der absoluten SST plausibel
- Anomaliefeld enthält endliche Werte
- alle fünf Regionen vorhanden
- beide Ansichten vorhanden
- Dateigröße > Mindestschwelle
- Manifest verweist nur auf tatsächlich existierende Dateien

Bei Fehler:

- bisheriger veröffentlichter Stand bleibt unverändert
- Workflow schlägt sichtbar fehl
- kein teilweise aktualisiertes `data_through`

## 15. Tests

### Unit-Tests

- Region-Bounds und IDs
- Kelvin-zu-Celsius-Konvertierung
- Auswahl des richtigen Klimatages
- Schaltjahr / 29. Februar
- Regridding-Maske
- Meereis-Maske
- feste Skalen
- Manifest-Erzeugung
- URL-/Pfadauflösung

### Integrations-Test

Ein kleiner fest definierter Testtag erzeugt für eine kleine Testregion:

- absolute SST
- Anomalie
- Manifest-Eintrag

Ohne vollständigen historischen Backfill.

### Frontend-Tests

- Reiter erreichbar
- Regionenwechsel
- Ansichtswechsel
- Vortag/Folgetag
- 30-Tage-Leiste
- fehlendes Datum
- PNG-Export
- PDF-Export

## 16. Performance

- keine Roh-NetCDF-Dateien an Browser ausliefern
- keine 30 Kartenvorschauen für die Zeitleiste laden
- Bilder lazy-loaden
- Klimatologie im Workflow cachen
- MUR nur für benötigten räumlichen Ausschnitt laden
- Frontend lädt beim Wechsel genau die benötigte Region/Ansicht/Datum-Kombination

## 17. Abgrenzung Stufe 1

Nicht enthalten:

- Städte-/Ortsmarker
- Extremwertmarker
- freie Kartenbounds
- frei zoombare wissenschaftliche Rasterkarte
- 7/30/90-Tage-MP4
- frei wählbare Animation
- monatliche SST-Mittel
- monatliche SST-Anomalien
- weitere Ozeanparameter
- regionale automatische Farbskalen

Diese Punkte bleiben mögliche Stufen 2/3.

## 18. Akzeptanzkriterien für Stufe 1

Stufe 1 ist fertig, wenn:

1. der neue Hauptreiter `Meere / SST` auf der Seite erreichbar ist,
2. alle fünf Regionen wählbar sind,
3. absolute SST und SST-Anomalie dargestellt werden,
4. Anomalien fest −6 bis +6 °C und absolute SST fest −2 bis +34 °C verwenden,
5. Datum, Vor-/Folgetag und 30-Tage-Leiste funktionieren,
6. der neueste vollständig verfügbare MUR-Tag automatisch veröffentlicht wird,
7. PNG- und PDF-Export funktionieren,
8. historische Tage ab 2020 über das getrennte Archiv adressierbar sind,
9. fehlende Tage sauber behandelt werden,
10. ein fehlerhafter Tageslauf keinen teilweise aktualisierten Stand veröffentlicht,
11. Tests für Verarbeitung, Manifest und Frontend bestehen.

## 19. Noch vor der Implementierung zu verifizieren

Diese Punkte werden im Implementierungsplan als erste technische Probes behandelt:

1. stabilster automatisierter MUR-Zugriff aus GitHub Actions (Harmony vs. `earthaccess`),
2. konkreter NetCDF-Dateiname und Variablenname der NOAA/NCEI-Tagesnormalen,
3. tatsächliche Dateigröße einer Woche WebP für alle fünf Regionen und beide Ansichten,
4. daraus abgeleitete endgültige Archivauflösung für den Backfill,
5. CORS-/Abrufverhalten des geplanten `sst-archive`-Branches aus GitHub Pages.

Diese Verifikationen dürfen die öffentliche Manifest-Schnittstelle und die bereits festgelegten Nutzerfunktionen nicht verändern; sie bestimmen nur die effizienteste technische Umsetzung.