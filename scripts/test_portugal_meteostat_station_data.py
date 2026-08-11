#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import subprocess
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

COUNTRY = "PT"
START_2026 = "2026-01-01"
END_2026 = date.today().isoformat()


def run(cmd: list[str], *, check=True) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def station_inventory() -> tuple[list[dict], list[str]]:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "stations.csv"
        cp = run([
            "meteo", "station",
            "--country", COUNTRY,
            "--format", "csv",
            "--all",
            "--output", str(out),
        ])

        if cp.stdout.strip():
            print(cp.stdout)

        text = out.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        fields = reader.fieldnames or []

    return rows, fields


def station_id(row: dict, fields: list[str]) -> str | None:
    candidates = [
        "id", "station", "station_id", "meteostat_id",
        "index", "",
    ]
    lowmap = {str(k).lower(): k for k in fields}

    for c in candidates:
        key = lowmap.get(c.lower())
        if key is not None:
            value = str(row.get(key, "")).strip()
            if value:
                return value

    # Last resort: first non-empty column which looks like an ID.
    for key in fields:
        value = str(row.get(key, "")).strip()
        if value and len(value) <= 12 and " " not in value:
            return value
    return None


def daily_period(row: dict, fields: list[str]):
    lowmap = {str(k).lower(): k for k in fields}
    start_key = next(
        (lowmap[k] for k in ("daily_start", "dailystart") if k in lowmap),
        None,
    )
    end_key = next(
        (lowmap[k] for k in ("daily_end", "dailyend") if k in lowmap),
        None,
    )
    return (
        str(row.get(start_key, "")).strip() if start_key else "",
        str(row.get(end_key, "")).strip() if end_key else "",
    )


def station_name(row: dict, fields: list[str]) -> str:
    lowmap = {str(k).lower(): k for k in fields}
    for c in ("name", "station_name"):
        if c in lowmap:
            return str(row.get(lowmap[c], "")).strip()
    return ""


def fetch_daily_2026(sid: str):
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"{sid}.csv"
        cp = run([
            "meteo", "daily", sid,
            "--start", START_2026,
            "--end", END_2026,
            "--parameters", "tmin,tmax",
            "--with-sources",
            "--no-models",
            "--format", "csv",
            "--all",
            "--output", str(out),
        ], check=False)

        if cp.returncode != 0:
            return {
                "ok": False,
                "error": cp.stdout.strip()[-1200:],
                "rows": 0,
                "tmin": 0,
                "tmax": 0,
                "tmin_sources": Counter(),
                "tmax_sources": Counter(),
                "first": None,
                "last": None,
                "header": [],
                "samples": [],
            }

        if not out.exists() or out.stat().st_size == 0:
            return {
                "ok": True,
                "error": "",
                "rows": 0,
                "tmin": 0,
                "tmax": 0,
                "tmin_sources": Counter(),
                "tmax_sources": Counter(),
                "first": None,
                "last": None,
                "header": [],
                "samples": [],
            }

        text = out.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        fields = reader.fieldnames or []

    lowmap = {str(k).lower(): k for k in fields}

    def key(*names):
        for n in names:
            if n.lower() in lowmap:
                return lowmap[n.lower()]
        return None

    time_key = key("time", "date")
    tmin_key = key("tmin")
    tmax_key = key("tmax")
    tmin_src_key = key("tmin_source")
    tmax_src_key = key("tmax_source")
    generic_src_key = key("source")

    valid_tmin = 0
    valid_tmax = 0
    tmin_sources = Counter()
    tmax_sources = Counter()
    dates = []
    samples = []

    for row in rows:
        d = str(row.get(time_key, "")).strip() if time_key else ""
        if d:
            dates.append(d)

        tmin_val = str(row.get(tmin_key, "")).strip() if tmin_key else ""
        tmax_val = str(row.get(tmax_key, "")).strip() if tmax_key else ""

        if tmin_val not in ("", "nan", "NaN", "None"):
            try:
                float(tmin_val)
                valid_tmin += 1
                src = ""
                if tmin_src_key:
                    src = str(row.get(tmin_src_key, "")).strip()
                elif generic_src_key:
                    src = str(row.get(generic_src_key, "")).strip()
                if src:
                    tmin_sources[src] += 1
            except ValueError:
                pass

        if tmax_val not in ("", "nan", "NaN", "None"):
            try:
                float(tmax_val)
                valid_tmax += 1
                src = ""
                if tmax_src_key:
                    src = str(row.get(tmax_src_key, "")).strip()
                elif generic_src_key:
                    src = str(row.get(generic_src_key, "")).strip()
                if src:
                    tmax_sources[src] += 1
            except ValueError:
                pass

        if len(samples) < 5 and (tmin_val or tmax_val):
            samples.append({
                "date": d,
                "tmin": tmin_val,
                "tmax": tmax_val,
                "tmin_source": str(row.get(tmin_src_key, "")).strip() if tmin_src_key else "",
                "tmax_source": str(row.get(tmax_src_key, "")).strip() if tmax_src_key else "",
                "source": str(row.get(generic_src_key, "")).strip() if generic_src_key else "",
            })

    return {
        "ok": True,
        "error": "",
        "rows": len(rows),
        "tmin": valid_tmin,
        "tmax": valid_tmax,
        "tmin_sources": tmin_sources,
        "tmax_sources": tmax_sources,
        "first": min(dates) if dates else None,
        "last": max(dates) if dates else None,
        "header": fields,
        "samples": samples,
    }


