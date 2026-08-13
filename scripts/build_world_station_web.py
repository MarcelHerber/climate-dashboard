#!/usr/bin/env python3
"""Build compact web data for the dashboard tab ``Weltweite Stationen``.

The input is the already-built GHCN historical baseline pickle.  No NOAA
redownload is performed here.  The script writes one gzip-compressed station
pack per geographic continent plus a small manifest with the Stage-9 country
record master.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import pickle
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
ACTIVE_CUTOFF_YEAR = 2025

CONTINENT_ORDER = [
    "Europe",
    "Africa",
    "Asia",
    "North America",
    "South America",
    "Oceania",
    "Antarctica",
]
CONTINENT_SLUG = {
    "Europe": "europe",
    "Africa": "africa",
    "Asia": "asia",
    "North America": "north_america",
    "South America": "south_america",
    "Oceania": "oceania",
    "Antarctica": "antarctica",
}

# Only edge cases are named explicitly.  Most stations are classified from
# coordinates.  These name overrides prevent the Mediterranean/Middle-East
# overlap from putting North Africa or the Levant into Europe.
AFRICA_COUNTRY_WORDS = {
    "algeria", "angola", "benin", "botswana", "burkina faso", "burundi",
    "cameroon", "cape verde", "cabo verde", "central african republic", "chad",
    "comoros", "congo", "democratic republic of the congo", "djibouti", "egypt",
    "equatorial guinea", "eritrea", "eswatini", "ethiopia", "gabon", "gambia",
    "ghana", "guinea", "guinea-bissau", "ivory coast", "cote d ivoire", "kenya",
    "lesotho", "liberia", "libya", "madagascar", "malawi", "mali", "mauritania",
    "mauritius", "morocco", "mozambique", "namibia", "niger", "nigeria", "reunion",
    "rwanda", "saint helena", "sao tome", "senegal", "seychelles", "sierra leone",
    "somalia", "south africa", "south sudan", "sudan", "tanzania", "togo", "tunisia",
    "uganda", "western sahara", "zambia", "zimbabwe",
}
ASIA_COUNTRY_WORDS = {
    "afghanistan", "armenia", "azerbaijan", "bahrain", "bangladesh", "bhutan",
    "burma", "myanmar", "cambodia", "china", "georgia", "india", "indonesia",
    "iran", "iraq", "israel", "japan", "jordan", "kazakhstan", "korea", "kuwait",
    "kyrgyzstan", "laos", "lebanon", "malaysia", "maldives", "mongolia", "nepal",
    "north korea", "oman", "pakistan", "palestine", "philippines", "qatar",
    "saudi arabia", "singapore", "south korea", "sri lanka", "syria", "taiwan",
    "tajikistan", "thailand", "timor", "turkey", "turkmenistan", "united arab emirates",
    "uzbekistan", "vietnam", "yemen",
}
OCEANIA_COUNTRY_WORDS = {
    "american samoa", "australia", "cook islands", "fiji", "french polynesia", "guam",
    "kiribati", "marshall islands", "micronesia", "nauru", "new caledonia", "new zealand",
    "niue", "norfolk island", "northern mariana", "palau", "papua new guinea", "pitcairn",
    "samoa", "solomon islands", "tokelau", "tonga", "tuvalu", "vanuatu", "wallis",
}
NORTH_AMERICA_COUNTRY_WORDS = {
    "antigua", "bahamas", "barbados", "belize", "bermuda", "canada", "cayman",
    "costa rica", "cuba", "dominica", "dominican republic", "el salvador", "greenland",
    "grenada", "guadeloupe", "guatemala", "haiti", "honduras", "jamaica", "martinique",
    "mexico", "montserrat", "nicaragua", "panama", "puerto rico", "saint kitts",
    "saint lucia", "saint pierre", "saint vincent", "trinidad", "turks and caicos",
    "united states", "virgin islands",
}
SOUTH_AMERICA_COUNTRY_WORDS = {
    "argentina", "bolivia", "brazil", "chile", "colombia", "ecuador", "falkland",
    "french guiana", "guyana", "paraguay", "peru", "south georgia", "suriname",
    "uruguay", "venezuela",
}

STATION_FIELDS = [
    "id", "name", "country_code", "lat", "lon", "elevation_m", "active",
    "tmax_first_year", "tmax_last_year", "tmin_first_year", "tmin_last_year",
    "tmax_valid", "tmin_valid",
    "tmax_high_tenths", "tmax_high_date", "tmax_low_tenths", "tmax_low_date",
    "tmin_high_tenths", "tmin_high_date", "tmin_low_tenths", "tmin_low_date",
]

COUNTRY_RECORD_FIELDS = [
    "country_code", "country", "metric", "master_status", "publishable",
    "value_c", "date", "site", "source_type", "official_verified", "source",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(text: object) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def named_match(country: str, words: set[str]) -> bool:
    c = norm(country)
    return any(word == c or word in c for word in words)


def continent_for_station(country: str, lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        if named_match(country, AFRICA_COUNTRY_WORDS):
            return "Africa"
        if named_match(country, ASIA_COUNTRY_WORDS):
            return "Asia"
        if named_match(country, OCEANIA_COUNTRY_WORDS):
            return "Oceania"
        return "Europe"

    if lat <= -60:
        return "Antarctica"
    if named_match(country, AFRICA_COUNTRY_WORDS):
        return "Africa"
    if named_match(country, ASIA_COUNTRY_WORDS):
        # Russia is intentionally split geographically below instead of by name.
        if "russia" not in norm(country):
            return "Asia"
    if named_match(country, OCEANIA_COUNTRY_WORDS):
        return "Oceania"
    if named_match(country, SOUTH_AMERICA_COUNTRY_WORDS):
        return "South America"
    if named_match(country, NORTH_AMERICA_COUNTRY_WORDS):
        return "North America"

    c = norm(country)
    if "russia" in c:
        return "Europe" if lon < 60 else "Asia"

    # Americas are geometrically very clean in the GHCN station inventory.
    if -95 <= lon <= -25 and lat < 15:
        return "South America"
    if -170 <= lon <= -20 and lat >= 7:
        return "North America"

    # Europe / Africa / Asia overlap around the Mediterranean.  Country-name
    # overrides above handle the ambiguous southern/eastern shore countries.
    if -25 <= lon <= 60 and 34 <= lat <= 72:
        return "Europe"
    if -25 <= lon <= 60 and -40 <= lat < 34:
        return "Africa"
    if 25 <= lon <= 180 and -12 <= lat <= 82:
        return "Asia"

    # Remaining non-Antarctic stations are predominantly Pacific/Oceania.
    return "Oceania"


def year_from_date(value: object) -> int | None:
    text = str(value or "")
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def record_value(record: dict | None) -> int | None:
    if not record:
        return None
    value = record.get("value_tenths")
    if isinstance(value, int):
        return value
    value_c = record.get("value_c")
    try:
        return round(float(value_c) * 10)
    except (TypeError, ValueError):
        return None


def record_date(record: dict | None) -> str:
    if not record:
        return ""
    return str(record.get("date") or record.get("first_date") or "")


def station_row(station: dict) -> list:
    inv = station.get("inventory") or {}
    tmax_inv = inv.get("TMAX") or {}
    tmin_inv = inv.get("TMIN") or {}
    tmax = station.get("tmax") or {}
    tmin = station.get("tmin") or {}

    tmax_last = tmax_inv.get("last_year") or year_from_date(tmax.get("last_valid_date"))
    tmin_last = tmin_inv.get("last_year") or year_from_date(tmin.get("last_valid_date"))
    last_years = [y for y in (tmax_last, tmin_last) if isinstance(y, int)]
    active = int(bool(last_years and max(last_years) >= ACTIVE_CUTOFF_YEAR))

    return [
        station.get("id") or "",
        station.get("name") or station.get("id") or "",
        station.get("country_code") or "",
        station.get("latitude"),
        station.get("longitude"),
        station.get("elevation_m"),
        active,
        tmax_inv.get("first_year"),
        tmax_last,
        tmin_inv.get("first_year"),
        tmin_last,
        int(tmax.get("valid_count") or 0),
        int(tmin.get("valid_count") or 0),
        record_value(tmax.get("highest_record")),
        record_date(tmax.get("highest_record")),
        record_value(tmax.get("lowest_record")),
        record_date(tmax.get("lowest_record")),
        record_value(tmin.get("highest_record")),
        record_date(tmin.get("highest_record")),
        record_value(tmin.get("lowest_record")),
        record_date(tmin.get("lowest_record")),
    ]


def first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def load_country_records(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = []
        for row in reader:
            rows.append([
                first(row, "country_code"),
                first(row, "country"),
                first(row, "metric"),
                first(row, "master_status", "status"),
                first(row, "publishable"),
                first(row, "canonical_value_c", "value_c"),
                first(row, "canonical_date", "date"),
                first(row, "canonical_site", "site"),
                first(row, "canonical_source_type", "source_type"),
                first(row, "official_verified"),
                first(row, "canonical_source", "source"),
            ])
    return rows


def find_cache(cache_dir: Path, baseline_dir: Path | None) -> Path:
    candidates = sorted(cache_dir.glob("world_ghcn_baseline_through_*_v*.pkl.gz"))
    if baseline_dir:
        candidates += sorted(baseline_dir.glob("world_ghcn_baseline_through_*_v*.pkl.gz"))
    if not candidates:
        raise FileNotFoundError(f"Kein World-GHCN-Baseline-Pickle in {cache_dir} gefunden.")
    return candidates[-1]


def load_pickle(path: Path) -> dict:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def write_gzip_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", compresslevel=9, mtime=0) as handle:
            handle.write(raw)


def build(cache_path: Path, master_input: Path, output_dir: Path) -> dict:
    payload = load_pickle(cache_path)
    stations = payload.get("stations") or {}
    summary = payload.get("summary") or {}

    grouped: dict[str, list[list]] = defaultdict(list)
    countries_by_continent: dict[str, dict[str, str]] = defaultdict(dict)
    active_by_continent: Counter = Counter()
    missing_coords = 0

    for station_id in sorted(stations):
        station = stations[station_id]
        lat = station.get("latitude")
        lon = station.get("longitude")
        if lat is None or lon is None:
            missing_coords += 1
            continue
        continent = continent_for_station(station.get("country") or "", float(lat), float(lon))
        row = station_row(station)
        grouped[continent].append(row)
        code = str(station.get("country_code") or "")
        if code:
            countries_by_continent[continent][code] = str(station.get("country") or code)
        if row[6] == 1:
            active_by_continent[continent] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    packs_dir = output_dir / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)

    packs = {}
    total_rows = 0
    total_active = 0
    for continent in CONTINENT_ORDER:
        rows = grouped.get(continent, [])
        rows.sort(key=lambda r: (str(r[2]), str(r[1]), str(r[0])))
        slug = CONTINENT_SLUG[continent]
        filename = f"packs/{slug}.json.gz"
        pack = {
            "schema_version": SCHEMA_VERSION,
            "continent": continent,
            "fields": STATION_FIELDS,
            "countries": countries_by_continent.get(continent, {}),
            "rows": rows,
        }
        write_gzip_json(output_dir / filename, pack)
        packs[continent] = {
            "file": filename,
            "stations": len(rows),
            "active_stations": int(active_by_continent[continent]),
            "countries": len(countries_by_continent.get(continent, {})),
        }
        total_rows += len(rows)
        total_active += int(active_by_continent[continent])

    country_records = load_country_records(master_input)
    status_counts = Counter(row[3] for row in country_records)
    publishable_count = sum(str(row[4]).strip().lower() in {"yes", "true", "1"} for row in country_records)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "baseline_cutoff_year": summary.get("cutoff_year", ACTIVE_CUTOFF_YEAR),
        "ghcn_version": summary.get("ghcn_version", ""),
        "station_count": total_rows,
        "active_station_count": total_active,
        "stations_without_coordinates": missing_coords,
        "continents": CONTINENT_ORDER,
        "packs": packs,
        "country_record_fields": COUNTRY_RECORD_FIELDS,
        "country_records": country_records,
        "country_record_status_counts": dict(sorted(status_counts.items())),
        "country_record_publishable_count": publishable_count,
        "source_note": (
            "Stationsdaten: NOAA GHCN-Daily, historische Tageswerte bis einschließlich 2025; "
            "nur Beobachtungen mit leerem GHCN-QFLAG. Länderrekorde: QC-Master Stage 9; "
            "offene Fälle bleiben ausdrücklich als UNRESOLVED_REVIEW gekennzeichnet."
        ),
    }
    (output_dir / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "world_ghcn_baseline_through_2025_v1.pkl.gz"
        sample = {
            "summary": {"cutoff_year": 2025, "ghcn_version": "test"},
            "stations": {
                "GME00000001": {
                    "id": "GME00000001", "country_code": "GM", "country": "Germany",
                    "name": "BERLIN TEST", "latitude": 52.5, "longitude": 13.4, "elevation_m": 50.0,
                    "inventory": {"TMAX": {"first_year": 1950, "last_year": 2025}, "TMIN": {"first_year": 1950, "last_year": 2025}},
                    "tmax": {"valid_count": 100, "highest_record": {"value_tenths": 401, "date": "2022-07-20"}, "lowest_record": {"value_tenths": -130, "date": "1956-02-10"}},
                    "tmin": {"valid_count": 99, "highest_record": {"value_tenths": 250, "date": "2018-07-31"}, "lowest_record": {"value_tenths": -250, "date": "1956-02-10"}},
                },
                "ASN00000001": {
                    "id": "ASN00000001", "country_code": "AS", "country": "Australia",
                    "name": "ALICE TEST", "latitude": -23.7, "longitude": 133.9, "elevation_m": 580.0,
                    "inventory": {"TMAX": {"first_year": 1980, "last_year": 2024}, "TMIN": None},
                    "tmax": {"valid_count": 50, "highest_record": {"value_tenths": 470, "date": "2019-01-01"}, "lowest_record": None},
                    "tmin": {"valid_count": 0, "highest_record": None, "lowest_record": None},
                },
            },
        }
        with gzip.open(cache, "wb") as handle:
            pickle.dump(sample, handle)
        master = root / "master.csv"
        master.write_text(
            "country_code;country;metric;master_status;publishable;canonical_value_c;canonical_date;canonical_site;canonical_source_type;official_verified;canonical_source\n"
            "GM;Germany;tmax_highest;GHCN_CANDIDATE;yes;40.1;2022-07-20;Berlin;GHCN;no;NOAA\n",
            encoding="utf-8",
        )
        out = root / "out"
        manifest = build(cache, master, out)
        assert manifest["station_count"] == 2
        assert manifest["active_station_count"] == 1
        assert manifest["packs"]["Europe"]["stations"] == 1
        assert manifest["packs"]["Oceania"]["stations"] == 1
        assert manifest["country_record_publishable_count"] == 1
        assert (out / "packs/europe.json.gz").exists()
        print("build_world_station_web.py self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/world-ghcn"))
    parser.add_argument("--baseline-dir", type=Path, default=Path("world_ghcn_baseline"))
    parser.add_argument("--master-input", type=Path, default=Path("world_ghcn_baseline/qc_stage9/world_country_record_master_stage9.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("world_stations"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    cache = find_cache(args.cache_dir, args.baseline_dir)
    manifest = build(cache, args.master_input, args.output_dir)
    print(json.dumps({
        "station_count": manifest["station_count"],
        "active_station_count": manifest["active_station_count"],
        "country_record_publishable_count": manifest["country_record_publishable_count"],
        "packs": manifest["packs"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
