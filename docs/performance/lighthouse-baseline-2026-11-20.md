# Lighthouse-Ausgangswert – Climate Dashboard, 20. November 2026

Status: vollständig gemessen, vor dem Performance-Umbau. Keine Produktionsdateien geändert.

- Live-URL: https://marcelherber.github.io/climate-dashboard/index.html?tab=overview
- Veröffentlichter Commit: `3b888474129506f5aa75b75f0bbce04d0ebafc88` (Pages-Deployment 44691427610 erfolgreich).
- Messworkflow: https://github.com/MarcelHerber/climate-dashboard/actions/runs/44692937072 (beide Jobs erfolgreich).
- Lighthouse 12.6.0; Chromium: Google Chrome 157.0.8103.78 (Mobil) / 157.0.8103.50 (Desktop); GitHub Actions ubuntu-24.04.
- Identischer SHA-256 der abgefragten veröffentlichten HTML-Datei in beiden Jobs: `484d7d63f09a869be21f65d4ab55ec8858d13de773ae18708cd6434fe8340fcc`.
- Drei unabhängige Kaltstarts pro Gerät, Lighthouse-Standardpreset Mobil (412×823, 1,75 DPR, 4× CPU, 150 ms RTT, 1638,4 kbit/s) und Desktop-Preset (1350×940, 1 DPR, 1× CPU, 40 ms RTT, 10240 kbit/s), simulierte Drosselung; nur Performance-Kategorie; keine Laufzeitfehler.
- Vollständige Lighthouse-JSON-/HTML-Berichte, Konfiguration, Response-Header, Original-HTML und Einzelmessungen: [Mobil](https://github.com/MarcelHerber/climate-dashboard/actions/runs/44692937072/artifacts/14608679964), [Desktop](https://github.com/MarcelHerber/climate-dashboard/actions/runs/44692937072/artifacts/14609412419) (90 Tage Aufbewahrung).

## Messwerte

Alle Zeiten in Millisekunden, übertragene Bytes laut Lighthouse. Median pro Kennzahl, nicht etwa Werte eines ausgewählten Laufs.

| Gerät/Lauf | Score | FCP | LCP | Speed Index | TBT | CLS | TTI | Bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Mobil 1 | 53 | 4711.090 | 4711.090 | 5289.307 | 711.939 | 0 | 16023.819 | 3187664 |
| Mobil 2 | 53 | 4255.572 | 4557.396 | 4255.572 | 863.588 | 0.001081 | 15230.486 | 3138084 |
| Mobil 3 | 57 | 4693.727 | 5147.449 | 5167.368 | 374 | 0.093 | 15511.906 | 3138049 |
| **Mobil Median** | **53** | **4693.727** | **4711.090** | **5167.368** | **711.939** | **0.001081** | **15511.906** | **3138084** |
| Desktop 1 | 92 | 1221.743 | 1241.760 | 1221.743 | 109 | 0.005 | 1608.061 | 3138090 |
| Desktop 2 | 96 | 974.049 | 1244.656 | 974.049 | 55.272 | 0.005 | 1244.656 | 3138197 |
| Desktop 3 | 97 | 943.429 | 943.429 | 1030.006 | 83.5 | 0.005 | 2595.887 | 3138531 |
| **Desktop Median** | **96** | **974.049** | **1241.760** | **1030.006** | **83.5** | **0.004960** | **1608.061** | **3138197** |

## Diagnose (Beispiel Mobil-Lauf 2)

- Renderblocking-Opportunity: geschätzt 2202 ms; ungenutztes JavaScript: geschätzt 331 KiB. Dies sind Lighthouse-Schätzungen, keine schon erzielten Einsparungen.
- `index.html`: 1088734 dekodierte Bytes / 245405 transferierte Bytes; im Dokument steckt ungefähr 800600 Zeichen Haupt-JavaScript. Auslagerung allein reduziert den gesamten Code nicht.
- jsPDF: 110468 transferierte Bytes, html2canvas: 38013; beide sind beim Einstieg für Sichtdarstellung unnötige Bibliotheken, vor Export jedoch zwingend verfügbar zu machen.
- Chart.js: 61015 transferierte Bytes, geschätzt 1363 ms renderblockierend; Plugins müssen vor dem abhängigen Hauptscript bereitstehen.
- Größte zusätzliche Payload: `europe_stations/index.json` (1044106 Bytes) sowie drei HYRAS-Rangkarten (zusammen 944822 Bytes). Diese unaufgefordert geladenen Modul-Daten sind ein separater späterer Optimierungsschritt; nicht mit dem Script-Umbau vermischen.

## Vergleichsbedingungen für den Umbau

Vorher und Nachher jeweils auf demselben isolierten Testserver mit derselben veröffentlichten HTML-/Datenbasis, denselben CDN-Abhängigkeiten, derselben Chrome- und Lighthouse-Version und denselben Drosselungseinstellungen messen. Mindestens drei Kaltstarts; zusätzlich Prüfung von Navigation, Karten, Diagrammen, Dark Mode, SST und repräsentativen PNG/PDF-Exporten. Nicht eine lokale Vorschau mit dem extern gehosteten Live-Score als A/B vergleichen. `main` bleibt bis zur expliziten Freigabe unverändert.
