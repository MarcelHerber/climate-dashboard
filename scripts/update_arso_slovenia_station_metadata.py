#!/usr/bin/env python3
"""Build ARSO Slovenia station metadata from official Agromet metadata CSVs.

STEP 8f ONLY.

Primary metadata sources are now the two official ARSO Agromet station
metadata files from the SAME product family as the temperature month tables:

Current/automatic stations:
  https://meteo.arso.gov.si/uploads/probase/www/agromet/product/form/sl/etp_17xx_post.csv

Historical/classic stations:
  https://meteo.arso.gov.si/uploads/probase/www/agromet/product/form/sl/etp_6116_post.csv

Both are linked by ARSO as:
  "Meta podatki postaj (geo. širina, dolžina WGS84 [°] in nadmorska višina [m])"

The national ARSO Atlas okolja meteorological-station layer remains a
secondary exact-ID fallback.

Matching policy:
1. exact Agromet ID in the national GIS layer;
2. exact normalized station name in the appropriate official Agromet
   metadata CSV (historical/current period aware);
3. exact normalized name in the other Agromet CSV;
4. conservative, explicit aliases only where ARSO itself uses a shorter
   historic display name;
5. exact normalized station name in the national GIS layer;
6. direct official ARSO historical-normal coordinate reference for three verified discontinued IDs;
7. fuzzy suggestions are PRINTED ONLY and never auto-accepted.

No Europe integration happens here.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, UTC
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import update_arso_slovenia_station_cache as core

FORMAT_VERSION = 6
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")

AGROMET_CURRENT_META = (
    "https://meteo.arso.gov.si/uploads/probase/www/agromet/"
    "product/form/sl/etp_17xx_post.csv"
)
AGROMET_HIST_META = (
    "https://meteo.arso.gov.si/uploads/probase/www/agromet/"
    "product/form/sl/etp_6116_post.csv"
)

GIS_LAYER = (
    "https://gis.arso.gov.si/arcgis/rest/services/"
    "Atlasokolja_intranet_D96/MapServer/81"
)
GIS_QUERY = GIS_LAYER + "/query"
GHCN_STATIONS_URL = (
    "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
)

GIS_FIELDS = [
    "OBJECTID",
    "IDMM",
    "ST_POSTAJE",
    "IME_POSTAJE",
    "TIP",
    "SIF_MERITVE",
    "DAT_ZAC_TIPA",
    "DAT_KON_TIPA",
    "Z",
    "GEO_SIR",
    "GEO_DOL",
]

# Only conservative display-name aliases supported by official ARSO pages.
NAME_ALIASES = {
    "slap vipava": ["slap"],
    "podcetrtek i": ["podcetrtek"],
    "gornja radgona i": ["gornja radgona"],
    # ARSO Agromet uses the longer current display name.
    "turski vrh": ["turski vrh pri zavrcu"],
}


def metadata_path(cache_dir: Path) -> Path:
    return cache_dir / f"arso_slovenia_station_metadata_v{FORMAT_VERSION}.json"


def status_path(cache_dir: Path) -> Path:
    return cache_dir / f"arso_slovenia_station_metadata_status_v{FORMAT_VERSION}.json"


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def norm_name(value: Any) -> str:
    s = str(value or "").strip().casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def station_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
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


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("\xa0", " ")
    if not s:
        return None
    s = s.replace(",", ".")
    s = re.sub(r"[^0-9+\-.]", "", s)
    if not s or s in {"+", "-", ".", "+.", "-."}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def valid_coord(lat: float | None, lon: float | None) -> bool:
    return (
        lat is not None
        and lon is not None
        and 45.0 <= lat <= 47.2
        and 13.0 <= lon <= 17.0
    )


def valid_elevation(x: float | None) -> float | None:
    if x is None:
        return None
    return x if -20.0 <= x <= 3000.0 else None


def decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";\t,|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", "\t", ",", "|")}
        return max(counts, key=counts.get)


def header_index(header: list[str], groups: list[list[str]]) -> int | None:
    hn = [norm_name(x) for x in header]
    for patterns in groups:
        for i, h in enumerate(hn):
            if all(p in h for p in patterns):
                return i
    return None


def parse_agromet_metadata(raw: bytes, source_name: str) -> list[dict[str, Any]]:
    text = decode_bytes(raw)
    delimiter = detect_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [[cell.strip() for cell in row] for row in rows if any(c.strip() for c in row)]

    if not rows:
        raise RuntimeError(f"{source_name}: Metadaten-CSV ist leer.")

    header_i = None
    indices = None

    # Search first rows for a recognizable header.
    for i, row in enumerate(rows[:12]):
        name_i = header_index(
            row,
            [
                ["postaja"],
                ["station"],
                ["ime", "post"],
                ["naziv"],
            ],
        )
        lat_i = header_index(
            row,
            [
                ["geo", "sir"],
                ["sirina"],
                ["latitude"],
                ["lat"],
            ],
        )
        lon_i = header_index(
            row,
            [
                ["geo", "dol"],
                ["dolzina"],
                ["longitude"],
                ["lon"],
            ],
        )
        elev_i = header_index(
            row,
            [
                ["nadmors"],
                ["visina"],
                ["elevation"],
                ["elev"],
                ["nmv"],
            ],
        )
        if name_i is not None and lat_i is not None and lon_i is not None:
            header_i = i
            indices = (name_i, lat_i, lon_i, elev_i)
            break

    parsed: list[dict[str, Any]] = []

    if header_i is not None and indices is not None:
        name_i, lat_i, lon_i, elev_i = indices
        for row in rows[header_i + 1 :]:
            if name_i >= len(row):
                continue
            name = row[name_i].strip()
            lat = parse_number(row[lat_i]) if lat_i < len(row) else None
            lon = parse_number(row[lon_i]) if lon_i < len(row) else None
            elev = (
                parse_number(row[elev_i])
                if elev_i is not None and elev_i < len(row)
                else None
            )

            # Occasionally longitude/latitude ordering is reversed.
            if not valid_coord(lat, lon) and valid_coord(lon, lat):
                lat, lon = lon, lat

            if name and valid_coord(lat, lon):
                parsed.append(
                    {
                        "name": name,
                        "norm_name": norm_name(name),
                        "lat": float(lat),
                        "lon": float(lon),
                        "elevation_m": valid_elevation(elev),
                        "source": source_name,
                        "raw": row,
                    }
                )
    else:
        # Header-independent fallback. Find a textual station cell plus two
        # decimal values that form a Slovenia WGS84 coordinate pair.
        for row in rows:
            if len(row) < 3:
                continue

            name = next(
                (
                    cell.strip()
                    for cell in row
                    if cell.strip()
                    and any(ch.isalpha() for ch in cell)
                    and parse_number(cell) is None
                ),
                "",
            )
            if not name:
                continue

            nums = [(j, parse_number(cell)) for j, cell in enumerate(row)]
            nums = [(j, x) for j, x in nums if x is not None]

            lat = lon = None
            used = set()

            for j1, x1 in nums:
                for j2, x2 in nums:
                    if j1 == j2:
                        continue
                    if valid_coord(x1, x2):
                        lat, lon = float(x1), float(x2)
                        used = {j1, j2}
                        break
                if lat is not None:
                    break

            if lat is None:
                continue

            elevation = None
            for j, x in nums:
                if j in used:
                    continue
                if -20.0 <= x <= 3000.0:
                    # Elevations are typically integer-ish and outside the
                    # lat/lon range; prefer the first plausible value > 20 m.
                    if x > 20:
                        elevation = float(x)
                        break

            parsed.append(
                {
                    "name": name,
                    "norm_name": norm_name(name),
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": valid_elevation(elevation),
                    "source": source_name,
                    "raw": row,
                }
            )

    if not parsed:
        preview = "\n".join(delimiter.join(r) for r in rows[:8])
        raise RuntimeError(
            f"{source_name}: keine WGS84-Stationsmetadaten erkannt. Vorschau:\n{preview}"
        )

    return parsed


def load_agromet_metadata() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current = parse_agromet_metadata(
        core.http_bytes(AGROMET_CURRENT_META),
        "ARSO Agromet 2017-current metadata",
    )
    historical = parse_agromet_metadata(
        core.http_bytes(AGROMET_HIST_META),
        "ARSO Agromet 1961-2016 metadata",
    )
    return current, historical


def make_gis_url() -> str:
    params = {
        "where": "1=1",
        "outFields": ",".join(GIS_FIELDS),
        "returnGeometry": "false",
        "resultRecordCount": "1000",
        "f": "json",
    }
    return GIS_QUERY + "?" + urlencode(params)


def load_gis_rows() -> list[dict[str, Any]]:
    raw = core.http_bytes(make_gis_url())
    data = json.loads(core.decode(raw))
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False))
    if data.get("exceededTransferLimit"):
        raise RuntimeError("ARSO GIS exceededTransferLimit.")
    features = data.get("features", [])
    rows = [
        f.get("attributes")
        for f in features
        if isinstance(f, dict) and isinstance(f.get("attributes"), dict)
    ]
    if not rows:
        raise RuntimeError("ARSO nationaler GIS-Layer ist leer.")
    return rows


def gis_coord(row: dict[str, Any]) -> tuple[float, float, float | None] | None:
    lat = parse_number(row.get("GEO_SIR"))
    lon = parse_number(row.get("GEO_DOL"))
    elev = parse_number(row.get("Z"))
    if not valid_coord(lat, lon):
        return None
    return float(lat), float(lon), valid_elevation(elev)


def choose_gis_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [r for r in rows if gis_coord(r) is not None]
    if not usable:
        return None

    # Prefer rows with open-ended type periods, then newest OBJECTID.
    def key(row):
        end = str(row.get("DAT_KON_TIPA") or "").strip()
        open_ended = 1 if not end else 0
        oid = int(parse_number(row.get("OBJECTID")) or 0)
        return (open_ended, oid)

    return max(usable, key=key)


def coord_key(item: dict[str, Any]) -> tuple[float, float]:
    return (round(float(item["lat"]), 5), round(float(item["lon"]), 5))


def index_by_name(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        n = row.get("norm_name") or norm_name(row.get("name"))
        if n:
            out[n].append(row)
    return dict(out)


def unique_coord_candidate(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not rows:
        return None, []
    variants = {}
    for row in rows:
        variants.setdefault(coord_key(row), row)
    unique_rows = list(variants.values())
    if len(unique_rows) == 1:
        return unique_rows[0], unique_rows
    return None, unique_rows


def period_preference(meta: dict[str, Any]) -> list[str]:
    start = meta.get("start_year")
    end = meta.get("end_year")

    if isinstance(end, int) and end <= 2016:
        return ["historical", "current"]
    if isinstance(start, int) and start >= 2017:
        return ["current", "historical"]
    # Long/open series: prefer current site metadata when available.
    return ["current", "historical"]


def fuzzy_suggestions(
    wanted: str,
    all_rows: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    scores = []
    for row in all_rows:
        candidate = row.get("norm_name") or ""
        if not candidate:
            continue
        score = SequenceMatcher(None, wanted, candidate).ratio()
        scores.append((score, candidate, row))
    scores.sort(reverse=True, key=lambda x: x[0])

    out = []
    seen = set()
    for score, candidate, row in scores:
        key = (candidate, coord_key(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "score": round(score, 3),
                "name": row.get("name"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "elevation_m": row.get("elevation_m"),
                "source": row.get("source"),
            }
        )
        if len(out) >= limit:
            break
    return out



def index_gis_by_name(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        n = norm_name(row.get("IME_POSTAJE"))
        if n:
            out[n].append(row)
    return dict(out)


def choose_gis_name_row(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Conservative exact-name GIS matcher.

    Multiple layer rows are common because ARSO stores different station/type
    periods. We accept only when all usable rows are geographically coherent:
    maximum pairwise spread <= 0.03 degrees in both latitude and longitude.
    Then the usual GIS row ranking chooses the representative row.
    """
    usable = [row for row in rows if gis_coord(row) is not None]
    if not usable:
        return None, []

    coords = [gis_coord(row) for row in usable]
    lats = [c[0] for c in coords if c is not None]
    lons = [c[1] for c in coords if c is not None]

    if (max(lats) - min(lats)) > 0.03 or (max(lons) - min(lons)) > 0.03:
        return None, usable

    return choose_gis_row(usable), usable


