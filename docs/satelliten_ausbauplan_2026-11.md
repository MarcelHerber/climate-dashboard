# Satellitenstudio – Ausbauplan und technische Freigabekriterien

Stand: 11. November 2026. Repository: MarcelHerber/climate-dashboard.
Grundsatz: Bestandsfunktionen (MTG-I1 RGB, MTG-I2-Status, alle sechs Ausschnitte,
UTC-Steuerung, 6–48-Bilder-Film, PNG, Dark Mode und Mobilnavigation) bleiben erhalten.
Neue Datenprodukte werden erst nach **GetCapabilities + echtem GetMap** freigeschaltet.

## Phase 0 – Ausgangszustand und Referenztests

- WMS: https://view.eumetsat.int/geoserver/wms, WMS 1.1.1.
- Bestehende Produkte: mtg_fd:rgb_geocolour, mtg_fd:rgb_dust,
  mtg_fd:rgb_cloudtype. Alle neuen Layer bekommen separate überprüfte Zeitachsen.
- Vorheriger Status vom 11.11.2026, 07:50 UTC: Einzelbild-PNGs der drei
  Produkte positiv geprüft; GeoColour-Vorschau HTTP 504. WMS-Störungen
  dürfen nicht zu erfundenen UTC-Zeiten führen.
- Bisherige End-to-End-Tests: node --test tests/test_satelliten_ui.cjs
  tests/test_satellite_film.cjs; Chromium Desktop 1440×900 und Handy 390×844,
  echte EUMETSAT-Bilder und Zeitdimension.
- Keine Änderung an passwortgeschützten Seiten oder ihrem Zugriffssystem.

## Phase 1 – geografische Orientierung (begonnen)

- Vorhandene lokale Datei data/blocking/borders_50m.json (Natural Earth,
  1:50m, public domain) statt externem Kachelservice verwenden.
- Vektorküsten/-ländergrenzen und benannte Städte optional zuschalten;
  präzise Projektion passend zur vom WMS gelieferten EPSG:4326-BBOX.
- Bekanntes Limit des Materials: -78–65° Länge, 25–85°N; außerhalb
  keinerlei falsche Linien zeichnen. Azoren, Madeira, Kanaren und Neufundland
  sind von den vorhandenen Küstenlinien erfasst.
- Erdscheibe AUTO:97004: keine lat/lon-Overlays zeichnen, bis eine
  geostationäre Transformation gesondert gerechnet und getestet wurde.
- Akzeptanz: Desktop/Mobil, Wechsel zwischen allen Ausschnitten, beide
  Schalter, Filmstillstand/-wiedergabe, keine schiefen Grenzen; lokale
  GeoJSON-Quelle muss im GitHub-Pages-Artefakt liegen.
- Folge: dieselben Linien optional auch auf exportierte PNGs zeichnen.

## Phase 2 – zusätzliche FCI-Produkte (technische Prüfung begonnen)

- Nur Layer aus der **aktuellen** EUMETView-GetCapabilities-Liste
  (MTG-FCI), beginnend mit Airmass RGB, Night Microphysics,
  IR 10.5 µm, Convection/Severe Storms und Fire Temperature.
- scripts/audit_satellite_layers.py sammelt reale Layernamen, Titel,
  WMS-Zeitdimension, testet ausgewählte GetMap-PNGs und speichert einen
  nachweisbaren Prüfbericht unter data/satellite_layer_discovery_latest.json.
- UI-Gate: Layer gefunden, mindestens ein echtes PNG und konkreter
  UTC-Zeitpunkt nachgewiesen, Daten aktuell. Historische MSG-Produkte
  niemals als MTG-I1 ausgeben.
- Je Produkt Legende/meteorologische Interpretation und Helligkeits-/Nacht-
  Einschränkungen dokumentieren; zusätzliches FCI-Band nicht mit
  einer RGB-Temperaturmessung verwechseln.
- Tests: tatsächliche PNG-Signatur/Größe, WMS-CORS, alle sechs Regionen,
  Mobilansicht, Bildzeitwechsel und Produktwechsel.

