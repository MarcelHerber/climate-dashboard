# Automatische Aktualisierung des Climate Dashboard

## Was wird aktualisiert?

- `data.json`: monatliche Deutschland-Gebietsmittel des DWD für Temperatur, Niederschlag und Sonnenscheindauer.
- `daily_tmax_1881_2026.json`: höchstes gemeldetes Tagesmaximum (`TXK`) aller verfügbaren DWD-KL-Stationen pro Datum.
- `update_status.json`: Datenstand, Prüfwerte und Zeitpunkt des letzten erfolgreichen Laufs.

Das tägliche Skript überschreibt außerdem jüngere, bereits vorhandene Tage, falls der DWD Werte nachträglich korrigiert. Ein neuer Tag wird nur übernommen, wenn genügend Stationen gemeldet haben. Die vorhandenen Klimamittel 1991–2020 bleiben unverändert.

## Installation

1. Den Inhalt dieses Pakets in die oberste Ebene des GitHub-Repositories kopieren.
2. Alle Dateien committen und auf `main` pushen.
3. In GitHub öffnen: **Settings → Pages → Build and deployment → Source**.
4. Als Quelle **GitHub Actions** auswählen.
5. Unter **Actions** den Workflow **DWD-Daten aktualisieren und GitHub Pages veröffentlichen** einmal manuell starten.

Danach läuft der Workflow täglich um **10:17 Uhr Europe/Berlin**. Er kann jederzeit zusätzlich über **Run workflow** gestartet werden.

## Sicherheit

Die bestehenden JSON-Dateien werden nur ersetzt, wenn Downloads, Datenstruktur und Plausibilitätsprüfungen erfolgreich sind. Bei einer unvollständigen DWD-Lieferung bricht der Workflow ab und die veröffentlichte Website behält den letzten funktionierenden Datenstand.

## Lokaler Test

```bash
python -m pip install -r requirements.txt
python scripts/update_dashboard.py
```

Nur prüfen, ohne Daten herunterzuladen:

```bash
python scripts/update_dashboard.py --validate-only
```

## Datenquellen

- DWD CDC: monatliche Gebietsmittel Deutschland
- DWD CDC: tägliche Klimadaten deutscher Stationen, Verzeichnis `daily/kl/recent`
