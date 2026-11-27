#!/usr/bin/env python3
"""Europa-Anomalie- und Rekordmonitor: Baselines aufbauen, aktuelles Jahr laden, statische Dateien schreiben.

Beispiele
  python update_europe_anomaly_map.py --year 2026                       # Stufe A + B1 + B2.1
  python update_europe_anomaly_map.py --sources A                       # nur DE, FR, CZ, GHCN-Rest
  python update_europe_anomaly_map.py --sources dwd_de,geosphere_at     # einzelne Quellen
  python update_europe_anomaly_map.py --baseline-only --sources B2.1    # nur historische Baselines aufbauen
  python update_europe_anomaly_map.py --self-test

Die bestehenden Dateien (europe_stations/*.json, dwd_daily_map/) werden weder gelesen noch verändert.
Ausgabe standardmäßig nach europe_anomaly, Cache nach .cache/europe-anomaly.
Quellen, die ausfallen oder noch im Aufbau sind, erscheinen im Index mit Status und Meldung. Ihre Stationen
werden nicht durch eine andere Quelle ersetzt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import europe_anomaly_map as emap
import europe_anomaly_sources as src
import europe_climate_engine as E


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    p.add_argument("--output", default="europe_anomaly")
    p.add_argument("--cache-dir", default=".cache/europe-anomaly")
    p.add_argument("--sources", default="", help="Stufen (A,B1,B2.1,…) oder Quellenschlüssel, kommagetrennt; Standard: A,B1,B2.1")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--max-runtime-minutes", type=float, default=150.0, help="Laufzeitbudget je fortsetzbarer Baseline")
    p.add_argument("--force-baseline", default="", help="Quellenschlüssel (kommagetrennt) oder 'all'")
    p.add_argument("--chmi-cache-dir", default="", help="vorhandenen CHMI-Cache (nur lesend) wiederverwenden")
    p.add_argument("--baseline-only", action="store_true", help="nur Baselines/Engine-Caches aufbauen, nichts exportieren")
    p.add_argument("--strict", action="store_true", help="Exit-Code 1, wenn eine ausgewählte Quelle nicht ok ist")
    p.add_argument("--list-sources", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.self_test:
        import test_europe_anomaly
        test_europe_anomaly.run_all()
        return 0
    if args.list_sources:
        for s in src.SPECS:
            print(f"{s.stage:5} {s.key:18} {','.join(s.countries):4} {s.label}{'' if s.run else '  (noch nicht angebunden)'}")
        return 0

    selection = [t for t in args.sources.split(",") if t.strip()] or None
    specs = src.select_specs(selection)
    force = frozenset(t.strip() for t in args.force_baseline.split(",") if t.strip())
    ctx = src.Ctx(
        year=args.year, cache_dir=Path(args.cache_dir), workers=max(1, args.workers), force=force,
        max_runtime_minutes=args.max_runtime_minutes, chmi_cache_dir=Path(args.chmi_cache_dir) if args.chmi_cache_dir else None,
        baseline_only=args.baseline_only,
    )
    ctx.cache_dir.mkdir(parents=True, exist_ok=True)
    print("=== EUROPA-ANOMALIE- UND REKORDMONITOR ===")
    print("Auswahl: " + ", ".join(f"{s.key} ({s.stage})" for s in specs))

    results = src.run_sources(ctx, specs)
    chosen = {s.key for s in specs}
    chosen_results = [r for r in results if r.key in chosen]
    ok = [r for r in chosen_results if r.status == "ok"]
    print("\n=== QUELLENSTATUS ===")
    for r in results:
        print(f"{r.status.upper():9} {r.stage:5} {r.label:28} {r.message}")
    if args.baseline_only:
        return 1 if (args.strict and len(ok) != len(chosen_results)) else 0
    if not ok:
        print("Keine ausgewählte Quelle lieferte Daten. Es wird nichts exportiert.", file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    index = emap.write_map(output_dir, results, args.year)
    emap.validate_output(output_dir)
    if args.strict and len(ok) != len(chosen_results):
        print("STRICT: mindestens eine ausgewählte Quelle ist nicht ok.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