# Independent ARSO 1971-2000 normal-table references for three historical IDs.
# These are deliberately low precision (degree + minute) and are used only as
# a plausibility cross-check, never as the coordinate source itself.

# Direct official ARSO climate-normal coordinates for historical stations
# that no longer appear in the current ID/name metadata layers.
#
# Source PDFs:
# 045 Stara Fužina:
# https://meteo.arso.gov.si/uploads/probase/www/climate/table/en/by_location/stara-fuzina/climate-normals_71-00_stara-fuzina.pdf
# 334 Gornja Radgona:
# https://meteo.arso.gov.si/uploads/probase/www/climate/table/en/by_location/gornja-radgona/climate-normals_71-00_gornja-radgona.pdf
# 349 Podgradje:
# https://meteo.arso.gov.si/uploads/probase/www/climate/table/en/by_location/podgradje/climate-normals_71-00_podgradje.pdf
OFFICIAL_HISTORICAL_COORDS = {
    "045": {
        "lat": 46 + 17 / 60,
        "lon": 13 + 54 / 60,
        "elevation_m": 547.0,
        "metadata_name": "STARA FUŽINA",
        "metadata_source": "ARSO climate normals 1971-2000",
    },
    "334": {
        "lat": 46 + 40 / 60,
        "lon": 16 + 0 / 60,
        "elevation_m": 232.0,
        "metadata_name": "GORNJA RADGONA",
        "metadata_source": "ARSO climate normals 1971-2000",
    },
    "349": {
        "lat": 46 + 30 / 60,
        "lon": 16 + 14 / 60,
        "elevation_m": 272.0,
        "metadata_name": "PODGRADJE",
        "metadata_source": "ARSO climate normals 1971-2000",
    },
}

