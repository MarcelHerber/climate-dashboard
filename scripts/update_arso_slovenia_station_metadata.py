#!/usr/bin/env python3
"""Probe/build official ARSO station metadata for the Slovenia temperature IDs.

STEP 8 ONLY:
- reads the already-tested 74-station agrometeorological inventory;
- queries an official ARSO ArcGIS meteorological-station layer;
- matches ArcGIS field ST_POSTAJE to the three-digit Agromet station ID;
- reports exact-ID coverage, coordinate variants and missing IDs;
- writes a small JSON metadata cache for the next integration step.

It DOES NOT modify:
- the historical 1961-2025 temperature cache;
- the 2026 current cache;
- the unified Europe updater.

Official ArcGIS layer:
https://gis.arso.gov.si/arcgis/rest/services/VISFRIM/VISFRIM_new/MapServer/1

Relevant official fields:
ST_POSTAJE, IME_POSTAJ, DAT_ZAC_TI, DAT_KON_TI, Z, GEO_SIR, GEO_DOL
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import update_arso_slovenia_station_cache as core

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")

GIS_LAYER = (
    "https://gis.arso.gov.si/arcgis/rest/services/"
    "VISFRIM/VISFRIM_new/MapServer/1"
)
GIS_QUERY = GIS_LAYER + "/query"

GIS_FIELDS = [
    "ST_POSTAJE",
    "IME_POSTAJ",
    "DAT_ZAC_TI",
    "DAT_KON_TI",
    "ID",
    "Z",
    "GEO_SIR",
    "GEO_DOL",
]


def metadata_path(cache_dir: Path) -> Path:
    return cache_dir / (
        f"arso_slovenia_station_metadata_v{FORMAT_VERSION}.json"
    )


def status_path(cache_dir: Path) -> Path:
    return cache_dir / (
        f"arso_slovenia_station_metadata_status_v{FORMAT_VERSION}.json"
    )


def atomic_json(path: Path, obj: Any) -> None:
    core.atomic_json(path, obj)


def norm_name(value: Any) -> str:
    s = str(value or "").strip().casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def station_id(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            return None
        n = int(value)
    else:
        s = str(value).strip()
        m = re.fullmatch(r"0*(\d{1,3})(?:\.0+)?", s)
        if not m:
            return None
        n = int(m.group(1))

    if not 0 <= n <= 999:
        return None
    return f"{n:03d}"


def finite_float(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def parse_yearish(value: Any) -> tuple[int, int, int]:
    """Return a sortable (year, month, day), unknown -> (0,0,0)."""
    if value is None:
        return (0, 0, 0)

    s = str(value).strip()
    if not s:
        return (9999, 12, 31)  # blank end date generally means still active

    # YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD
    m = re.search(
        r"\b(19\d{2}|20\d{2})[-./](\d{1,2})[-./](\d{1,2})\b",
        s,
    )
    if m:
        return tuple(map(int, m.groups()))

    # DD.MM.YYYY / DD-MM-YYYY / DD/MM/YYYY
    m = re.search(
        r"\b(\d{1,2})[-./](\d{1,2})[-./](19\d{2}|20\d{2})\b",
        s,
    )
    if m:
        d, mo, y = map(int, m.groups())
        return (y, mo, d)

    # At least keep a year if that is all the layer contains.
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    if m:
        return (int(m.group(1)), 1, 1)

    return (0, 0, 0)


def make_query_url() -> str:
    params = {
        "where": "1=1",
        "outFields": ",".join(GIS_FIELDS),
        "returnGeometry": "false",
        "f": "json",
    }
    return GIS_QUERY + "?" + urlencode(params)


def load_gis_rows() -> tuple[list[dict[str, Any]], str]:
    url = make_query_url()
    raw = core.http_bytes(url)
    data = json.loads(core.decode(raw))

    if "error" in data:
        raise RuntimeError(
            "ARSO ArcGIS query error: "
            + json.dumps(data["error"], ensure_ascii=False)
        )

    features = data.get("features")
    if not isinstance(features, list):
        raise RuntimeError(
            "ARSO ArcGIS response enthält keine 'features'-Liste."
        )

    rows: list[dict[str, Any]] = []
    for feature in features:
        attrs = feature.get("attributes") if isinstance(feature, dict) else None
        if isinstance(attrs, dict):
            rows.append(attrs)

    if not rows:
        raise RuntimeError("ARSO ArcGIS query lieferte 0 Datensätze.")

    return rows, url


def coordinate_from_row(row: dict[str, Any]) -> tuple[float, float, float | None] | None:
    lat = finite_float(row.get("GEO_SIR"))
    lon = finite_float(row.get("GEO_DOL"))
    elev = finite_float(row.get("Z"))

    # Slovenia bounding box with a little safety margin.
    if lat is None or lon is None:
        return None
    if not (45.0 <= lat <= 47.2 and 13.0 <= lon <= 17.0):
        return None
    if elev is not None and not (-20 <= elev <= 3000):
        elev = None

    return (lat, lon, elev)


def row_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    """Prefer the most recently applicable station-location row."""
    end = parse_yearish(row.get("DAT_KON_TI"))
    start = parse_yearish(row.get("DAT_ZAC_TI"))
    has_coord = coordinate_from_row(row) is not None
    return (
        1 if has_coord else 0,
        end,
        start,
        int(finite_float(row.get("ID")) or 0),
    )


def unique_coordinate_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[float, float, float | None], dict[str, Any]] = {}

    for row in rows:
        coord = coordinate_from_row(row)
        if coord is None:
            continue

        lat, lon, elev = coord
        key = (
            round(lat, 5),
            round(lon, 5),
            None if elev is None else round(elev, 1),
        )

        if key not in seen:
            seen[key] = {
                "lat": lat,
                "lon": lon,
                "elevation_m": elev,
                "gis_name": row.get("IME_POSTAJ"),
                "start": row.get("DAT_ZAC_TI"),
                "end": row.get("DAT_KON_TI"),
                "gis_id": row.get("ID"),
            }

    return list(seen.values())


def build_metadata(
    inventory: dict[str, dict[str, Any]],
    gis_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_sid: dict[str, list[dict[str, Any]]] = {}

    for row in gis_rows:
        sid = station_id(row.get("ST_POSTAJE"))
        if sid is None:
            continue
        by_sid.setdefault(sid, []).append(row)

    metadata: dict[str, dict[str, Any]] = {}
    missing_ids: list[str] = []
    no_coordinate_ids: list[str] = []
    multirow_ids: list[str] = []
    multicoordinate_ids: list[str] = []
    name_mismatches: list[dict[str, Any]] = []

    for sid in sorted(inventory):
        inv = inventory[sid]
        candidates = by_sid.get(sid, [])

        if not candidates:
            missing_ids.append(sid)
            continue

        if len(candidates) > 1:
            multirow_ids.append(sid)

        candidates = sorted(candidates, key=row_rank, reverse=True)
        chosen = candidates[0]
        coord = coordinate_from_row(chosen)

        # If the nominally newest row has no usable coordinate, use the
        # newest row that does.
        if coord is None:
            chosen = next(
                (
                    row
                    for row in candidates
                    if coordinate_from_row(row) is not None
                ),
                chosen,
            )
            coord = coordinate_from_row(chosen)

        variants = unique_coordinate_variants(candidates)
        if len(variants) > 1:
            multicoordinate_ids.append(sid)

        if coord is None:
            no_coordinate_ids.append(sid)
            metadata[sid] = {
                "station_id": sid,
                "name": inv.get("name"),
                "lat": None,
                "lon": None,
                "elevation_m": None,
                "gis_name": chosen.get("IME_POSTAJ"),
                "gis_start": chosen.get("DAT_ZAC_TI"),
                "gis_end": chosen.get("DAT_KON_TI"),
                "gis_id": chosen.get("ID"),
                "coordinate_variants": variants,
            }
            continue

        lat, lon, elev = coord

        inv_name = inv.get("name")
        gis_name = chosen.get("IME_POSTAJ")
        ni = norm_name(inv_name)
        ng = norm_name(gis_name)

        # Only informational. Names can legitimately differ slightly.
        if ni and ng and ni not in ng and ng not in ni:
            name_mismatches.append(
                {
                    "station_id": sid,
                    "inventory_name": inv_name,
                    "gis_name": gis_name,
                }
            )

        metadata[sid] = {
            "station_id": sid,
            "name": inv_name,
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "gis_name": gis_name,
            "gis_start": chosen.get("DAT_ZAC_TI"),
            "gis_end": chosen.get("DAT_KON_TI"),
            "gis_id": chosen.get("ID"),
            "coordinate_variants": variants,
        }

    matched_ids = sorted(metadata)
    coordinate_ids = sorted(
        sid
        for sid, meta in metadata.items()
        if meta.get("lat") is not None and meta.get("lon") is not None
    )

    return {
        "metadata": metadata,
        "matched_ids": matched_ids,
        "coordinate_ids": coordinate_ids,
        "missing_ids": missing_ids,
        "no_coordinate_ids": no_coordinate_ids,
        "multirow_ids": multirow_ids,
        "multicoordinate_ids": multicoordinate_ids,
        "name_mismatches": name_mismatches,
        "gis_station_id_count": len(by_sid),
    }


def known_station_checks(metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Independent sanity checks against ARSO climate pages."""
    expected = {
        # ID: (lat, lon, elevation)
        "192": (46.0655, 14.5124, 299.0),   # Ljubljana Bežigrad
        "097": (45.8956, 13.6240, 55.0),    # Bilje
        "048": (46.3787, 13.8489, 2513.0),  # Kredarica
    }

    checks = []
    for sid, (elat, elon, eelev) in expected.items():
        meta = metadata.get(sid)
        if not meta or meta.get("lat") is None or meta.get("lon") is None:
            checks.append(
                {
                    "station_id": sid,
                    "ok": False,
                    "reason": "missing GIS coordinate",
                }
            )
            continue

        lat = float(meta["lat"])
        lon = float(meta["lon"])
        elev = meta.get("elevation_m")

        horizontal_ok = abs(lat - elat) <= 0.03 and abs(lon - elon) <= 0.03
        elevation_ok = (
            elev is None
            or abs(float(elev) - eelev) <= 60.0
        )

        checks.append(
            {
                "station_id": sid,
                "ok": bool(horizontal_ok and elevation_ok),
                "gis": {
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": elev,
                },
                "reference": {
                    "lat": elat,
                    "lon": elon,
                    "elevation_m": eelev,
                },
            }
        )

    return checks


