#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import dwd_daily_map
import update_europe_station_records as core

_CORE_PARSE_DWD_PRODUCT_BYTES = core.parse_dwd_product_bytes


def parse_dwd_daily_map_product(data: bytes, cutoff_year=None, exact_year=None) -> dict:
    """Parse DWD KL TXK/TNK/TMK, normals and annual climate-day records."""
    state = _CORE_PARSE_DWD_PRODUCT_BYTES(data, cutoff_year=cutoff_year, exact_year=exact_year)
    historical = exact_year is None
    # Der Core liefert je Kalendertag Maximum von TMAX ("cal") und Minimum von TMIN ("cal"). Hier kommen
    # die beiden fehlenden Richtungen (TMAX-Minimum "cal_lo", TMIN-Maximum "cal_hi"), die Messjahre je
    # Kalendertag ("n") und die Klimamittel aller Referenzperioden ("clim") hinzu.
    state["TMEAN"] = {}
    if historical:
        state["TMAX"]["cal_lo"] = {}
        state["TMIN"]["cal_hi"] = {}

    annual = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [n for n in zf.namelist() if re.search(r"produkt_klima_tag_.*\.txt$", n, re.I)]
        if not members:
            members = [n for n in zf.namelist() if n.lower().endswith(".txt") and "produkt" in n.lower()]

        for member in members:
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="")
                reader = csv.DictReader(text, delimiter=";")
                if not reader.fieldnames:
                    continue

                fmap = {str(k).strip(): k for k in reader.fieldnames if k is not None}
                date_key = fmap.get("MESS_DATUM")
                tx_key = fmap.get("TXK")
                tn_key = fmap.get("TNK")
                tm_key = fmap.get("TMK")
                if not date_key:
                    continue

                for row in reader:
                    datestr = str(row.get(date_key, "")).strip()
                    if not re.fullmatch(r"\d{8}", datestr):
                        continue
                    year = int(datestr[:4])
                    if cutoff_year is not None and year > cutoff_year:
                        continue
                    if exact_year is not None and year != exact_year:
                        continue

                    date_int = int(datestr)
                    mmdd = f"{datestr[4:6]}-{datestr[6:8]}"
                    if mmdd not in dwd_daily_map._CYCLE_POS:
                        continue
                    tm = core.dwd_float_to_tenths(row.get(tm_key, "")) if tm_key else None
                    if not historical:
                        if tm is not None:
                            state["TMEAN"][mmdd] = (tm, date_int)
                        continue
                    tx = core.dwd_float_to_tenths(row.get(tx_key, "")) if tx_key else None
                    tn = core.dwd_float_to_tenths(row.get(tn_key, "")) if tn_key else None

                    if historical:
                        yr = annual.setdefault(year, {"TMAX_valid":0,"TMIN_valid":0,**{k:0 for k in dwd_daily_map.CLIMATE_DAY_DEFS}})
                        if tx is not None:
                            yr["TMAX_valid"] += 1
                        if tn is not None:
                            yr["TMIN_valid"] += 1
                        for key, definition in dwd_daily_map.CLIMATE_DAY_DEFS.items():
                            value = tx if definition["element"] == "TMAX" else tn
                            if dwd_daily_map.climate_day_hit(definition, value):
                                yr[key] += 1

                        if tx is not None:
                            dwd_daily_map.add_climatology_value(state["TMAX"], mmdd, tx, year)
                            dwd_daily_map.add_observation_count(state["TMAX"], mmdd)
                            dwd_daily_map.update_extreme(state["TMAX"]["cal_lo"], mmdd, tx, date_int, False)
                        if tn is not None:
                            dwd_daily_map.add_climatology_value(state["TMIN"], mmdd, tn, year)
                            dwd_daily_map.add_observation_count(state["TMIN"], mmdd)
                            dwd_daily_map.update_extreme(state["TMIN"]["cal_hi"], mmdd, tn, date_int, True)
                        if tm is not None:
                            dwd_daily_map.add_climatology_value(state["TMEAN"], mmdd, tm, year)

    if historical:
        climate_days = {}
        for key, definition in dwd_daily_map.CLIMATE_DAY_DEFS.items():
            valid_key = definition["element"] + "_valid"
            eligible = [(year, values[key]) for year, values in annual.items()
                        if int(values.get(valid_key, 0)) >= dwd_daily_map.MIN_ANNUAL_VALID_DAYS]
            if not eligible:
                continue
            record = max(count for _, count in eligible)
            years = sorted(year for year, count in eligible if count == record)
            climate_days[key] = {"record": int(record), "years": years, "eligible_years": len(eligible)}
        state["CLIMATE_DAYS"] = climate_days

    return state