## Phase 3 – Isobaren und Fronten (Quellenaudit, keine ungenaue Überlagerung)

- Ein 5-hPa-Isobar-Layer benötigt **georeferenzierte MSLP-Gitterdaten**
  (z. B. amtliches ICON-/ECMWF-Feld) plus explizite Analyse-/Vorhersagezeit.
  Die Gitter in identische Kartenprojektion bringen und Konturen 5 hPa
  zeichnen. Höhen des Druckfelds und die Bezugszeit in der Legende führen.
- Die bereits gesammelten amtlichen Boden-/Frontenkarten in
  isobaren_original.js sind großteils Original-Grafiken mit
  uneinheitlichen Projektionen. Sie sind **nicht automatisch**
  EPSG:4326-Overlays; zuerst eine synchronisierte Vergleichsansicht anbieten.
- Nur georeferenzierte Fronten als echte Vektoren überlagern. Quellenstatus,
  Nutzungsbedingungen, Prognose vs. Analyse und Zeitdifferenz getrennt prüfen.
- Abnahme: gleiche BBOX, sichtbare Küstenübereinstimmung, valide UTC,
  5-hPa-Schritte und kein Ausgeben von Modellprognosen als Beobachtung.

## Phase 4 – GIF und MP4 (Plattformprüfung)

- Zunächst MediaRecorder.isTypeSupported, canvas.captureStream und
  VideoEncoder auf Desktop/Mobil im Chromium-Test erfassen.
- MP4/H.264 nur anbieten, wenn die tatsächliche Laufzeit es unterstützt
  oder ein verifizierter serverseitiger FFmpeg-Export eingerichtet ist.
  Ein WebM-Blob darf **nie** in .mp4 umbenannt werden.
- GIF benötigt einen eigenen kleinen Encoder oder verifizierten Exportjob;
  36–48 Bilder bei 320/480/720 px und Dateigrößen-/Speicherlimits testen.
- Filmexport enthält UTC je Frame, Auflösung, Produkt, Quelle und
  EUMETSAT-/ggf. NASA-Hinweis. Kein Export unbestätigter Bildzeitpunkte.
- Test: Ergebnis mit einem echten Decoder/ffprobe/Pillow öffnen,
  Bildanzahl und Zeitstempel prüfen, Desktop-/Handy-Download.

## Phase 5 – Performance und Stabilität

- WMS-HTTP-500/504, Timeouts, CORS, fehlende Frames und Aussetzer
  gesondert protokollieren. Höchstens zwei gleichzeitige Vorschau-Requests,
  Abbruch bei Produkt-/Regionwechsel, keine wiederholten Downloads
  während des Abspielens.
- Sparsame 320px-Vorschau bei langen Filmen, größere PNGs nur auf
  ausdrücklich gewählte Qualitätsstufe.
- Bereits geladene Frames über Produkte/Regionen hinweg nur weiterverwenden,
  wenn Layer+BBOX+Zeit+Größe identisch sind (kein veraltetes Falschbild).
- Messen statt behaupten: Zeit bis erstes Bild, Zeit bis Filmstart,
  Bytes pro Film, p50/p95 der WMS-Laufzeiten und Abbruchquote.
- Der öffentliche Status kennzeichnet Quellenfehler statt "live" zu erfinden.

## Reihenfolge und Freigabe

1. Phase 1 komplett testen und veröffentlichen.
2. Phase 2 durch echte MTG-PNGs und Zeitdimension absichern, dann UI erweitern.
3. Phase 3 zunächst side-by-side/Analyse-Zeit, anschließend georeferenzierte
   Konturen und erst danach Fronten.
4. Phase 4 nur für nachweislich decodierbare GIF-/MP4-Dateien freigeben.
5. Phase 5 läuft begleitend als kontinuierliche Qualitätskontrolle.

Referenzen: Natural Earth (https://www.naturalearthdata.com/);
EUMETSAT EUMETView (https://view.eumetsat.int/);
WMS GetCapabilities (https://view.eumetsat.int/geoserver/wms?service=WMS&version=1.1.1&request=GetCapabilities).
