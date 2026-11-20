# Lighthouse-Vergleich — 20. November 2026 (Runner-UTC)

**Experiment, nicht freigegeben.** Nur Branch `perf/dashboard-loading-20261120`.
Gemessener Commit: `334a44da785ef90d7512e7d545bfa2b53a259f11`.
Die ursprüngliche Live-Referenz bleibt unverändert in
[lighthouse-baseline-2026-11-20.md](lighthouse-baseline-2026-11-20.md).

[Erfolgreicher Vergleichslauf](https://github.com/MarcelHerber/climate-dashboard/actions/runs/44709139707)
· [Desktop-Artefakt](https://github.com/MarcelHerber/climate-dashboard/actions/runs/44709139707/artifacts/14615929700)
· [Mobil-Artefakt](https://github.com/MarcelHerber/climate-dashboard/actions/runs/44709139707/artifacts/14616238526).

## Methode

Lighthouse 12.6.0, Ubuntu 24.04, Chrome 157.0.8103.78 Desktop bzw.
157.0.8103.50 Mobil; exakt dieselbe jeweilige Browserinstallation für alle
vier Stufen. Die archivierte Produktions-HTML wurde per SHA-256 verifiziert.
Die extern ausgelagerte Hauptdatei entspricht in Stufe 1 exakt den 802.960
Bytes des Inline-Skripts (SHA-256
`f51a14c7a96b2c69c49f57d3e0f1a70dcf5bdce0ea1bca0c085ac7ef60f6aab8`).
Die Daten und Skriptantworten pro Gerät wurden gemeinsam vorgewärmt und
anschließend vom Snapshot-Proxy wiedergegeben; die gewerteten Browserstarts
sind dennoch echte Kaltstarts mit jeweils neuem Browserprofil. Keine späten
Datensnapshot-Misses. Konfiguration, Einzelberichte, übertragene Daten und
Hash-Manifest sind in den Artefakten archiviert. Die ursprünglichen Live-Scores
werden nicht direkt gegen diese isolierte Messung verglichen.

## Mediane

Zeiten in ms; Bytes nach Lighthouse. Stufen: 0 Referenz, 1 Auslagerung,
2 zusätzlich defer, 3 zusätzlich Lazy-Export.

| Gerät/Stufe | Score | FCP | LCP | Speed Index | TBT | CLS | TTI | Bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Desktop 0 | 96 | 964 | 998 | 1050 | 102 | .00496 | 2655 | 3122057 |
| Desktop 1 | 94 | 1068 | 1124 | 1134 | 131 | .00496 | 2756 | 3122445 |
| Desktop 2 | 97 | 647 | 884 | 864 | 122 | .00496 | 2757 | 3127754 |
| Desktop 3 | 97 | 638 | 764 | 859 | 134 | .00496 | 2714 | 2980834 |
| Mobil 0 | 47 | 4548 | 4720 | 5515 | 1062 | 0 | 16124 | 3122020 |
| Mobil 1 | 51 | 3889 | 3889 | 5655 | 1498 | 0 | 16415 | 3122408 |
| Mobil 2 | 63 | 2056 | 2730 | 5715 | 1921 | 0 | 16103 | 3127717 |
| Mobil 3 | 63 | 2029 | 2712 | 5539 | 1827 | 0 | 15268 | 2980798 |

## Einzelmessungen

| Gerät/Stufe/Lauf | Score | FCP | LCP | Speed Index | TBT | CLS | TTI | Bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Desktop 0/1 | 96 | 964 | 964 | 1058 | 115 | .00496 | 2655 | 3122057 |
| Desktop 0/2 | 96 | 955 | 1001 | 1050 | 101 | .00496 | 1181 | 3122057 |
| Desktop 0/3 | 96 | 998 | 998 | 998 | 92 | .00496 | 2702 | 3122057 |
| Desktop 1/1 | 93 | 1084 | 1124 | 1084 | 134 | .00496 | 2756 | 3122445 |
| Desktop 1/2 | 94 | 1068 | 1108 | 1178 | 131 | .00496 | 2787 | 3122445 |
| Desktop 1/3 | 95 | 1054 | 1154 | 1134 | 56 | .00496 | 1332 | 3122445 |
| Desktop 2/1 | 97 | 638 | 884 | 870 | 122 | .00496 | 2757 | 3127754 |
| Desktop 2/2 | 97 | 652 | 913 | 856 | 125 | .00496 | 2799 | 3127754 |
| Desktop 2/3 | 97 | 647 | 830 | 864 | 120 | .00496 | 2757 | 3127754 |
| Desktop 3/1 | 97 | 624 | 761 | 860 | 134 | .00496 | 2693 | 2980834 |
| Desktop 3/2 | 97 | 667 | 764 | 858 | 137 | .00496 | 2768 | 2980834 |
| Desktop 3/3 | 97 | 638 | 769 | 859 | 128 | .00496 | 2714 | 2980834 |
| Mobil 0/1 | 49 | 4531 | 4694 | 5515 | 973 | 0 | 15945 | 3122020 |
| Mobil 0/2 | 47 | 4618 | 4785 | 5693 | 1062 | 0 | 16124 | 3122020 |
| Mobil 0/3 | 47 | 4548 | 4720 | 5268 | 1173 | 0 | 16149 | 3122020 |
| Mobil 1/1 | 51 | 3889 | 3889 | 5245 | 1545 | 0 | 16415 | 3122408 |
| Mobil 1/2 | 44 | 4630 | 4782 | 5747 | 1453 | 0 | 16424 | 3122408 |
| Mobil 1/3 | 54 | 3473 | 3473 | 5655 | 1498 | 0 | 16402 | 3122408 |
| Mobil 2/1 | 62 | 2066 | 2757 | 5773 | 1939 | .00292 | 16103 | 3127717 |
| Mobil 2/2 | 63 | 2052 | 2730 | 5231 | 1921 | 0 | 16160 | 3127717 |
| Mobil 2/3 | 63 | 2056 | 2724 | 5715 | 1735 | 0 | 15951 | 3127717 |
| Mobil 3/1 | 63 | 1966 | 2712 | 5408 | 1827 | 0 | 15010 | 2980798 |
| Mobil 3/2 | 62 | 2156 | 2695 | 5617 | 1736 | .00292 | 15366 | 2980798 |
| Mobil 3/3 | 63 | 2029 | 2725 | 5539 | 1835 | 0 | 15268 | 2980798 |

## Befunde und Freigabekriterien

- Übertragene Bytes: −141.223 Desktop, −141.222 Mobil, je etwa −4,5 %.
- Auslagerung allein spart keine Bytes und ist nicht ausreichend.
- Defer ermöglicht deutlich früheren Bildaufbau. Das zusätzliche Lazy Loading
  spart gegenüber der defer-Stufe rund 147 kB und reduziert die mobile TBT
  etwas, aber nicht bis auf den alten Wert.
- Mobile TBT 1.062 → 1.827 ms (+72 %), in allen drei Kaltstarts schlechter.
  Gesamte Script-Evaluation dagegen 2.980 → 2.907 ms im Median. Das frühere
  FCP verschiebt weitere lange Initialisierungsaufgaben in das messbare
  TBT-Fenster. Kein Beleg für erhöhte gesamte JavaScript-Rechenarbeit.
  Nächster Schritt vor einer Freigabe: Chrome-Trace der langen Aufgaben,
  insbesondere Dashboard-Initialisierung, SST-Graph und Hintergrunddaten;
  keine ungeprüfte Änderung der wissenschaftlichen Datenlogik.
- 48 gezielte Regressionen bestanden (11 Python, 37 Node); zusätzlicher
  Loader-Funktionstest erfolgreich. Vollständige Python-Discovery in identischem
  Sparse-Checkout: 541 Referenz- vs. 544 Kandidatentests, identisch zwei
  bestehende Fehlschläge und 78 Fehler (u. a. fehlende Daten/Abhängigkeiten).
  Keine zusätzlichen fehlgeschlagenen Tests durch den Umbau.
- Browser: 320, 360, 390 und 1440 px, Licht/Dunkel, Öffnen/Schließen,
  Kartenfarbwerte, Tabs und Footer, PNG/PDF der monatlichen Häufigkeitsverteilung
  und kein eager Laden der Bibliotheken bestanden. Keine unbehandelten
  JavaScript-Ausnahmen. Zwei bereits in der Referenz vorkommende HTTP-404-URLs
  (`era5_stratosphere.js?v=1`, `favicon.png`); bei einigen Läufen wird der
  Favicon-404 wiederholt.
- SST-Tab und Footer geprüft; die vollständige Karte war bei 390 px im
  Screenshot sichtbar, weitere Screenshots zeigten noch den Ladezustand.
  Gesonderter Browser-Nachtest für vollständige SST-Karte und SST-Exporte.
- Keine Veröffentlichung oder Merge. Die ausdrückliche Nutzereinwilligung
  ist erforderlich, auch nach weiteren Optimierungen.

Datumsnotiz: UTC-Zeitstempel 20.11.2026 aus GitHub Actions; der Nutzer nannte
den 16.11.2026 als sein aktuelles Datum. Die Messdaten wurden nicht umdatiert.