# Reuse the proven DWD download/cache machinery, but with the daily-map parser.
core.parse_dwd_product_bytes = parse_dwd_daily_map_product


def validate_output(output_dir: Path) -> dict:
    index_path = output_dir / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"Fehlender DWD-Tageskartenindex: {index_path}")

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if payload.get("ready") is not True:
        raise RuntimeError("DWD-Tageskarte meldet ready != true.")
    if "TMK" not in str(payload.get("source", "")):
        raise RuntimeError("TMK/Tmean fehlt im DWD-Tageskartenindex.")

    data_through = str(payload.get("data_through") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_through):
        raise RuntimeError(f"Ungueltiger Datenstand: {data_through!r}")

    calendar_path = output_dir / "calendar" / f"{data_through[5:]}.json.gz"
    if not calendar_path.is_file():
        raise RuntimeError(f"Letzte Tagesdatei fehlt: {calendar_path}")

    with gzip.open(calendar_path, "rt", encoding="utf-8") as handle:
        day = json.load(handle)

    rows = day.get("rows") or []
    tmean = [r for r in rows if len(r) >= 14 and r[11] is not None]
    tmean_anom = [r for r in rows if len(r) >= 14 and r[12] is not None]
    if not tmean:
        raise RuntimeError("Keine Tmean/TMK-Werte in der letzten Tagesdatei.")
    if not tmean_anom:
        raise RuntimeError("Keine Tmean-Anomalien in der letzten Tagesdatei.")

    width = len(dwd_daily_map.ROW_FIELDS)
    if rows and any(len(r) != width for r in rows):
        raise RuntimeError(f"Tageszeilen haben nicht {width} Felder (Format passt nicht zu ROW_FIELDS).")
    n_obs = [r for r in rows if r[18] or r[19]]
    if not n_obs:
        raise RuntimeError("Keine Messjahre (Felder 18/19) in der letzten Tagesdatei.")

    ref_counts = {}
    for ref in payload.get("references") or []:
        if ref.get("default"):
            continue
        ref_path = output_dir / "calendar_ref" / ref["key"] / f"{data_through[5:]}.json.gz"
        if not ref_path.is_file():
            raise RuntimeError(f"Referenzdatei fehlt: {ref_path}")
        with gzip.open(ref_path, "rt", encoding="utf-8") as handle:
            ref_rows = json.load(handle).get("rows") or []
        if ref_rows and any(len(r) != len(dwd_daily_map.REF_ROW_FIELDS) for r in ref_rows):
            raise RuntimeError(f"Referenzzeilen {ref['key']} haben ein unerwartetes Format.")
        ref_counts[ref["key"]] = len(ref_rows)
        if not ref_rows:
            print(f"WARNUNG: Referenz {ref['key']} hat am {data_through} keine Anomalien.")

    print(
        f"DWD Tageskarte OK: {payload.get('station_count', 0)} Stationen | "
        f"bis {data_through} | Tmean {len(tmean)} | Tmean-Anomalie {len(tmean_anom)} | "
        f"Rekorde (>=30 J.) {payload.get('latest_record_count', 0)} | Referenzen {ref_counts}"
    )
    return payload


