# Meere / SST – Betrieb

Der Bereich **Meere / SST** verwendet NASA/JPL MUR SST v4.1 für die tägliche SST und die NOAA-OISST-Tagesklimatologie 1991–2020 als Referenz.

## Datenquellen

- NASA/JPL MUR SST v4.1, Earthdata Collection `C1996881146-POCLOUD`
- NOAA PSL OISST High Resolution, `sst.day.mean.ltm.1991-2020.nc`
- NOAA-Klimatologie wird workflowseitig nur für den gemeinsamen Kartenausschnitt gecacht.

## GitHub Secret

Erforderlich ist genau dieses Actions Secret:

```text
EARTHDATA_TOKEN
```

Der Wert darf niemals in Dateien, Workflow-Logs oder Artefakte geschrieben werden.

## Veröffentlichung

- Archiv-Branch: `sst-archive`
- Tägliches Update: `.github/workflows/update-sst-europe.yml`
- Historischer Backfill: `.github/workflows/backfill-sst-europe.yml`
- Der Backfill akzeptiert pro Lauf genau einen Monat im Format `YYYY-MM`.
- Beide Workflows benutzen die Concurrency-Gruppe `sst-archive-writer` und können das Archiv daher nicht gleichzeitig schreiben.
- `sst-archive` wird als einzelner Snapshot-Commit force-with-lease veröffentlicht, damit Binärhistorie nicht dauerhaft anwächst.

## Pflicht vor dem Backfill ab 2020

Als erster echter Datenlauf muss der Zeitraum

```text
2026-09-01 bis 2026-09-07
```

erzeugt werden. Erwartet werden 70 valide WebP-Dateien (7 Tage × 5 Regionen × 2 Ansichten), ein gültiges `manifest.json` und `storage_report.json`.

**Erst nach Prüfung dieses Speicherreports** darf der historische Backfill ab `2020-01` monatweise gestartet werden.

## Feste Stufe-1-Konfiguration

- SST absolut: −2 bis +34 °C
- SST-Anomalie: −6 bis +6 °C
- Meereis-Maskierung: `sea_ice_fraction >= 0.15`
- Karten: 1600 × 1050 px, WebP
- Regionen: Europa, Mittelmeer, Nordsee + Ostsee, Nordatlantik, Nordmeer / Skandinavien