HISTORICAL_NORMAL_REFS = {
    "045": (46 + 17 / 60, 13 + 54 / 60, 547.0),  # Stara Fužina
    "334": (46 + 40 / 60, 16 + 0 / 60, 232.0),   # Gornja Radgona
    "349": (46 + 30 / 60, 16 + 14 / 60, 272.0),  # Podgradje
}


def historical_ref_ok(
    sid: str,
    row: dict[str, Any],
) -> bool:
    ref = HISTORICAL_NORMAL_REFS.get(sid)
    if ref is None:
        return True

    coord = gis_coord(row)
    if coord is None:
        return False

    lat, lon, elev = coord
    rlat, rlon, relev = ref

    if abs(lat - rlat) > 0.05 or abs(lon - rlon) > 0.05:
        return False
    if elev is not None and abs(float(elev) - relev) > 120.0:
        return False
    return True


def parse_ghcn_stations(raw: bytes) -> list[dict[str, Any]]:
    """Parse NOAA GHCN-Daily fixed-width station metadata."""
    text = raw.decode("utf-8", errors="replace")
    rows = []
    for line in text.splitlines():
        if len(line) < 71:
            continue
        sid = line[0:11].strip()
        lat = parse_number(line[12:20])
        lon = parse_number(line[21:30])
        elev = parse_number(line[31:37])
        name = line[41:71].strip()

        if not sid or not name or not valid_coord(lat, lon):
            continue

        rows.append(
            {
                "ghcn_id": sid,
                "name": name,
                "norm_name": norm_name(name),
                "lat": float(lat),
                "lon": float(lon),
                "elevation_m": valid_elevation(elev),
            }
        )
    return rows


