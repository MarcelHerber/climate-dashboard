# Mobile Navigation v1 · Climate Dashboard

Stand: 30.10.2026

## Ziel

Alle 20 derzeit über \`scripts/build_pages_site.sh\` ausgelieferten HTML-Seiten bekommen dieselbe **mobile Kategorienavigation**. Auf dem Desktop bleibt die bisherige Navigation unverändert. Meteorologische Inhalte, Karten, Messwerte, Ensemblegrafiken und Exporte werden nicht verändert.

## Mobile Informationsarchitektur (bis 800 px)

- Startseite / Übersicht
- Deutschland (Gebietsmittel, Klima-Index, HYRAS, Extreme)
- Stationen (aktuelle Messwerte, Profile, Niederschlag, Schnee, Rekorde)
- Europa & Prognosen (ERA5, Ensembles, ICON-Gefahren, Saisonprognose, Stratosphäre, MOSMIX)
- Synoptik & Karten (europäische/weltweite Isobaren, Tiefdruck-Tracker)
- Klima & Indizes (NAO/AO, Blocking, ENSO, QBO, MJO, Meereis, Schnee, ACE)
- Weitere Werkzeuge (Vergleiche, Datenstatus, Alpenwetter)

Das Menü besitzt eine textbasierte Suche ohne Serveraufrufe, eine Liste der letzten fünf angesteuerten Bereiche und direkte Navigation zu internen Tabs oder eigenständigen HTML-Seiten. Die interne Tab-Navigation von anderen Seiten ist über \`index.html#cd-tab=...\` erreichbar. Experimentell ausgeblendete Tabs bleiben ausgeblendet.

## Umsetzung

1. \`mobile_navigation.js\`: Navigation, Suchfilter, gespeicherte Direkteinstiege, Fokusführung, Escape-/Hintergrund-Schließen, Tab-Tiefenlinks.
2. \`mobile_navigation.css\`: responsives Menü, kompakte zweispaltige Direkteinstiege, besseres Layout für lange Tabellen und Mobil-Formulare, Dark-Mode-Farben.
3. \`scripts/inject_mobile_navigation.py\`: Fügt CSS/JS **nur dem erzeugten** \`_site/*.html\` hinzu, nicht den Quelldateien. Idempotent und bei unvollständigem HTML sicher abbrechend.
4. \`scripts/build_pages_site.sh\`: Alle 20 HTML-Seiten vor dem Pages-Upload auf beide Assets prüfen.
5. \`tests/test_mobile_navigation.cjs\`, \`tests/test_mobile_navigation_build.py\`, \`test-mobile-navigation.yml\`: automatisierte Prüfung der Navigation und des Builds.

Mobile Navigation wird nur bei <=800 px angezeigt. Ohne JavaScript bleibt auf der Hauptseite das bisherige mobile Dropdown erhalten; auf den Unterseiten bleiben die ursprünglichen Kopfzeilen und Links bestehen.

## Akzeptanzkriterien und Geräteabnahme

Vor einer finalen Live-Freigabe im Browser unter 320, 360, 390, 428, 768 und 800 px prüfen:

- Menü auf der Startseite und auf jeder eigenständigen Seite erreichbar; auf dem Desktop kein dupliziertes Menü
- Alle 20 veröffentlichten HTML-Seiten erreichbar; alle regulären \`switchTab()\`-Ziele erreichbar
- Menüsuchfeld findet Begriffe mit Umlauten und Fachabkürzungen
- Kategorie öffnet die richtige Liste, Escape/Schließen/Hintergrund schließen, Fokus kehrt zum Auslöser zurück
- „Zuletzt geöffnet“ behält die letzten fünf Bereiche, ohne Wetterdaten an Browser-Speicher zu senden
- Keine unbeabsichtigte **horizontale Seitenscrollleiste**; breite Fach-Tabellen dürfen innerhalb des Tabellencontainers horizontal scrollen
- Karten/Diagramme bleiben steuerbar, Download-Buttons funktionieren, Dropdowns passen in den Bildschirm
- Light/Dark Mode, Hoch-/Querformat, iOS Safari und Android Chrome
- Falls neue HTML-Seiten hinzukommen, ihre Navigation im Kategorienkatalog ergänzen und Tests beibehalten

**Noch offen:** Eine echte gerätebasierte oder Browser-Emulations-Abnahme sowie die Bestätigung des Live-GitHub-Pages-Deploys. Die GitHub-Actions-Ausführung ist in dieser Umgebung nicht auslesbar.
