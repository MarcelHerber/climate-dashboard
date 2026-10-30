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

## Mobile Detaildarstellung (Iteration 2)

- `mobile_content.css` verbessert für Bildschirmbreiten von 320 bis 600 px die Platzierung von Diagrammen, Legenden, Buttons, Formularen, Kartenbildern und wissenschaftlichen Tabellen.
- `mobile_content.js` registriert ein optionales Chart.js-Darstellungsplugin: Bei höchstens 430 px werden maximal fünf Zeitachsenmarkierungen angezeigt, Beschriftungen bleiben waagerecht und Chart-Legenden nutzen kompaktere Beschriftungsfelder. **Datenreihen, Ensemblemitglieder, UTC-Zeiten, Einheiten, Achsen-Minima/Maxima und Prognosehorizonte bleiben unverändert.** Beim Vergrößern werden die ursprünglichen Darstellungseinstellungen wiederhergestellt.
- Breite Tabellen mit horizontalem Überlauf erhalten auf schmalen Geräten einen Hinweis „Seitlich wischen“, ohne Zeilen oder Spalten aus den Originaldaten zu entfernen.
- Auswahllisten erhalten eine 16-px-Schriftgröße gegen iOS-Safari-Fokuszoom. Exportaktionen bleiben vollständig benannt und können bei 320 px umbrechen.
- Mobile Startseiten-Direkteinstiege stehen zweispaltig; Inhaltsbilder werden maximal bildschirmbreit gezeigt. Keine Animationen oder Transformationen an meteorologischen Rasterbildern.
- `tests/test_mobile_content.cjs` überprüft insbesondere, dass kompaktere Chart-Achsen nach dem Wechsel auf Desktop die ursprüngliche Darstellung zurückbekommen und keine Messwerte verändert werden.
- Der universelle Pages-Injektor veröffentlicht alle vier neuen Mobile-Assets auf allen Root-Unterseiten.

Hinweis zu Exporten: Die Funktionalität von PNG/PDF/CSV wird nicht ersetzt oder verändert. Auf einem schmalen Gerät kann ein Canvas-PNG die reduzierten Bildschirm-Achsenticks abbilden; die Messdaten bleiben vollständig. Eine komplett unabhängige Print-/Export-Diagrammgestaltung wäre ein zusätzlicher Ausbauschritt.

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