def main():
    print("============================================================")
    print("PORTUGAL · METEOSTAT DAILY TMIN/TMAX PROBE")
    print("============================================================")
    print("Nur Probe. KEIN Cache. KEINE Europa-Integration.")
    print()
    print("Wichtig:")
    print("- direkte Stationsabfrage, keine Punkt-Interpolation")
    print("- --no-models: Modellwerte werden ausgeschlossen")
    print("- --with-sources: Datenquellen werden mit ausgegeben")
    print()

    version = run(["meteo", "--version"], check=False)
    print("Meteostat CLI:", version.stdout.strip())

    rows, fields = station_inventory()
    print("\n=== PT-STATIONSINVENTAR ===")
    print(f"CSV-Spalten: {fields}")
    print(f"Meteostat-Stationen mit country=PT: {len(rows):,}")

    parsed = []
    for row in rows:
        sid = station_id(row, fields)
        if not sid:
            continue
        ds, de = daily_period(row, fields)
        parsed.append({
            "id": sid,
            "name": station_name(row, fields),
            "daily_start": ds,
            "daily_end": de,
            "raw": row,
        })

    print(f"Stationen mit erkannter Meteostat-ID: {len(parsed):,}")
    print("\nErste 30 Stationen:")
    for st in parsed[:30]:
        print(
            f"{st['id']} | {st['name']} | "
            f"daily={st['daily_start']} .. {st['daily_end']}"
        )

    if fields:
        print("\nErstes vollständiges Metadatenobjekt:")
        if rows:
            print(json.dumps(rows[0], ensure_ascii=False, indent=2))

    # Prioritize stations whose inventory says they reach 2026/current period.
    def reaches_2026(st):
        de = st["daily_end"]
        return de.startswith("2026") or de >= "2026-01-01"

    candidates = [st for st in parsed if reaches_2026(st)]
    if not candidates:
        candidates = parsed

    print("\n=== 2026 DAILY TMIN/TMAX OHNE MODELLE ===")
    print(f"Zu prüfende Stationen: {len(candidates):,}")

    successful = []
    failed = []
    all_sources = Counter()

    for i, st in enumerate(candidates, 1):
        sid = st["id"]
        info = fetch_daily_2026(sid)

        if not info["ok"]:
            failed.append((sid, info["error"]))
            print(
                f"[{i}/{len(candidates)}] {sid} | {st['name']} | "
                f"FEHLER: {info['error'][:300]}"
            )
            continue

        if info["tmin"] or info["tmax"]:
            successful.append((st, info))

        for src, n in info["tmin_sources"].items():
            all_sources[f"TMIN:{src}"] += n
        for src, n in info["tmax_sources"].items():
            all_sources[f"TMAX:{src}"] += n

        print(
            f"[{i}/{len(candidates)}] {sid} | {st['name']} | "
            f"{info['first']} .. {info['last']} | "
            f"TMIN={info['tmin']} | TMAX={info['tmax']} | "
            f"TMIN_sources={dict(info['tmin_sources'])} | "
            f"TMAX_sources={dict(info['tmax_sources'])}"
        )

        if info["header"]:
            print(f"  HEADER: {info['header']}")
        for sample in info["samples"][:2]:
            print("  SAMPLE:", json.dumps(sample, ensure_ascii=False))

    print("\n============================================================")
    print("ZUSAMMENFASSUNG")
    print("============================================================")
    print(f"Meteostat PT-Stationen gesamt: {len(parsed):,}")
    print(f"2026-Kandidaten laut Inventar: {len(candidates):,}")
    print(
        "2026 mit mindestens einem echten TMIN/TMAX-Wert nach --no-models: "
        f"{len(successful):,}"
    )
    print(f"CLI-Fehler: {len(failed):,}")

    both = [
        (st, info)
        for st, info in successful
        if info["tmin"] > 0 and info["tmax"] > 0
    ]
    print(f"2026 mit TMIN UND TMAX: {len(both):,}")

    print("\n=== STATIONEN MIT TMIN + TMAX 2026 ===")
    for st, info in both:
        print(
            f"{st['id']} | {st['name']} | "
            f"TMIN={info['tmin']} | TMAX={info['tmax']} | "
            f"bis {info['last']} | "
            f"TMIN_sources={dict(info['tmin_sources'])} | "
            f"TMAX_sources={dict(info['tmax_sources'])}"
        )

    print("\n=== QUELLENHÄUFIGKEITEN ===")
    for src, n in all_sources.most_common():
        print(f"{src} -> {n:,}")

    if failed:
        print("\n=== FEHLERBEISPIELE ===")
        for sid, err in failed[:10]:
            print(f"{sid}: {err}")

    print("\nBitte den vollständigen Log schicken, insbesondere:")
    print("1) Meteostat-Stationen mit country=PT")
    print("2) CSV-Spalten / erstes Metadatenobjekt")
    print("3) 2026 mit TMIN UND TMAX")
    print("4) STATIONEN MIT TMIN + TMAX 2026")
    print("5) QUELLENHÄUFIGKEITEN")
    print()
    print(
        "Danach vergleichen wir Meteostat gegen die 18 GHCN-Stationen und "
        "gegen die IPMA-Stationsliste. Erst dann entscheiden wir die Portugal-Quelle."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
