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
    """Parse DWD KL TXK/TNK plus TMK and 1991-2020 calendar-day normals."""
    state = _CORE_PARSE_DWD_PRODUCT_BYTES(data, cutoff_year=cutoff_year, exact_year=exact_year)
    historical = exact_year is None
    state["TMEAN"] = {"clim_1991_2020": {}} if historical else {}

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

                    if historical and dwd_daily_map.REFERENCE_START <= year <= dwd_daily_map.REFERENCE_END:
                        for element, key in (("TMAX", tx_key), ("TMIN", tn_key)):
                            if not key:
                                continue
                            value = core.dwd_float_to_tenths(row.get(key, ""))
                            if value is not None:
                                dwd_daily_map.add_climatology_value(state[element], mmdd, value)

                    if tm_key:
                        value = core.dwd_float_to_tenths(row.get(tm_key, ""))
                        if value is None:
                            continue
                        if historical:
                            if dwd_daily_map.REFERENCE_START <= year <= dwd_daily_map.REFERENCE_END:
                                dwd_daily_map.add_climatology_value(state["TMEAN"], mmdd, value)
                        else:
                            state["TMEAN"][mmdd] = (value, date_int)

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

    print(
        f"DWD Tageskarte OK: {payload.get('station_count', 0)} Stationen | "
        f"bis {data_through} | Tmean {len(tmean)} | Tmean-Anomalie {len(tmean_anom)}"
    )
    return payload


def self_test() -> None:
    raw = (
        "MESS_DATUM;TXK;TNK;TMK\n"
        "19910828;25.0;12.0;18.5\n"
        "20260828;31.0;16.0;23.0\n"
    ).encode("latin-1")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("produkt_klima_tag_19910101_20260828_00001.txt", raw)
    data = buf.getvalue()

    hist = parse_dwd_daily_map_product(data, cutoff_year=2025)
    assert hist["TMAX"]["clim_1991_2020"]["08-28"] == [250, 1]
    assert hist["TMIN"]["clim_1991_2020"]["08-28"] == [120, 1]
    assert hist["TMEAN"]["clim_1991_2020"]["08-28"] == [185, 1]

    cur = parse_dwd_daily_map_product(data, exact_year=2026)
    assert cur["TMAX"]["08-28"] == (310, 20260828)
    assert cur["TMIN"]["08-28"] == (160, 20260828)
    assert cur["TMEAN"]["08-28"] == (230, 20260828)
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