def run(cache_dir: Path) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("=== ARSO SLOWENIEN · STATIONSMETADATEN ===", flush=True)
    print("Ziel: offizielle Koordinaten/Höhen für die 74 Agromet-IDs", flush=True)
    print(f"GIS-Layer: {GIS_LAYER}", flush=True)

    inventory, inventory_source = core.load_inventory()
    print(f"Agromet-Inventar: {len(inventory):,} Stationen", flush=True)
    print(f"Inventarquelle: {inventory_source}", flush=True)

    gis_rows, query_url = load_gis_rows()
    print(f"ARSO-GIS-Datensätze: {len(gis_rows):,}", flush=True)

    result = build_metadata(inventory, gis_rows)
    metadata = result["metadata"]
    checks = known_station_checks(metadata)

    payload = {
        "format_version": FORMAT_VERSION,
        "source": "ARSO official ArcGIS meteorological station layer",
        "source_layer": GIS_LAYER,
        "query_url": query_url,
        "inventory_source": inventory_source,
        "inventory_count": len(inventory),
        "gis_row_count": len(gis_rows),
        "gis_station_id_count": result["gis_station_id_count"],
        "matched_id_count": len(result["matched_ids"]),
        "coordinate_id_count": len(result["coordinate_ids"]),
        "missing_id_count": len(result["missing_ids"]),
        "no_coordinate_id_count": len(result["no_coordinate_ids"]),
        "multirow_id_count": len(result["multirow_ids"]),
        "multicoordinate_id_count": len(result["multicoordinate_ids"]),
        "metadata": metadata,
        "missing_ids": result["missing_ids"],
        "no_coordinate_ids": result["no_coordinate_ids"],
        "multirow_ids": result["multirow_ids"],
        "multicoordinate_ids": result["multicoordinate_ids"],
        "name_mismatches": result["name_mismatches"],
        "known_station_checks": checks,
        "updated_utc": datetime.now(UTC).isoformat(),
    }

    out = metadata_path(cache_dir)
    atomic_json(out, payload)

    known_ok = sum(1 for x in checks if x.get("ok"))
    status = {
        "complete_probe": True,
        "metadata_file": str(out),
        "inventory_count": len(inventory),
        "gis_row_count": len(gis_rows),
        "gis_station_id_count": result["gis_station_id_count"],
        "matched_id_count": len(result["matched_ids"]),
        "coordinate_id_count": len(result["coordinate_ids"]),
        "missing_id_count": len(result["missing_ids"]),
        "no_coordinate_id_count": len(result["no_coordinate_ids"]),
        "multirow_id_count": len(result["multirow_ids"]),
        "multicoordinate_id_count": len(result["multicoordinate_ids"]),
        "name_mismatch_count": len(result["name_mismatches"]),
        "known_station_checks_ok": known_ok,
        "known_station_checks_total": len(checks),
        "missing_ids": result["missing_ids"],
        "no_coordinate_ids": result["no_coordinate_ids"],
        "multicoordinate_ids": result["multicoordinate_ids"],
        "updated_utc": datetime.now(UTC).isoformat(),
    }

    atomic_json(status_path(cache_dir), status)

    print()
    print("=" * 88)
    print("ARSO SLOWENIEN · METADATEN STATUS")
    print("=" * 88)
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print()
    print("Bekannte Stations-Checks:")
    for item in checks:
        print(json.dumps(item, ensure_ascii=False))

    if result["name_mismatches"]:
        print()
        print("Erste Namensabweichungen (nur Hinweis):")
        for item in result["name_mismatches"][:15]:
            print(json.dumps(item, ensure_ascii=False))

    print()
    print(f"Output: {out}")
    print("ARSO Slowenien Metadaten-Abgleich abgeschlossen.")
    return 0