def self_test() -> None:
    raw = (
        "MESS_DATUM;TXK;TNK;TMK\n"
        "19550828;20.0;10.0;15.0\n"
        "19910828;25.0;12.0;18.5\n"
        "19920828;30.0;8.0;19.0\n"
        "19920229;5.0;-2.0;1.5\n"
        "20260828;31.0;16.0;23.0\n"
    ).encode("latin-1")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("produkt_klima_tag_19550101_20260828_00001.txt", raw)
    data = buf.getvalue()
    raw_clim = dwd_daily_map.clim_raw

    hist = parse_dwd_daily_map_product(data, cutoff_year=2025)
    # Klimamittel: 1955 nur in 1951-1980; 1991/1992 in 1991-2020 (und 1981-2010), 2026 nirgends (cutoff)
    assert raw_clim(hist["TMAX"], "1951_1980", "08-28") == (200, 1)
    assert raw_clim(hist["TMAX"], "1991_2020", "08-28") == (550, 2)
    assert raw_clim(hist["TMAX"], "1981_2010", "08-28") == (550, 2)
    assert raw_clim(hist["TMAX"], "1961_1990", "08-28") == (0, 0)
    assert raw_clim(hist["TMIN"], "1991_2020", "08-28") == (200, 2)
    assert raw_clim(hist["TMEAN"], "1991_2020", "08-28") == (375, 2)
    assert raw_clim(hist["TMAX"], "1991_2020", "02-29") == (50, 1)          # 29.02.1992 liegt in 1991-2020
    # vier Rekordrichtungen am 28.08.: TMAX 200/250/300, TMIN 100/120/80
    assert hist["TMAX"]["cal"]["08-28"] == (300, 19920828, 1)               # Core: Tmax-Maximum
    assert hist["TMAX"]["cal_lo"]["08-28"] == (200, 19550828, 1)            # neu: Tmax-Minimum
    assert hist["TMIN"]["cal"]["08-28"] == (80, 19920828, 1)                # Core: Tmin-Minimum
    assert hist["TMIN"]["cal_hi"]["08-28"] == (120, 19910828, 1)            # neu: Tmin-Maximum
    # Messjahre je Kalendertag
    assert dwd_daily_map.observed_years(hist["TMAX"], "08-28") == 3
    assert dwd_daily_map.observed_years(hist["TMIN"], "08-28") == 3
    assert dwd_daily_map.observed_years(hist["TMAX"], "02-29") == 1
    assert "CLIMATE_DAYS" in hist

    cur = parse_dwd_daily_map_product(data, exact_year=2026)
    assert cur["TMAX"]["08-28"] == (310, 20260828)
    assert cur["TMIN"]["08-28"] == (160, 20260828)
    assert cur["TMEAN"]["08-28"] == (230, 20260828)
    assert "02-29" not in cur["TMAX"]                                       # nur 2026
    print("update_dwd_daily_map.py self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--output", default="europe_stations/dwd_daily_map")
    parser.add_argument("--cache-dir", default=".cache/dwd-daily-map")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force-baseline", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    year = int(args.year)
    cutoff_year = year - 1
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("=== DWD TAGESKARTE · EIGENER UPDATE-LAUF ===")
    station_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    stations = core.parse_dwd_stations(station_text)
    if not stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")

    cache_file = cache_dir / (
        f"dwd_daily_map_baseline_through_{cutoff_year}"
        f"_core_v{core.DWD_BASELINE_FORMAT_VERSION}"
        f"_map_v{dwd_daily_map.CACHE_VERSION}.pkl.gz"
    )

    baseline = core.load_or_build_dwd_baseline(
        cache_file,
        stations,
        cutoff_year,
        args.force_baseline,
        max(1, args.workers),
    )
    current = core.parse_current_dwd_year(year, stations, workers=max(1, args.workers))
    if not current:
        raise RuntimeError(f"Keine aktuellen DWD-KL-Daten fuer {year} gefunden.")

    if output_dir.exists():
        shutil.rmtree(output_dir)

    dwd_daily_map.write_daily_map(
        output_dir,
        stations=stations,
        baseline=baseline,
        current=current,
        current_year=year,
        station_listing_text=station_text,
    )
    validate_output(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
