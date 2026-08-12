#!/usr/bin/env python3
"""Stage-3 QC for world GHCN temperature-extreme candidates.

Stage 3 builds on Stage 2 and focuses on:
  * geographic sanity checks for compact countries/territories,
  * source-backed resolution of a small number of high-priority cases,
  * repeated-extreme diagnostics,
  * tie-aware country ranking (equal extreme values share rank 1).

The policy remains conservative: only cases with a direct source-backed
contradiction, or a demonstrable station/country geography mismatch, are
removed. Heuristics only raise review priority.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

WMO_TABLE_DATE = "2025-07-31"
WMO_TABLE_URL = "https://public.wmo.int/sites/default/files/2025-07/Table_Records_25Jul2025.pdf"
NOAA_GHCN_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
NOAA_GHCN_COUNTRIES_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-countries.txt"
BOM_MILDURA_NONSTANDARD_URL = "https://www.bom.gov.au/climate/current/month/vic/archive/200901.summary.shtml"
BOM_ONSLOW_2022_URL = "https://www.bom.gov.au/climate/current/annual/wa/archive/2022.summary.shtml"
BOM_AUS_JAN_2022_URL = "https://www.bom.gov.au/clim_data/IDCKGC1AR0/202201.summary.shtml"

REQUIRED_COLUMNS = {
    "country_code", "country", "metric", "value_c", "date",
    "station_id", "station_name", "latitude", "longitude",
    "stage2_status", "stage2_rank",
}

METRIC_DIRECTION = {
    "tmax_highest": "desc",
    "tmin_highest": "desc",
    "tmin_lowest": "asc",
    "tmax_lowest": "asc",
}

UNRESOLVED_ORDER = {
    "PASS_SOURCE_BACKED": 0,
    "PASS_PRELIMINARY": 0,
    "REVIEW": 1,
    "REVIEW_CRITICAL": 2,
    "REJECT_CONFIRMED": 3,
}

# Generous envelopes for compact countries/territories that occur among the
# Stage-2 review cases. They are deliberately broader than the actual land
# borders. Outside-envelope hits are review flags only, except for the exact
# ICE SKATE B mismatch resolved below.
# Tuple: lat_min, lat_max, lon_min, lon_max. Dateline-crossing boxes are handled
# by lon_min > lon_max.
STRICT_GEO_ENVELOPES: dict[str, tuple[float, float, float, float]] = {
    "IC": (62.0, 68.0, -26.5, -11.0),       # Iceland
    "AQ": (-15.5, -10.0, -172.8, -167.5),  # American Samoa
    "BF": (20.0, 28.0, -81.0, -71.0),      # Bahamas
    "CV": (14.0, 18.0, -26.5, -22.0),      # Cabo Verde
    "FK": (-54.0, -49.5, -62.5, -56.0),    # Falklands
    "FM": (-1.0, 11.0, 134.0, 166.0),      # Micronesia
    "JQ": (15.5, 17.5, -171.0, -168.0),    # Johnston Atoll
    "RM": (3.0, 16.0, 159.0, 174.0),       # Marshall Islands
    "WF": (-16.0, -12.0, 179.0, -175.0),   # Wallis/Futuna, crosses dateline
}


@dataclass(frozen=True)
class Flag:
    status: str
    code: str
    note: str
    source: str = ""
    priority: int = 0
    resolves_inherited_review: bool = False


def _float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return math.nan


def _int(value: object, default: int = 999999) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _same_value(a: float, b: float, tol: float = 0.051) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fieldnames = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - set(fieldnames)
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader), fieldnames


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _lon_in_box(lon: float, lon_min: float, lon_max: float) -> bool:
    if lon_min <= lon_max:
        return lon_min <= lon <= lon_max
    return lon >= lon_min or lon <= lon_max


def _inside_geo_envelope(country_code: str, lat: float, lon: float) -> bool | None:
    box = STRICT_GEO_ENVELOPES.get(country_code)
    if box is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    lat_min, lat_max, lon_min, lon_max = box
    return lat_min <= lat <= lat_max and _lon_in_box(lon, lon_min, lon_max)


def _stage3_flags(row: dict[str, str], value: float) -> list[Flag]:
    flags: list[Flag] = []
    station = (row.get("station_id") or "").strip()
    station_name = (row.get("station_name") or "").strip().upper()
    country = (row.get("country_code") or "").strip()
    metric = (row.get("metric") or "").strip()
    obs_date = (row.get("date") or "").strip()
    lat = _float(row.get("latitude"))
    lon = _float(row.get("longitude"))
    ties = _int(row.get("tie_count"), 0)

    # Basic coordinate integrity.
    if not (math.isfinite(lat) and math.isfinite(lon)):
        flags.append(Flag(
            "REVIEW_CRITICAL", "MISSING_OR_INVALID_COORDINATES",
            "Candidate has missing/non-numeric coordinates; geographic verification is impossible.",
            NOAA_GHCN_STATIONS_URL, priority=80,
        ))
    elif not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        flags.append(Flag(
            "REJECT_CONFIRMED", "COORDINATES_OUTSIDE_EARTH_RANGE",
            "Latitude/longitude are outside valid Earth coordinate ranges.",
            NOAA_GHCN_STATIONS_URL, priority=100,
        ))

    # Compact-country/territory envelope sanity check. This is only a review
    # flag unless we have the exact, demonstrable ICE SKATE B mismatch below.
    inside = _inside_geo_envelope(country, lat, lon)
    if inside is False:
        flags.append(Flag(
            "REVIEW_CRITICAL", "COUNTRY_COORDINATE_ENVELOPE_MISMATCH",
            f"Station coordinates ({lat:.4f}, {lon:.4f}) lie far outside the deliberately generous Stage-3 envelope for GHCN country code {country}.",
            f"{NOAA_GHCN_STATIONS_URL} | {NOAA_GHCN_COUNTRIES_URL}", priority=85,
        ))

    # ICE SKATE B is coded as Iceland in the candidate table but the GHCN
    # metadata coordinates are 80 N, 113 W — thousands of kilometres outside
    # Iceland. It must not participate in Iceland country ranking.
    if station == "ICW00091004" and country == "IC" and math.isfinite(lat) and math.isfinite(lon):
        if lat >= 75.0 and lon <= -80.0:
            flags.append(Flag(
                "REJECT_CONFIRMED", "ICE_SKATE_B_NOT_GEOGRAPHIC_ICELAND",
                "ICE SKATE B is carried with GHCN country code IC, but its station coordinates (~80 N, 113 W) are outside Iceland; exclude it from Iceland country-extreme ranking.",
                f"{NOAA_GHCN_STATIONS_URL} | {NOAA_GHCN_COUNTRIES_URL}", priority=100,
            ))

    # Mildura Post Office 50.7 C (7 Jan 1906): BOM explicitly notes this heat
    # sequence was observed in a non-standard screen. For a source-backed,
    # comparable record baseline, do not retain it as a verified Australian
    # extreme candidate.
    if station == "ASN00076077" and metric == "tmax_highest" and obs_date == "1906-01-07" and _same_value(value, 50.7):
        flags.append(Flag(
            "REJECT_CONFIRMED", "BOM_MILDURA_1906_NONSTANDARD_SCREEN",
            "BOM states the January 1906 Mildura Post Office heat sequence, including 50.7 °C on 7 Jan, was recorded in a non-standard screen; exclude from the comparable verified-record baseline.",
            BOM_MILDURA_NONSTANDARD_URL, priority=100,
        ))

    # Oodnadatta: WMO-recognized Southern Hemisphere high.
    if metric == "tmax_highest" and obs_date == "1960-01-02" and _same_value(value, 50.7) and "OODNADATTA" in station_name:
        flags.append(Flag(
            "PASS_SOURCE_BACKED", "WMO_OODNADATTA_50_7_VERIFIED",
            "50.7 °C at Oodnadatta on 2 Jan 1960 is the WMO-recognized Southern Hemisphere high.",
            WMO_TABLE_URL, priority=0, resolves_inherited_review=True,
        ))

    # Onslow Airport: BOM explicitly recognizes 50.7 C on 13 Jan 2022 as equal
    # to Australia's all-time highest temperature. Resolve the inherited WMO-
    # tie review flag as source-backed rather than leaving it critical.
    if station == "ASN00005017" and metric == "tmax_highest" and obs_date == "2022-01-13" and _same_value(value, 50.7):
        flags.append(Flag(
            "PASS_SOURCE_BACKED", "BOM_ONSLOW_2022_AU_RECORD_TIE_VERIFIED",
            "BOM reports 50.7 °C at Onslow Airport on 13 Jan 2022 as equal to the all-time highest temperature in Australia.",
            f"{BOM_ONSLOW_2022_URL} | {BOM_AUS_JAN_2022_URL}", priority=0, resolves_inherited_review=True,
        ))

    # Turkmenistan 56.5 C conflicts with WMO's published Eastern-Hemisphere
    # high. The WMO table itself notes that some potential records may be under
    # evaluation, so this remains REVIEW_CRITICAL rather than an automatic
    # rejection until a station/date-specific authoritative source resolves it.
    if country == "TX" and metric == "tmax_highest" and value > 55.05:
        flags.append(Flag(
            "REVIEW_CRITICAL", "ABOVE_WMO_EASTERN_HEMISPHERE_RECORD_UNVERIFIED",
            "Candidate exceeds the WMO-published Eastern Hemisphere high of 55.0 °C; keep as critical review because the WMO table is not an exhaustive rejection list for every unevaluated historical observation.",
            WMO_TABLE_URL, priority=95,
        ))

    # Repeated exact station extremes across long periods are a strong data-
    # pipeline smell. This is diagnostic only, never an automatic rejection.
    first = _parse_date(row.get("first_date"))
    last = _parse_date(row.get("last_date"))
    span_days = (last - first).days if first and last else 0
    if ties >= 10 and span_days >= 30:
        priority = 90 if ties >= 30 or span_days >= 365 else 70
        flags.append(Flag(
            "REVIEW_CRITICAL" if priority >= 85 else "REVIEW",
            "REPEATED_EXACT_EXTREME_LONG_SPAN",
            f"The same station extreme is reported {ties} times over {span_days} days ({row.get('first_date')} to {row.get('last_date')}); verify possible repeated/default/encoded values.",
            NOAA_GHCN_STATIONS_URL, priority=priority,
        ))

    # Daily TMIN above the WMO/Quriyat context remains a critical category, but
    # Stage 3 does not auto-reject because observation windows can differ.
    if metric == "tmin_highest" and value >= 42.6:
        flags.append(Flag(
            "REVIEW_CRITICAL", "ULTRA_HIGH_DAILY_MINIMUM",
            "Daily minimum is at/above the exceptional 42.6 °C class; retain only with station/date-specific authoritative verification.",
            WMO_TABLE_URL, priority=90,
        ))

    return flags


def _resolve_status(inherited: str, flags: Iterable[Flag]) -> str:
    flags = list(flags)
    if any(f.status == "REJECT_CONFIRMED" for f in flags):
        return "REJECT_CONFIRMED"

    inherited = inherited if inherited in UNRESOLVED_ORDER else "PASS_PRELIMINARY"
    new_review = [f for f in flags if f.status in {"REVIEW", "REVIEW_CRITICAL"}]
    passes = [f for f in flags if f.status == "PASS_SOURCE_BACKED" and f.resolves_inherited_review]

    # A source-backed resolver may clear an inherited REVIEW/REVIEW_CRITICAL
    # only when Stage 3 has not raised a new independent review flag.
    if passes and not new_review:
        return "PASS_SOURCE_BACKED"

    candidates = [inherited] + [f.status for f in new_review]
    return max(candidates, key=lambda s: UNRESOLVED_ORDER.get(s, 0))


def _priority_score(row: dict[str, object]) -> int:
    status = str(row.get("stage3_status", ""))
    base = {
        "REJECT_CONFIRMED": 1000,
        "REVIEW_CRITICAL": 700,
        "REVIEW": 400,
        "PASS_PRELIMINARY": 100,
        "PASS_SOURCE_BACKED": 0,
    }.get(status, 200)
    try:
        extra = int(row.get("stage3_flag_priority") or 0)
    except (TypeError, ValueError):
        extra = 0
    return base + extra


def _rerank_tie_aware(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get("stage3_status") == "REJECT_CONFIRMED":
            continue
        groups[(str(row.get("country_code", "")), str(row.get("metric", "")))].append(dict(row))

    out: list[dict[str, object]] = []
    for key in sorted(groups):
        metric = key[1]
        reverse = METRIC_DIRECTION.get(metric, "desc") == "desc"
        group = groups[key]
        group.sort(key=lambda r: (
            -_float(r.get("value_c")) if reverse else _float(r.get("value_c")),
            str(r.get("date", "")), str(r.get("station_id", "")),
        ))

        distinct_rank = 0
        previous_value: float | None = None
        for row in group:
            v = _float(row.get("value_c"))
            if previous_value is None or not _same_value(v, previous_value):
                distinct_rank += 1
                previous_value = v
            row["stage3_rank"] = distinct_rank
            row["stage3_is_country_extreme"] = "yes" if distinct_rank == 1 else "no"
            out.append(row)
    return out


def _render_report(annotated: list[dict[str, object]], clean: list[dict[str, object]], rank1: list[dict[str, object]]) -> str:
    counts = Counter(str(r.get("stage3_status")) for r in annotated)
    rejected = [r for r in annotated if r.get("stage3_status") == "REJECT_CONFIRMED"]
    verified = [r for r in annotated if r.get("stage3_status") == "PASS_SOURCE_BACKED"]
    review_rank1 = [r for r in rank1 if r.get("stage3_status") in {"REVIEW", "REVIEW_CRITICAL"}]
    geo = [r for r in annotated if "COUNTRY_COORDINATE_ENVELOPE_MISMATCH" in str(r.get("stage3_flags", ""))]
    repeats = [r for r in annotated if "REPEATED_EXACT_EXTREME_LONG_SPAN" in str(r.get("stage3_flags", ""))]

    lines = [
        "# World GHCN candidate QC · Stage 3",
        "",
        "Stage 3 ergänzt geografische Plausibilität, source-backed Auflösung einzelner Prioritätsfälle und tie-aware Ranking.",
        "Automatische Ausschlüsse bleiben auf direkt belegte Widersprüche bzw. demonstrierbare Country/Coordinate-Mismatches begrenzt.",
        "",
        "## Ergebnis",
        f"- Eingangszeilen aus Stage 2: {len(annotated):,}",
    ]
    for status in ("REJECT_CONFIRMED", "PASS_SOURCE_BACKED", "REVIEW_CRITICAL", "REVIEW", "PASS_PRELIMINARY"):
        lines.append(f"- {status}: {counts.get(status, 0):,}")
    lines += [
        f"- Stage-3-Clean-Zeilen: {len(clean):,}",
        f"- Country-extreme-Zeilen (inkl. echte Gleichstände): {len(rank1):,}",
        f"- Geografie-Flags: {len(geo):,}",
        f"- Repeat-Extreme-Flags: {len(repeats):,}",
        "",
        "## Stage-3 bestätigt ausgeschlossen",
    ]
    if rejected:
        for r in rejected:
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('stage3_flags')}"
            )
    else:
        lines.append("Keine.")

    lines += ["", "## Source-backed aufgelöst / bestätigt"]
    if verified:
        for r in verified:
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('stage3_flags')}"
            )
    else:
        lines.append("Keine.")

    lines += ["", "## Verbleibende Country-Rank-1-Prüffälle"]
    review_rank1.sort(key=lambda r: (-_priority_score(r), str(r.get("country_code")), str(r.get("metric"))))
    for r in review_rank1[:120]:
        lines.append(
            f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
            f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | "
            f"{r.get('stage3_status')} | score={r.get('stage3_priority_score')}"
        )
    if len(review_rank1) > 120:
        lines.append(f"- … weitere {len(review_rank1)-120:,} Fälle in `review_priority_rank1_stage3.csv`.")

    lines += [
        "",
        "## Ranking-Änderung",
        "Stage 3 verwendet Rang nach **distinct temperature value**. Gleich hohe/gleich tiefe Landesextreme teilen sich Rang 1.",
        "Dadurch kann z. B. nach Ausschluss eines nicht vergleichbaren Altwerts mehr als eine gültige Station denselben Landes-Rang 1 tragen.",
        "",
        "## Referenzen",
        f"- WMO Records of Weather and Climate Extremes, {WMO_TABLE_DATE}: {WMO_TABLE_URL}",
        f"- NOAA/NCEI GHCN station metadata: {NOAA_GHCN_STATIONS_URL}",
        f"- NOAA/NCEI GHCN country-code list: {NOAA_GHCN_COUNTRIES_URL}",
        f"- BOM on Mildura 1906 non-standard screen: {BOM_MILDURA_NONSTANDARD_URL}",
        f"- BOM Western Australia 2022 / Onslow 50.7 °C: {BOM_ONSLOW_2022_URL}",
        f"- BOM Australia January 2022 / Onslow record tie: {BOM_AUS_JAN_2022_URL}",
        "",
        "## Nächster Schritt",
        "Nach Stage 3 prüfen wir nur noch die verbleibenden **Country-Rank-1**-Zeilen mit REVIEW/REVIEW_CRITICAL. Noch keine 2026-Integration.",
        "",
    ]
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    rows, input_fields = _read_rows(input_path)
    annotated: list[dict[str, object]] = []

    for raw in rows:
        row: dict[str, object] = dict(raw)
        value = _float(raw.get("value_c"))
        flags: list[Flag] = []
        if not math.isfinite(value):
            flags.append(Flag("REVIEW_CRITICAL", "NON_NUMERIC_VALUE", "value_c is not numeric.", priority=100))
        else:
            flags.extend(_stage3_flags(raw, value))

        inherited = (raw.get("stage2_status") or "PASS_PRELIMINARY").strip()
        status = _resolve_status(inherited, flags)
        priority = max((f.priority for f in flags), default=0)

        row["stage3_status"] = status
        row["stage3_flags"] = "|".join(dict.fromkeys(f.code for f in flags))
        row["stage3_notes"] = " || ".join(dict.fromkeys(f.note for f in flags))
        row["stage3_sources"] = " || ".join(dict.fromkeys(f.source for f in flags if f.source))
        row["stage3_flag_priority"] = priority
        row["stage3_priority_score"] = ""
        row["stage3_rank"] = ""
        row["stage3_is_country_extreme"] = ""
        annotated.append(row)

    for row in annotated:
        row["stage3_priority_score"] = _priority_score(row)

    clean = _rerank_tie_aware(annotated)
    rank1 = [dict(r) for r in clean if _int(r.get("stage3_rank")) == 1]

    # Sort review outputs by importance, then country/metric/value.
    review_all = [dict(r) for r in annotated if r["stage3_status"] in {"REVIEW", "REVIEW_CRITICAL"}]
    review_all.sort(key=lambda r: (-_priority_score(r), str(r.get("country_code")), str(r.get("metric")), _int(r.get("stage2_rank"))))

    review_rank1 = [dict(r) for r in rank1 if r["stage3_status"] in {"REVIEW", "REVIEW_CRITICAL"}]
    review_rank1.sort(key=lambda r: (-_priority_score(r), str(r.get("country_code")), str(r.get("metric")), str(r.get("date"))))

    extra_fields = [
        "stage3_status", "stage3_flags", "stage3_notes", "stage3_sources",
        "stage3_flag_priority", "stage3_priority_score", "stage3_rank",
        "stage3_is_country_extreme",
    ]
    output_fields = input_fields + [f for f in extra_fields if f not in input_fields]
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(output_dir / "world_country_extreme_candidates_stage3_annotated.csv", annotated, output_fields)
    _write_csv(output_dir / "world_country_extreme_candidates_stage3_clean.csv", clean, output_fields)
    _write_csv(output_dir / "world_country_rank1_stage3.csv", rank1, output_fields)
    _write_csv(output_dir / "rejected_confirmed_stage3.csv", [r for r in annotated if r["stage3_status"] == "REJECT_CONFIRMED"], output_fields)
    _write_csv(output_dir / "source_backed_stage3.csv", [r for r in annotated if r["stage3_status"] == "PASS_SOURCE_BACKED"], output_fields)
    _write_csv(output_dir / "review_priority_stage3.csv", review_all, output_fields)
    _write_csv(output_dir / "review_priority_rank1_stage3.csv", review_rank1, output_fields)
    _write_csv(output_dir / "geography_flags_stage3.csv", [r for r in annotated if "COUNTRY_COORDINATE_ENVELOPE_MISMATCH" in str(r.get("stage3_flags", ""))], output_fields)
    _write_csv(output_dir / "repeated_extremes_stage3.csv", [r for r in annotated if "REPEATED_EXACT_EXTREME_LONG_SPAN" in str(r.get("stage3_flags", ""))], output_fields)

    summary = {
        "schema_version": 1,
        "stage": "world_ghcn_candidate_qc_stage3",
        "input_rows": len(annotated),
        "status_counts": dict(Counter(str(r["stage3_status"]) for r in annotated)),
        "stage3_clean_rows": len(clean),
        "stage3_country_extreme_rows_including_ties": len(rank1),
        "confirmed_rejected_rows_stage3": sum(r["stage3_status"] == "REJECT_CONFIRMED" for r in annotated),
        "source_backed_rows_stage3": sum(r["stage3_status"] == "PASS_SOURCE_BACKED" for r in annotated),
        "geography_flagged_rows": sum("COUNTRY_COORDINATE_ENVELOPE_MISMATCH" in str(r.get("stage3_flags", "")) for r in annotated),
        "repeated_extreme_flagged_rows": sum("REPEATED_EXACT_EXTREME_LONG_SPAN" in str(r.get("stage3_flags", "")) for r in annotated),
        "rank1_review_rows": len(review_rank1),
        "ranking_policy": "Tie-aware ranking by distinct extreme value; equal country-extreme values share rank 1.",
        "qc_policy": "Reject only direct authoritative contradictions or demonstrable country/coordinate mismatch; heuristics remain review-only.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "qc_report.md").write_text(_render_report(annotated, clean, rank1), encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "rank", "value_c", "date", "first_date", "last_date", "tie_count",
        "station_id", "station_name", "latitude", "longitude", "stage2_status", "stage2_rank",
    ]
    sample = [
        # exact geographic mismatch: must reject
        {"country_code":"IC","country":"Iceland","metric":"tmax_lowest","rank":"1","value_c":"-36.1","date":"1961-02-28","first_date":"1961-02-28","last_date":"1961-02-28","tie_count":"1","station_id":"ICW00091004","station_name":"ICE SKATE B","latitude":"80.0","longitude":"-113.0","stage2_status":"REVIEW_CRITICAL","stage2_rank":"1"},
        # Mildura non-standard screen: reject
        {"country_code":"AS","country":"Australia","metric":"tmax_highest","rank":"1","value_c":"50.7","date":"1906-01-07","first_date":"1906-01-07","last_date":"1906-01-07","tie_count":"1","station_id":"ASN00076077","station_name":"MILDURA POST OFFICE","latitude":"-34.18","longitude":"142.2","stage2_status":"REVIEW_CRITICAL","stage2_rank":"1"},
        # WMO/BOM valid ties should both become country rank 1 after Mildura removal
        {"country_code":"AS","country":"Australia","metric":"tmax_highest","rank":"2","value_c":"50.7","date":"1960-01-02","first_date":"1960-01-02","last_date":"1960-01-02","tie_count":"1","station_id":"ASN00016000","station_name":"OODNADATTA AIRPORT","latitude":"-27.55","longitude":"135.45","stage2_status":"PASS_PRELIMINARY","stage2_rank":"2"},
        {"country_code":"AS","country":"Australia","metric":"tmax_highest","rank":"3","value_c":"50.7","date":"2022-01-13","first_date":"2022-01-13","last_date":"2022-01-13","tie_count":"1","station_id":"ASN00005017","station_name":"ONSLOW AIRPORT","latitude":"-21.67","longitude":"115.11","stage2_status":"REVIEW_CRITICAL","stage2_rank":"3"},
        # WMO conflict: remain critical review
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","rank":"1","value_c":"56.5","date":"1890-06-20","first_date":"1890-06-20","last_date":"1890-06-20","tie_count":"1","station_id":"TX000038895","station_name":"BAJRAMALY","latitude":"37.6","longitude":"62.18","stage2_status":"REVIEW_CRITICAL","stage2_rank":"1"},
        # repeated Fiji extreme: review only
        {"country_code":"FJ","country":"Fiji","metric":"tmax_highest","rank":"1","value_c":"39.0","date":"1979-01-04","first_date":"1979-01-04","last_date":"1981-12-25","tie_count":"80","station_id":"FJM00091699","station_name":"ONO-I-LAU","latitude":"-20.66","longitude":"-178.72","stage2_status":"REVIEW","stage2_rank":"1"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader(); writer.writerows(sample)
        out = root / "out"
        summary = run(src, out)

        with (out / "world_country_extreme_candidates_stage3_annotated.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            ann = list(csv.DictReader(handle, delimiter=";"))
        by_station = {r["station_id"]: r for r in ann}
        assert by_station["ICW00091004"]["stage3_status"] == "REJECT_CONFIRMED"
        assert "ICE_SKATE_B_NOT_GEOGRAPHIC_ICELAND" in by_station["ICW00091004"]["stage3_flags"]
        assert by_station["ASN00076077"]["stage3_status"] == "REJECT_CONFIRMED"
        assert by_station["ASN00005017"]["stage3_status"] == "PASS_SOURCE_BACKED"
        assert by_station["TX000038895"]["stage3_status"] == "REVIEW_CRITICAL"
        assert "ABOVE_WMO_EASTERN_HEMISPHERE_RECORD_UNVERIFIED" in by_station["TX000038895"]["stage3_flags"]
        assert "REPEATED_EXACT_EXTREME_LONG_SPAN" in by_station["FJM00091699"]["stage3_flags"]

        with (out / "world_country_rank1_stage3.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rank1 = list(csv.DictReader(handle, delimiter=";"))
        aus = [r for r in rank1 if r["country_code"] == "AS" and r["metric"] == "tmax_highest"]
        assert {r["station_id"] for r in aus} == {"ASN00016000", "ASN00005017"}
        assert all(r["stage3_rank"] == "1" for r in aus)
        assert summary["confirmed_rejected_rows_stage3"] == 2
        assert summary["source_backed_rows_stage3"] == 2
        assert (out / "review_priority_rank1_stage3.csv").exists()

    print("SELF-TEST OK")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test and (args.input is None or args.output_dir is None):
        parser.error("--input and --output-dir are required unless --self-test is used")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        self_test(); return 0
    summary = run(args.input, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