def self_test() -> int:
    inventory = {
        "048": {"name": "Kredarica"},
        "097": {"name": "Bilje"},
        "192": {"name": "Ljubljana Bežigrad"},
        "816": {"name": "Podnanos"},
    }

    rows = [
        {
            "ST_POSTAJE": 48,
            "IME_POSTAJ": "KREDARICA",
            "DAT_ZAC_TI": "01.01.1961",
            "DAT_KON_TI": "",
            "ID": 1,
            "Z": 2513,
            "GEO_SIR": 46.3787,
            "GEO_DOL": 13.8489,
        },
        {
            "ST_POSTAJE": "097",
            "IME_POSTAJ": "Bilje",
            "DAT_ZAC_TI": "1962-01-01",
            "DAT_KON_TI": None,
            "ID": 2,
            "Z": 55,
            "GEO_SIR": 45.8956,
            "GEO_DOL": 13.6240,
        },
        {
            "ST_POSTAJE": 192.0,
            "IME_POSTAJ": "Ljubljana Bezigrad",
            "DAT_ZAC_TI": "1961",
            "DAT_KON_TI": "2010",
            "ID": 3,
            "Z": 299,
            "GEO_SIR": 46.0650,
            "GEO_DOL": 14.5119,
        },
        {
            "ST_POSTAJE": 192,
            "IME_POSTAJ": "Ljubljana Bežigrad",
            "DAT_ZAC_TI": "2011",
            "DAT_KON_TI": "",
            "ID": 4,
            "Z": 299,
            "GEO_SIR": 46.0655,
            "GEO_DOL": 14.5124,
        },
    ]

    result = build_metadata(inventory, rows)

    assert station_id(48) == "048"
    assert station_id("097") == "097"
    assert station_id(192.0) == "192"

    assert result["missing_ids"] == ["816"]
    assert result["multirow_ids"] == ["192"]
    assert result["multicoordinate_ids"] == ["192"]
    assert result["metadata"]["192"]["gis_id"] == 4
    assert result["metadata"]["192"]["lat"] == 46.0655

    checks = known_station_checks(result["metadata"])
    assert sum(1 for x in checks if x["ok"]) == 3

    print("ARSO Slovenia station-metadata self-test OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR_DEFAULT,
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    return run(args.cache_dir)


if __name__ == "__main__":
    raise SystemExit(main())