def load_ghcn_stations() -> list[dict[str, Any]]:
    raw = core.http_bytes(GHCN_STATIONS_URL)
    rows = parse_ghcn_stations(raw)
    if not rows:
        raise RuntimeError("NOAA GHCN-Stationsmetadaten konnten nicht gelesen werden.")
    return rows


def ghcn_crosswalk_for_turski_vrh(
    ghcn_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Strict independent crosswalk for ARSO 346 Turški Vrh only.

    Requirements:
    - exact normalized name TURSKI VRH, or a name beginning with it;
    - location inside Slovenia bounding box;
    - GHCN elevation within 100 m of ARSO's documented 280 m;
    - all surviving candidates must refer to essentially the same location.
    """
    wanted = "turski vrh"
    candidates = []

    for row in ghcn_rows:
        name = row.get("norm_name", "")
        if not (name == wanted or name.startswith(wanted + " ")):
            continue

        lat = row.get("lat")
        lon = row.get("lon")
        elev = row.get("elevation_m")

        if not valid_coord(lat, lon):
            continue

        if elev is not None and abs(float(elev) - 280.0) > 100.0:
            continue

        candidates.append(row)

    if not candidates:
        return None, []

    lats = [float(x["lat"]) for x in candidates]
    lons = [float(x["lon"]) for x in candidates]

    # Reject if NOAA contains geographically distinct namesakes.
    if (max(lats) - min(lats)) > 0.05 or (max(lons) - min(lons)) > 0.05:
        return None, candidates

    # Prefer closest elevation to ARSO's 280 m, then shortest name.
    chosen = min(
        candidates,
        key=lambda x: (
            abs(float(x["elevation_m"]) - 280.0)
            if x.get("elevation_m") is not None
            else 9999.0,
            len(x.get("name", "")),
        ),
    )
    return chosen, candidates


def build_metadata(
    inventory: dict[str, dict[str, Any]],
    current_rows: list[dict[str, Any]],
    historical_rows: list[dict[str, Any]],
    gis_rows: list[dict[str, Any]],
    ghcn_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_by_name = index_by_name(current_rows)
    hist_by_name = index_by_name(historical_rows)

    gis_by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in gis_rows:
        sid = station_id(row.get("ST_POSTAJE"))
        if sid:
            gis_by_sid[sid].append(row)
    gis_by_name = index_gis_by_name(gis_rows)

    all_meta_rows = current_rows + historical_rows

    metadata = {}
    unresolved = []
    methods = defaultdict(int)

    for sid in sorted(inventory):
        inv = inventory[sid]
        inv_name = inv.get("name") or ""
        wanted = norm_name(inv_name)

        # 1) Exact official ID in national GIS.
        chosen_gis = choose_gis_row(gis_by_sid.get(sid, []))
        if chosen_gis is not None:
            lat, lon, elev = gis_coord(chosen_gis)
            metadata[sid] = {
                "station_id": sid,
                "name": inv_name,
                "lat": lat,
                "lon": lon,
                "elevation_m": elev,
                "match_method": "gis_exact_id",
                "metadata_name": chosen_gis.get("IME_POSTAJE"),
                "metadata_source": GIS_LAYER,
                "matched_gis_station_id": station_id(
                    chosen_gis.get("ST_POSTAJE")
                ),
            }
            methods["gis_exact_id"] += 1
            continue

        indexes = {
            "current": current_by_name,
            "historical": hist_by_name,
        }

        accepted = None
        ambiguity = []

        # 2/3) Exact name, period-aware.
        for period in period_preference(inv):
            rows = indexes[period].get(wanted, [])
            one, variants = unique_coord_candidate(rows)
            if one is not None:
                accepted = (one, f"agromet_{period}_exact_name")
                break
            if len(variants) > 1:
                ambiguity.extend(variants)

        # 4) Conservative aliases only.
        if accepted is None:
            for alias in NAME_ALIASES.get(wanted, []):
                for period in period_preference(inv):
                    rows = indexes[period].get(alias, [])
                    one, variants = unique_coord_candidate(rows)
                    if one is not None:
                        accepted = (one, f"agromet_{period}_official_alias")
                        break
                    if len(variants) > 1:
                        ambiguity.extend(variants)
                if accepted is not None:
                    break

        if accepted is not None:
            row, method = accepted
            metadata[sid] = {
                "station_id": sid,
                "name": inv_name,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "elevation_m": row.get("elevation_m"),
                "match_method": method,
                "metadata_name": row.get("name"),
                "metadata_source": row.get("source"),
                "matched_gis_station_id": None,
            }
            methods[method] += 1
            continue

        # 5) Exact normalized name in the national official GIS layer.
        # Try the literal inventory name first, then only the conservative
        # aliases already used above. Fuzzy GIS matches are never accepted.
        gis_names = [wanted] + NAME_ALIASES.get(wanted, [])
        gis_accepted = None
        gis_ambiguous = []

        for gis_name in gis_names:
            candidate, candidate_rows = choose_gis_name_row(
                gis_by_name.get(gis_name, [])
            )
            if candidate is not None and historical_ref_ok(sid, candidate):
                gis_accepted = candidate
                break
            if candidate_rows:
                gis_ambiguous.extend(candidate_rows)

        if gis_accepted is not None:
            lat, lon, elev = gis_coord(gis_accepted)
            metadata[sid] = {
                "station_id": sid,
                "name": inv_name,
                "lat": lat,
                "lon": lon,
                "elevation_m": elev,
                "match_method": "gis_exact_name",
                "metadata_name": gis_accepted.get("IME_POSTAJE"),
                "metadata_source": GIS_LAYER,
                "matched_gis_station_id": station_id(
                    gis_accepted.get("ST_POSTAJE")
                ),
            }
            methods["gis_exact_name"] += 1
            continue

        # 6) Direct historical ARSO climate-normal coordinate reference.
        # Only three explicitly verified discontinued IDs are allowed here.
        hist_ref = OFFICIAL_HISTORICAL_COORDS.get(sid)
        if hist_ref is not None:
            metadata[sid] = {
                "station_id": sid,
                "name": inv_name,
                "lat": float(hist_ref["lat"]),
                "lon": float(hist_ref["lon"]),
                "elevation_m": float(hist_ref["elevation_m"]),
                "match_method": "arso_historical_normals",
                "metadata_name": hist_ref["metadata_name"],
                "metadata_source": hist_ref["metadata_source"],
                "matched_gis_station_id": None,
            }
            methods["arso_historical_normals"] += 1
            continue

        # 7) Independent NOAA GHCN crosswalk, intentionally restricted to
        # the one remaining historical ARSO station 346 Turški Vrh.
        if sid == "346" and ghcn_rows:
            ghcn_match, ghcn_candidates = ghcn_crosswalk_for_turski_vrh(
                ghcn_rows
            )
            if ghcn_match is not None:
                metadata[sid] = {
                    "station_id": sid,
                    "name": inv_name,
                    "lat": float(ghcn_match["lat"]),
                    "lon": float(ghcn_match["lon"]),
                    "elevation_m": (
                        float(ghcn_match["elevation_m"])
                        if ghcn_match.get("elevation_m") is not None
                        else 280.0
                    ),
                    "match_method": "noaa_ghcn_crosswalk",
                    "metadata_name": ghcn_match["name"],
                    "metadata_source": GHCN_STATIONS_URL,
                    "matched_gis_station_id": None,
                    "matched_ghcn_station_id": ghcn_match["ghcn_id"],
                    "arso_documented_elevation_m": 280.0,
                }
                methods["noaa_ghcn_crosswalk"] += 1
                continue
        else:
            ghcn_candidates = []

        unresolved.append(
            {
                "station_id": sid,
                "name": inv_name,
                "start_year": inv.get("start_year"),
                "end_year": inv.get("end_year"),
                "ambiguous_exact_coordinates": [
                    {
                        "name": x.get("name"),
                        "lat": x.get("lat"),
                        "lon": x.get("lon"),
                        "source": x.get("source"),
                    }
                    for x in ambiguity
                ],
                "ambiguous_gis_exact_name_rows": [
                    {
                        "gis_station_id": station_id(x.get("ST_POSTAJE")),
                        "name": x.get("IME_POSTAJE"),
                        "coord": gis_coord(x),
                    }
                    for x in gis_ambiguous
                ],
                "ghcn_candidates": [
                    {
                        "ghcn_id": x.get("ghcn_id"),
                        "name": x.get("name"),
                        "lat": x.get("lat"),
                        "lon": x.get("lon"),
                        "elevation_m": x.get("elevation_m"),
                    }
                    for x in ghcn_candidates
                ],
                "suggestions": fuzzy_suggestions(wanted, all_meta_rows),
            }
        )

    return {
        "metadata": metadata,
        "unresolved": unresolved,
        "method_counts": dict(methods),
    }


def known_station_checks(metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    expected = {
        "192": (46.0655, 14.5124, 299.0),
        "097": (45.8956, 13.6240, 55.0),
        "048": (46.3787, 13.8489, 2513.0),
    }
    out = []
    for sid, (elat, elon, eelev) in expected.items():
        meta = metadata.get(sid)
        if not meta:
            out.append({"station_id": sid, "ok": False, "reason": "missing"})
            continue
        lat = float(meta["lat"])
        lon = float(meta["lon"])
        elev = meta.get("elevation_m")
        ok = (
            abs(lat - elat) <= 0.03
            and abs(lon - elon) <= 0.03
            and (elev is None or abs(float(elev) - eelev) <= 60.0)
        )
        out.append(
            {
                "station_id": sid,
                "ok": bool(ok),
                "lat": lat,
                "lon": lon,
                "elevation_m": elev,
                "method": meta.get("match_method"),
            }
        )
    return out


def run(cache_dir: Path) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("=== ARSO SLOWENIEN · STATIONSMETADATEN V6 ===", flush=True)
    print("Primär: offizielle Agromet-Metadaten-CSV 1961-2016 + 2017-heute")
    print("Sekundär: nationaler ARSO-GIS-Layer mit exakter Stations-ID")

    inventory, inventory_source = core.load_inventory()
    current_rows, historical_rows = load_agromet_metadata()
    gis_rows = load_gis_rows()
    ghcn_rows = load_ghcn_stations()

    print(f"Agromet-Inventar: {len(inventory):,}")
    print(f"Current-Metadatenzeilen: {len(current_rows):,}")
    print(f"Historische Metadatenzeilen: {len(historical_rows):,}")
    print(f"Nationale GIS-Zeilen: {len(gis_rows):,}")
    print(f"NOAA GHCN-Stationszeilen: {len(ghcn_rows):,}")

    result = build_metadata(
        inventory,
        current_rows,
        historical_rows,
        gis_rows,
        ghcn_rows,
    )
    checks = known_station_checks(result["metadata"])

    coordinate_count = len(result["metadata"])
    unresolved = result["unresolved"]
    integration_ready = coordinate_count == len(inventory)

    payload = {
        "format_version": FORMAT_VERSION,
        "inventory_source": inventory_source,
        "agromet_current_metadata_source": AGROMET_CURRENT_META,
        "agromet_historical_metadata_source": AGROMET_HIST_META,
        "gis_fallback_source": GIS_LAYER,
        "ghcn_crosswalk_source": GHCN_STATIONS_URL,
        "inventory_count": len(inventory),
        "coordinate_id_count": coordinate_count,
        "unresolved_count": len(unresolved),
        "integration_ready": integration_ready,
        "method_counts": result["method_counts"],
        "metadata": result["metadata"],
        "unresolved": unresolved,
        "known_station_checks": checks,
        "updated_utc": datetime.now(UTC).isoformat(),
    }

    out = metadata_path(cache_dir)
    atomic_json(out, payload)

    status = {
        "complete_probe": True,
        "integration_ready": integration_ready,
        "metadata_file": str(out),
        "inventory_count": len(inventory),
        "coordinate_id_count": coordinate_count,
        "unresolved_count": len(unresolved),
        "unresolved_ids": [x["station_id"] for x in unresolved],
        "method_counts": result["method_counts"],
        "agromet_current_metadata_rows": len(current_rows),
        "agromet_historical_metadata_rows": len(historical_rows),
        "gis_row_count": len(gis_rows),
        "ghcn_station_row_count": len(ghcn_rows),
        "known_station_checks_ok": sum(1 for x in checks if x["ok"]),
        "known_station_checks_total": len(checks),
        "updated_utc": datetime.now(UTC).isoformat(),
    }
    atomic_json(status_path(cache_dir), status)

    print()
    print("=" * 88)
    print("ARSO SLOWENIEN · METADATEN V6 STATUS")
    print("=" * 88)
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print()
    print("Bekannte Stations-Checks:")
    for check in checks:
        print(json.dumps(check, ensure_ascii=False))

    if unresolved:
        print()
        print("UNGEKLÄRTE STATIONEN – NICHT AUTOMATISCH ZUGEORDNET:")
        for item in unresolved:
            print("-" * 88)
            print(
                f"{item['station_id']} | {item['name']} | "
                f"{item.get('start_year')}-{item.get('end_year') or ''}"
            )
            if item["ambiguous_exact_coordinates"]:
                print("  Mehrere exakte Namens-Koordinaten:")
                for x in item["ambiguous_exact_coordinates"]:
                    print("   ", json.dumps(x, ensure_ascii=False))
            print("  Nur Vorschläge, NICHT übernommen:")
            for x in item["suggestions"]:
                print("   ", json.dumps(x, ensure_ascii=False))

    print()
    print(f"Output: {out}")
    if integration_ready:
        print("ARSO-Metadaten: 74/74 – integrationsreif.")
    else:
        print(
            f"ARSO-Metadaten: {coordinate_count}/{len(inventory)} sicher zugeordnet; "
            f"{len(unresolved)} bleiben bewusst offen."
        )
    return 0


def make_ghcn_fixture_line(
    station_id: str,
    lat: float,
    lon: float,
    elev: float,
    name: str,
) -> str:
    # NOAA GHCN fixed-width format fields used by parse_ghcn_stations().
    return (
        f"{station_id:<11} "
        f"{lat:8.4f} "
        f"{lon:9.4f} "
        f"{elev:6.1f} "
        f"{'':2} "
        f"{name:<30}"
    )


def self_test() -> int:
    ghcn_fixture = (
        make_ghcn_fixture_line(
            "SIX00000001", 46.3550, 16.0560, 280.0, "TURSKI VRH"
        )
        + "\n"
    ).encode("utf-8")
    ghcn_rows = parse_ghcn_stations(ghcn_fixture)
    assert len(ghcn_rows) == 1
    crosswalk, candidates = ghcn_crosswalk_for_turski_vrh(ghcn_rows)
    assert crosswalk is not None
    assert crosswalk["ghcn_id"] == "SIX00000001"
    assert len(candidates) == 1

    # CSV parser: semicolon + decimal comma style.
    fixture = (
        "postaja;geo. širina;geo. dolžina;nadmorska višina\n"
        "PODNANOS;45,8045;13,9659;153\n"
        "TROJANE - LIMOVCE;46,1984;14,9113;673\n"
    )
    parsed = parse_agromet_metadata(
        fixture.encode("utf-8"),
        "fixture",
    )
    assert len(parsed) == 2
    assert parsed[0]["name"] == "PODNANOS"
    assert parsed[0]["lat"] == 45.8045
    assert parsed[0]["lon"] == 13.9659
    assert parsed[0]["elevation_m"] == 153.0

    inventory = {
        "816": {
            "name": "Podnanos",
            "start_year": 2017,
            "end_year": None,
        },
        "829": {
            "name": "Trojane - Limovce",
            "start_year": 2017,
            "end_year": None,
        },
        "102": {
            "name": "Slap (Vipava)",
            "start_year": 1961,
            "end_year": 2006,
        },
        "349": {
            "name": "PODGRADJE",
            "start_year": 1961,
            "end_year": 2001,
        },
        "045": {
            "name": "STARA FUŽINA",
            "start_year": 1961,
            "end_year": 2002,
        },
        "346": {
            "name": "Turški Vrh",
            "start_year": 1961,
            "end_year": 2003,
        },
    }

    current_rows = parsed
    historical_rows = [
        {
            "name": "SLAP",
            "norm_name": "slap",
            "lat": 45.85,
            "lon": 13.96,
            "elevation_m": 150.0,
            "source": "hist fixture",
            "raw": [],
        }
    ]
    gis_fixture = [
        {
            "OBJECTID": 99,
            "ST_POSTAJE": 999,
            "IME_POSTAJE": "PODGRADJE",
            "DAT_KON_TIPA": "2001",
            "Z": 272,
            "GEO_SIR": 46.50,
            "GEO_DOL": 16.2333,
        }
    ]
    result = build_metadata(
        inventory,
        current_rows,
        historical_rows,
        gis_fixture,
        ghcn_rows,
    )
    assert len(result["metadata"]) == 6
    assert result["metadata"]["816"]["match_method"] == "agromet_current_exact_name"
    assert result["metadata"]["102"]["match_method"] == "agromet_historical_official_alias"
    assert result["metadata"]["349"]["match_method"] == "gis_exact_name"
    assert result["metadata"]["045"]["match_method"] == "arso_historical_normals"
    assert abs(result["metadata"]["045"]["lat"] - 46.2833333333) < 1e-6
    assert result["metadata"]["346"]["match_method"] == "noaa_ghcn_crosswalk"
    assert result["metadata"]["346"]["matched_ghcn_station_id"] == "SIX00000001"
    assert result["unresolved"] == []

    print("ARSO Slovenia station-metadata v6 self-test OK")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--cache-dir", type=Path, default=CACHE_DIR_DEFAULT)
    args = p.parse_args()

    if args.self_test:
        return self_test()

    return run(args.cache_dir)


if __name__ == "__main__":
    raise SystemExit(main())
