#!/usr/bin/env python3
"""Stage-4 QC for world GHCN country temperature-extreme candidates.

Stage 4 separates two questions that must not be conflated:

1) Is a GHCN candidate observation itself usable?
2) Does the GHCN candidate pool actually contain the authoritative country record?

The second question matters because a technically clean GHCN country rank 1 can
still be less extreme than an official WMO / national-meteorological-service
record that is absent from the GHCN top-candidate pool.

Policy:
  * direct authoritative contradiction of the SAME event may be rejected;
  * exact authoritative event matches may be promoted to PASS_SOURCE_BACKED;
  * missing official country records are reported as COVERAGE GAPS, not as bad
    observations;
  * a GHCN country candidate more extreme than an authoritative country anchor
    remains REVIEW_CRITICAL unless a same-event contradiction proves it wrong;
  * the suspicious 1979-1981 Pacific 39.0 C repeated-value pattern remains a
    review diagnostic only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WMO_TABLE_DATE = "2025-07-31"
WMO_TABLE_URL = "https://public.wmo.int/sites/default/files/2025-07/Table_Records_25Jul2025.pdf"
IMO_ICELAND_URL = "https://en.vedur.is/about-imo/news/the-most-significant-may-heatwave-ever-recorded-in-iceland"
NIWA_EXTREMES_URL = "https://niwa.co.nz/climate-and-weather/climate-extremes"
NIWA_RANFURLY_URL = "https://niwa.co.nz/news/global-experts-confirm-niwas-finding-southwest-pacifics-coldest-ever-temperature"
SAWS_EXTREMES_URL = "https://www.weathersa.co.za/home/climateques"
MET_EIREANN_EXTREMES_URL = "https://www.met.ie/climate/weather-extreme-records"
NOAA_GHCN_README_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt"

REQUIRED_COLUMNS = {
    "country_code", "country", "metric", "value_c", "date",
    "station_id", "station_name", "stage3_status", "stage3_rank",
}

METRIC_DIRECTION = {
    "tmax_highest": "desc",
    "tmin_highest": "desc",
    "tmin_lowest": "asc",
    "tmax_lowest": "asc",
}

STATUS_ORDER = {
    "PASS_SOURCE_BACKED": 0,
    "PASS_PRELIMINARY": 0,
    "REVIEW": 1,
    "REVIEW_CRITICAL": 2,
    "REJECT_CONFIRMED": 3,
}


@dataclass(frozen=True)
class Anchor:
    anchor_id: str
    country_code: str
    country: str
    metric: str
    value_c: float
    date: str
    site: str
    source: str
    kind: str = "country_record"  # country_record | verified_event
    site_keywords: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Flag:
    status: str
    code: str
    note: str
    source: str = ""
    priority: int = 0
    resolves_inherited_review: bool = False


# Curated authoritative anchors through 2025 only. The WMO table is an
# explicit 31-Jul-2025 snapshot. National-service anchors are historical
# all-time records with event dates <= 2025.
ANCHORS: tuple[Anchor, ...] = (
    Anchor(
        "WMO_US_TMAX_1913", "US", "United States", "tmax_highest", 56.7,
        "1913-07-10", "Furnace Creek (Greenland Ranch), California",
        WMO_TABLE_URL, site_keywords=("GREENLAND", "FURNACE"),
        note="WMO world and North-America highest temperature.",
    ),
    Anchor(
        "WMO_AY_TMIN_1983", "AY", "Antarctica", "tmin_lowest", -89.2,
        "1983-07-21", "Vostok, Antarctica", WMO_TABLE_URL,
        site_keywords=("VOSTOK",), note="WMO world lowest temperature.",
    ),
    Anchor(
        "WMO_AS_TMAX_1960", "AS", "Australia", "tmax_highest", 50.7,
        "1960-01-02", "Oodnadatta, Australia", WMO_TABLE_URL,
        site_keywords=("OODNADATTA",), note="WMO Southern-Hemisphere / SW-Pacific high.",
    ),
    Anchor(
        "WMO_TS_TMAX_1931", "TS", "Tunisia", "tmax_highest", 55.0,
        "1931-07-07", "Kebili, Tunisia", WMO_TABLE_URL,
        site_keywords=("KEBILI",), note="WMO Eastern-Hemisphere and Africa high.",
    ),
    Anchor(
        "WMO_KU_TMAX_2016", "KU", "Kuwait", "tmax_highest", 53.9,
        "2016-07-21", "Mitribah, Kuwait", WMO_TABLE_URL,
        site_keywords=("MITRIBAH",), note="WMO verified Asia high.",
    ),
    Anchor(
        "WMO_IS_TMAX_1942", "IS", "Israel", "tmax_highest", 54.0,
        "1942-06-21", "Tirat Tsvi (Tirat Zevi), Israel", WMO_TABLE_URL,
        site_keywords=("TIRAT", "TSVI", "ZEVI"), note="WMO Region VI high including Middle East.",
    ),
    Anchor(
        "WMO_IT_TMAX_2021", "IT", "Italy", "tmax_highest", 48.8,
        "2021-08-11", "Siracusa, Sicilia, Italy", WMO_TABLE_URL,
        site_keywords=("SIRACUSA", "SYRACUSE"), note="WMO continental-Europe high.",
    ),
    Anchor(
        "WMO_NZ_TMIN_1903", "NZ", "New Zealand", "tmin_lowest", -25.6,
        "1903-07-17", "Ranfurly / Eweburn, New Zealand", WMO_TABLE_URL,
        site_keywords=("RANFURLY", "EWEBURN"), note="WMO South-West-Pacific low.",
    ),
    Anchor(
        "NIWA_NZ_TMAX_1973", "NZ", "New Zealand", "tmax_highest", 42.4,
        "1973-02-07", "Rangiora / Jordan, New Zealand", NIWA_EXTREMES_URL,
        site_keywords=("RANGIORA", "JORDAN"), note="NIWA national highest air temperature.",
    ),
    Anchor(
        "WMO_CA_TMIN_1947", "CA", "Canada", "tmin_lowest", -63.0,
        "1947-02-03", "Snag, Yukon, Canada", WMO_TABLE_URL,
        site_keywords=("SNAG",), note="WMO North-America low.",
    ),
    Anchor(
        "WMO_GL_TMIN_1991", "GL", "Greenland [Denmark]", "tmin_lowest", -69.6,
        "1991-12-22", "Klinck AWS, Greenland", WMO_TABLE_URL,
        site_keywords=("KLINCK",), note="WMO Northern-Hemisphere low.",
    ),
    Anchor(
        "WMO_RS_TMIN", "RS", "Russia", "tmin_lowest", -67.8,
        "", "Verkhoyansk / Oymyakon, Russian Federation", WMO_TABLE_URL,
        site_keywords=("VERHO", "VERKHO", "OIMY", "OJMY"),
        note="WMO Asia low (equal record events in Russia).",
    ),
    Anchor(
        "WMO_AR_TMAX_1905", "AR", "Argentina", "tmax_highest", 48.9,
        "1905-12-11", "Rivadavia, Argentina", WMO_TABLE_URL,
        site_keywords=("RIVADAVIA",), note="WMO South-America high.",
    ),
    Anchor(
        "WMO_AR_TMIN_1907", "AR", "Argentina", "tmin_lowest", -32.8,
        "1907-06-01", "Sarmiento, Argentina", WMO_TABLE_URL,
        site_keywords=("SARMIENTO",), note="WMO South-America low.",
    ),
    Anchor(
        "WMO_MO_TMIN_1935", "MO", "Morocco", "tmin_lowest", -23.9,
        "1935-02-11", "Ifrane, Morocco", WMO_TABLE_URL,
        site_keywords=("IFRANE",), note="WMO Africa low.",
    ),
    Anchor(
        "IMO_IC_TMAX_1939", "IC", "Iceland", "tmax_highest", 30.5,
        "1939-06-22", "Teigarhorn, Iceland", IMO_ICELAND_URL,
        site_keywords=("TEIGARHORN",), note="Icelandic Met Office national all-time maximum.",
    ),
    Anchor(
        "SAWS_SF_TMAX_1918", "SF", "South Africa", "tmax_highest", 50.0,
        "1918-11-03", "Dunbrody, South Africa", SAWS_EXTREMES_URL,
        site_keywords=("DUNBRODY",), note="SAWS national highest temperature.",
    ),
    Anchor(
        "SAWS_SF_TMIN_2013", "SF", "South Africa", "tmin_lowest", -20.1,
        "2013-08-23", "Buffelsfontein near Molteno, South Africa", SAWS_EXTREMES_URL,
        site_keywords=("BUFFELSFONTEIN",), note="SAWS national lowest temperature.",
    ),
    Anchor(
        "MET_EIREANN_EI_TMAX_1887", "EI", "Ireland", "tmax_highest", 33.3,
        "1887-06-26", "Kilkenny Castle, Ireland", MET_EIREANN_EXTREMES_URL,
        site_keywords=("KILKENNY",), note="Met Eireann historical national highest shaded-air temperature.",
    ),
    Anchor(
        "MET_EIREANN_EI_TMIN_1881", "EI", "Ireland", "tmin_lowest", -19.1,
        "1881-01-16", "Markree, Ireland", MET_EIREANN_EXTREMES_URL,
        site_keywords=("MARKREE",), note="Met Eireann national lowest shaded-air temperature.",
    ),
    # WMO-verified event, but not used here as a hard Pakistan country-record
    # ceiling. It can source-back the exact Turbat observation if present.
    Anchor(
        "WMO_PK_TURBAT_2017_EVENT", "PK", "Pakistan", "tmax_highest", 53.7,
        "2017-05-28", "Turbat, Pakistan", WMO_TABLE_URL,
        kind="verified_event", site_keywords=("TURBAT",),
        note="WMO-verified 53.7 C Turbat event; event anchor only, not a national-record ceiling in Stage 4.",
    ),
)


COUNTRY_RECORD_ANCHORS = tuple(a for a in ANCHORS if a.kind == "country_record")
VERIFIED_EVENT_ANCHORS = tuple(a for a in ANCHORS if a.kind == "verified_event")
ANCHORS_BY_GROUP: dict[tuple[str, str], list[Anchor]] = defaultdict(list)
for _a in COUNTRY_RECORD_ANCHORS:
    ANCHORS_BY_GROUP[(_a.country_code, _a.metric)].append(_a)


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


def _same_value(a: float, b: float, tol: float = 0.051) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _norm(text: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper()).strip()


def _site_matches(row: dict[str, object], anchor: Anchor) -> bool:
    if not anchor.site_keywords:
        return True
    haystack = _norm(f"{row.get('station_name','')} {row.get('station_id','')}")
    return any(_norm(k) in haystack for k in anchor.site_keywords)


def _event_matches(row: dict[str, object], anchor: Anchor, require_value: bool = True) -> bool:
    if str(row.get("country_code", "")).strip() != anchor.country_code:
        return False
    if str(row.get("metric", "")).strip() != anchor.metric:
        return False
    if anchor.date and str(row.get("date", "")).strip() != anchor.date:
        return False
    if not _site_matches(row, anchor):
        return False
    if require_value and not _same_value(_float(row.get("value_c")), anchor.value_c):
        return False
    return True


def _more_extreme(metric: str, candidate: float, reference: float) -> bool:
    if METRIC_DIRECTION.get(metric) == "desc":
        return candidate > reference + 0.051
    return candidate < reference - 0.051


def _less_extreme(metric: str, candidate: float, reference: float) -> bool:
    if METRIC_DIRECTION.get(metric) == "desc":
        return candidate < reference - 0.051
    return candidate > reference + 0.051


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fields = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - set(fields)
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader), fields


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_status(inherited: str, flags: Iterable[Flag]) -> str:
    flags = list(flags)
    if any(f.status == "REJECT_CONFIRMED" for f in flags):
        return "REJECT_CONFIRMED"

    inherited = inherited if inherited in STATUS_ORDER else "PASS_PRELIMINARY"
    reviews = [f for f in flags if f.status in {"REVIEW", "REVIEW_CRITICAL"}]
    resolvers = [f for f in flags if f.status == "PASS_SOURCE_BACKED" and f.resolves_inherited_review]

    if resolvers and not reviews:
        return "PASS_SOURCE_BACKED"
    candidates = [inherited] + [f.status for f in reviews]
    return max(candidates, key=lambda s: STATUS_ORDER.get(s, 0))


def _rerank(rows: list[dict[str, object]], status_field: str = "stage4_status") -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get(status_field) == "REJECT_CONFIRMED":
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
        rank = 0
        prev: float | None = None
        for row in group:
            v = _float(row.get("value_c"))
            if prev is None or not _same_value(v, prev):
                rank += 1
                prev = v
            row["stage4_rank"] = rank
            row["stage4_is_country_extreme"] = "yes" if rank == 1 else "no"
            out.append(row)
    return out


def _initial_flags(row: dict[str, str]) -> list[Flag]:
    flags: list[Flag] = []
    value = _float(row.get("value_c"))
    country = (row.get("country_code") or "").strip()
    metric = (row.get("metric") or "").strip()
    date_s = (row.get("date") or "").strip()
    station = _norm(row.get("station_name"))

    if not math.isfinite(value):
        return [Flag("REVIEW_CRITICAL", "NON_NUMERIC_VALUE", "value_c is not numeric.", priority=100)]

    # Exact authoritative event matches, and same-event value contradictions.
    for anchor in ANCHORS:
        if country != anchor.country_code or metric != anchor.metric:
            continue
        if not anchor.date or date_s != anchor.date or not _site_matches(row, anchor):
            continue
        if _same_value(value, anchor.value_c):
            flags.append(Flag(
                "PASS_SOURCE_BACKED", f"OFFICIAL_EVENT_MATCH__{anchor.anchor_id}",
                f"Candidate matches authoritative event {anchor.site}, {anchor.date}, {anchor.value_c:.1f} °C.",
                anchor.source, priority=0, resolves_inherited_review=True,
            ))
        else:
            flags.append(Flag(
                "REJECT_CONFIRMED", f"OFFICIAL_SAME_EVENT_VALUE_CONFLICT__{anchor.anchor_id}",
                f"Same authoritative event is {anchor.value_c:.1f} °C, but GHCN candidate carries {value:.1f} °C; reject the conflicting GHCN value for country-record use.",
                anchor.source, priority=100,
            ))

    # Cross-country Pacific legacy pattern. Diagnostic only: the same 39.0 C
    # ceiling-like value repeats many times at multiple islands/stations across
    # 1979-1981. This is deliberately not an automatic rejection.
    ties = _int(row.get("tie_count"), 0)
    first_date = str(row.get("first_date") or "")
    last_date = str(row.get("last_date") or "")
    if (
        country in {"FJ", "TL", "TN"}
        and metric == "tmax_highest"
        and _same_value(value, 39.0)
        and ties >= 10
        and (first_date.startswith("1979") or first_date.startswith("1980") or first_date.startswith("1981"))
        and (last_date.startswith("1979") or last_date.startswith("1980") or last_date.startswith("1981"))
    ):
        flags.append(Flag(
            "REVIEW_CRITICAL", "PACIFIC_1979_1981_REPEATED_39C_CLUSTER",
            "Candidate belongs to the cross-country Fiji/Tokelau/Tonga pattern of repeatedly reported exact 39.0 °C station extremes during 1979-1981; retain for targeted source verification, not automatic rejection.",
            NOAA_GHCN_README_URL, priority=98,
        ))

    # Preserve the already-recognized critical nature of the most conspicuous
    # Stage-3 unresolved records, but do not auto-reject from a regional WMO
    # comparison alone.
    if country == "TX" and metric == "tmax_highest" and value > 55.05:
        flags.append(Flag(
            "REVIEW_CRITICAL", "STAGE4_WMO_EASTERN_HEMISPHERE_CONFLICT_UNRESOLVED",
            "Candidate is above the WMO 55.0 °C Eastern-Hemisphere record snapshot; WMO notes that potential records can be under evaluation, so this remains review-only without a same-event authoritative contradiction.",
            WMO_TABLE_URL, priority=97,
        ))

    if country == "MX" and metric == "tmax_highest" and value >= 56.65 and "GREENLAND" not in station:
        flags.append(Flag(
            "REVIEW_CRITICAL", "STAGE4_TIES_WMO_WORLD_HIGH_OTHER_MEXICO_EVENT",
            "Candidate equals the WMO world high but is a different Mexico event/site; retain only as critical review pending event-specific authoritative verification.",
            WMO_TABLE_URL, priority=96,
        ))

    return flags


def _group_rows(rows: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get("stage4_status") == "REJECT_CONFIRMED":
            continue
        groups[(str(row.get("country_code", "")), str(row.get("metric", "")))].append(row)
    return groups


def _anchor_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = _group_rows(rows)
    audits: list[dict[str, object]] = []

    for anchor in COUNTRY_RECORD_ANCHORS:
        group = groups.get((anchor.country_code, anchor.metric), [])
        rank1 = [r for r in group if _int(r.get("stage4_rank")) == 1]
        best = rank1[0] if rank1 else None
        exact = [r for r in group if _event_matches(r, anchor, require_value=True)]
        value_matches = [r for r in group if _same_value(_float(r.get("value_c")), anchor.value_c)]

        if best is None:
            status = "NO_GHCN_CANDIDATE"
            note = "No surviving GHCN candidate is present for this country/metric."
        else:
            best_v = _float(best.get("value_c"))
            if _same_value(best_v, anchor.value_c):
                if exact:
                    status = "MATCH_EXACT_OFFICIAL_EVENT"
                    note = "GHCN best value matches the authoritative country record and the authoritative event is represented."
                else:
                    status = "MATCH_VALUE_EVENT_NOT_REPRESENTED"
                    note = "GHCN best value equals the authoritative record value, but the authoritative event/site is not represented in the candidate pool."
            elif _less_extreme(anchor.metric, best_v, anchor.value_c):
                status = "OFFICIAL_COVERAGE_GAP"
                note = "GHCN best candidate is less extreme than the authoritative country record; do not use GHCN rank 1 as the national record."
            else:
                status = "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR"
                note = "GHCN best candidate is more extreme than the authoritative country-record anchor; requires event-specific verification."

        audits.append({
            "anchor_id": anchor.anchor_id,
            "country_code": anchor.country_code,
            "country": anchor.country,
            "metric": anchor.metric,
            "official_value_c": f"{anchor.value_c:.1f}",
            "official_date": anchor.date,
            "official_site": anchor.site,
            "anchor_source": anchor.source,
            "anchor_note": anchor.note,
            "ghcn_best_value_c": "" if best is None else str(best.get("value_c", "")),
            "ghcn_best_date": "" if best is None else str(best.get("date", "")),
            "ghcn_best_station_id": "" if best is None else str(best.get("station_id", "")),
            "ghcn_best_station_name": "" if best is None else str(best.get("station_name", "")),
            "exact_official_event_present": "yes" if exact else "no",
            "official_value_present_anywhere": "yes" if value_matches else "no",
            "anchor_status": status,
            "anchor_status_note": note,
        })

    return audits


def _priority_score(row: dict[str, object]) -> int:
    status = str(row.get("stage4_status", ""))
    base = {
        "REJECT_CONFIRMED": 1000,
        "REVIEW_CRITICAL": 700,
        "REVIEW": 400,
        "PASS_PRELIMINARY": 100,
        "PASS_SOURCE_BACKED": 0,
    }.get(status, 200)
    try:
        extra = int(row.get("stage4_flag_priority") or 0)
    except (TypeError, ValueError):
        extra = 0
    record_status = str(row.get("stage4_country_record_status", ""))
    if record_status == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR":
        base += 180
    elif record_status == "MATCH_VALUE_EVENT_NOT_REPRESENTED":
        base += 80
    elif record_status == "OFFICIAL_COVERAGE_GAP":
        # Coverage gap is important for the record system, but is not evidence
        # that the observation itself is bad.
        base += 40
    return base + extra


def _render_report(
    annotated: list[dict[str, object]],
    clean: list[dict[str, object]],
    rank1: list[dict[str, object]],
    audits: list[dict[str, object]],
) -> str:
    counts = Counter(str(r.get("stage4_status")) for r in annotated)
    rejected = [r for r in annotated if r.get("stage4_status") == "REJECT_CONFIRMED"]
    new_source = [r for r in annotated if r.get("stage4_status") == "PASS_SOURCE_BACKED" and "OFFICIAL_EVENT_MATCH__" in str(r.get("stage4_flags", ""))]
    gaps = [a for a in audits if a["anchor_status"] == "OFFICIAL_COVERAGE_GAP"]
    conflicts = [a for a in audits if a["anchor_status"] == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR"]
    matches = [a for a in audits if a["anchor_status"] == "MATCH_EXACT_OFFICIAL_EVENT"]
    value_only = [a for a in audits if a["anchor_status"] == "MATCH_VALUE_EVENT_NOT_REPRESENTED"]
    pacific = [r for r in annotated if "PACIFIC_1979_1981_REPEATED_39C_CLUSTER" in str(r.get("stage4_flags", ""))]
    review_rank1 = [r for r in rank1 if r.get("stage4_status") in {"REVIEW", "REVIEW_CRITICAL"}]
    review_rank1.sort(key=lambda r: (-_priority_score(r), str(r.get("country_code")), str(r.get("metric"))))

    lines = [
        "# World GHCN candidate QC · Stage 4",
        "",
        "Stage 4 trennt erstmals **Beobachtungs-QC** von **Landesrekord-Vollständigkeit**.",
        "Ein gültiger GHCN-Rang-1-Wert wird nicht gelöscht, nur weil ein offizieller Landesrekord außerhalb des GHCN-Kandidatenpools liegt.",
        "Stattdessen wird dafür explizit `OFFICIAL_COVERAGE_GAP` ausgegeben.",
        "",
        "## Ergebnis",
        f"- Eingangszeilen aus Stage 3: {len(annotated):,}",
    ]
    for status in ("REJECT_CONFIRMED", "PASS_SOURCE_BACKED", "REVIEW_CRITICAL", "REVIEW", "PASS_PRELIMINARY"):
        lines.append(f"- {status}: {counts.get(status, 0):,}")
    lines += [
        f"- Stage-4-Clean-Zeilen: {len(clean):,}",
        f"- Country-Rank-1-Zeilen inkl. Gleichstände: {len(rank1):,}",
        f"- Offizielle Country-Record-Anker: {len(COUNTRY_RECORD_ANCHORS):,}",
        f"- Exakte offizielle Matches: {len(matches):,}",
        f"- Offizielle Coverage-Gaps: {len(gaps):,}",
        f"- GHCN extremer als offizieller Anker: {len(conflicts):,}",
        f"- Wertgleich, offizielles Ereignis nicht im Kandidatenpool: {len(value_only):,}",
        f"- Pacific-39.0°C-Clusterzeilen: {len(pacific):,}",
        "",
        "## Stage-4 bestätigt ausgeschlossen",
    ]
    if rejected:
        for r in rejected:
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('stage4_flags')}"
            )
    else:
        lines.append("Keine neuen direkten Ausschlüsse.")

    lines += ["", "## Neue source-backed Ereignis-Matches"]
    if new_source:
        for r in new_source:
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_name')} | {r.get('stage4_flags')}"
            )
    else:
        lines.append("Keine neuen exakten Ereignis-Matches im GHCN-Kandidatenpool.")

    lines += ["", "## Offizielle Landesrekorde, die im GHCN-Kandidatenpool fehlen"]
    if gaps:
        for a in gaps:
            lines.append(
                f"- {a['country_code']} | {a['metric']} | offiziell {a['official_value_c']} °C "
                f"({a['official_date']} {a['official_site']}) | GHCN best {a['ghcn_best_value_c']} °C "
                f"({a['ghcn_best_date']} {a['ghcn_best_station_name']})"
            )
    else:
        lines.append("Keine Coverage-Gaps unter den kuratierten Ankern.")

    lines += ["", "## GHCN extremer als offizieller Landesrekord-Anker"]
    if conflicts:
        for a in conflicts:
            lines.append(
                f"- {a['country_code']} | {a['metric']} | GHCN {a['ghcn_best_value_c']} °C "
                f"vs offiziell {a['official_value_c']} °C | {a['ghcn_best_date']} | {a['ghcn_best_station_name']}"
            )
    else:
        lines.append("Keine gruppenweiten Konflikte unter den kuratierten Country-Record-Ankern.")

    lines += ["", "## Pacific 39.0 °C · gezielter Cluster"]
    if pacific:
        for r in pacific:
            lines.append(
                f"- {r.get('country_code')} | {r.get('station_id')} | {r.get('station_name')} | "
                f"39.0 °C | ties={r.get('tie_count')} | {r.get('first_date')} bis {r.get('last_date')}"
            )
        lines.append("Diese Zeilen bleiben REVIEW_CRITICAL; der Cluster allein ist kein Ausschlussbeweis.")
    else:
        lines.append("Kein passender Cluster im Input.")

    lines += ["", "## Verbleibende Country-Rank-1-Prüffälle"]
    for r in review_rank1[:120]:
        lines.append(
            f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
            f"{r.get('date')} | {r.get('station_name')} | {r.get('stage4_status')} | "
            f"record={r.get('stage4_country_record_status') or '-'} | score={r.get('stage4_priority_score')}"
        )
    if len(review_rank1) > 120:
        lines.append(f"- … weitere {len(review_rank1)-120:,} in `review_priority_rank1_stage4.csv`.")

    lines += [
        "",
        "## Offizielle Rekordanker dieser Stufe",
        f"- WMO Records of Weather and Climate Extremes, snapshot {WMO_TABLE_DATE}: {WMO_TABLE_URL}",
        f"- Icelandic Meteorological Office, Iceland all-time maximum: {IMO_ICELAND_URL}",
        f"- NIWA / Earth Sciences New Zealand climate extremes: {NIWA_EXTREMES_URL}",
        f"- NIWA / WMO Ranfurly verification: {NIWA_RANFURLY_URL}",
        f"- South African Weather Service climate extremes: {SAWS_EXTREMES_URL}",
        f"- Met Eireann weather extreme records: {MET_EIREANN_EXTREMES_URL}",
        "",
        "## Architektur-Hinweis",
        "`world_country_extreme_candidates_stage4_clean.csv` bleibt die bereinigte GHCN-Kandidatenbasis.",
        "`official_country_record_anchors_stage4.csv` ist davon getrennt und zeigt, wo ein offizieller Rekord GHCN bestätigt, fehlt oder ihm widerspricht.",
        "Damit kann eine spätere finale Länder-Rekordreferenz offizielle Anker bevorzugen, ohne valide GHCN-Beobachtungen künstlich zu löschen.",
        "",
        "## Nächster Schritt",
        "Nach dem Stage-4-Log prüfen wir die verbliebenen `GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR`-Fälle und den Pacific-39.0°C-Cluster gezielt. Noch keine 2026-Integration.",
        "",
    ]
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    raw_rows, input_fields = _read_rows(input_path)
    flags_by_idx: dict[int, list[Flag]] = {}
    annotated: list[dict[str, object]] = []

    # Pass 1: event-level authoritative matches/conflicts and Stage-4 diagnostics.
    for idx, raw in enumerate(raw_rows):
        flags = _initial_flags(raw)
        flags_by_idx[idx] = flags
        inherited = (raw.get("stage3_status") or "PASS_PRELIMINARY").strip()
        status = _resolve_status(inherited, flags)
        row: dict[str, object] = dict(raw)
        row["__stage4_idx"] = idx
        row["stage4_status"] = status
        row["stage4_flags"] = "|".join(dict.fromkeys(f.code for f in flags))
        row["stage4_notes"] = " || ".join(dict.fromkeys(f.note for f in flags))
        row["stage4_sources"] = " || ".join(dict.fromkeys(f.source for f in flags if f.source))
        row["stage4_flag_priority"] = max((f.priority for f in flags), default=0)
        row["stage4_priority_score"] = ""
        row["stage4_rank"] = ""
        row["stage4_is_country_extreme"] = ""
        row["stage4_country_record_status"] = ""
        row["stage4_country_record_anchor_id"] = ""
        annotated.append(row)

    # Preliminary rerank after same-event confirmed rejections.
    ranked_pre = _rerank(annotated)
    rank_by_idx = {int(r["__stage4_idx"]): (r["stage4_rank"], r["stage4_is_country_extreme"]) for r in ranked_pre}
    for row in annotated:
        idx = int(row["__stage4_idx"])
        if idx in rank_by_idx:
            row["stage4_rank"], row["stage4_is_country_extreme"] = rank_by_idx[idx]

    # Country-record anchor audit based on the best surviving GHCN candidates.
    audits = _anchor_audit(annotated)
    audit_by_group = {(str(a["country_code"]), str(a["metric"])): a for a in audits}

    # Pass 2: attach record-completeness status to current rank-1 rows. Only a
    # more-extreme-than-official conflict changes candidate QC status. Coverage
    # gaps do NOT make the GHCN observation invalid.
    for row in annotated:
        if row.get("stage4_status") == "REJECT_CONFIRMED" or _int(row.get("stage4_rank")) != 1:
            continue
        key = (str(row.get("country_code", "")), str(row.get("metric", "")))
        audit = audit_by_group.get(key)
        if not audit:
            continue
        record_status = str(audit["anchor_status"])
        row["stage4_country_record_status"] = record_status
        row["stage4_country_record_anchor_id"] = str(audit["anchor_id"])

        idx = int(row["__stage4_idx"])
        if record_status == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR":
            f = Flag(
                "REVIEW_CRITICAL", "GHCN_MORE_EXTREME_THAN_OFFICIAL_COUNTRY_RECORD",
                f"GHCN country-rank-1 value {row.get('value_c')} °C is more extreme than authoritative anchor {audit['official_value_c']} °C ({audit['official_site']}).",
                str(audit["anchor_source"]), priority=99,
            )
            flags_by_idx[idx].append(f)
        elif record_status == "MATCH_VALUE_EVENT_NOT_REPRESENTED":
            f = Flag(
                "REVIEW", "OFFICIAL_VALUE_MATCH_BUT_EVENT_MISSING",
                "GHCN best value equals the official record value, but the official event/site is absent from the candidate pool; verify whether this is a valid tie or a coverage artifact.",
                str(audit["anchor_source"]), priority=60,
            )
            flags_by_idx[idx].append(f)

    # Re-resolve fields after pass-2 flags.
    for row in annotated:
        idx = int(row["__stage4_idx"])
        flags = flags_by_idx[idx]
        inherited = str(raw_rows[idx].get("stage3_status") or "PASS_PRELIMINARY").strip()
        row["stage4_status"] = _resolve_status(inherited, flags)
        row["stage4_flags"] = "|".join(dict.fromkeys(f.code for f in flags))
        row["stage4_notes"] = " || ".join(dict.fromkeys(f.note for f in flags))
        row["stage4_sources"] = " || ".join(dict.fromkeys(f.source for f in flags if f.source))
        row["stage4_flag_priority"] = max((f.priority for f in flags), default=0)

    # Final tie-aware rerank. If a second-pass flag changes only review status,
    # ranking is unchanged, but this keeps output logic self-contained.
    clean = _rerank(annotated)
    rank1 = [dict(r) for r in clean if _int(r.get("stage4_rank")) == 1]

    # Re-attach record status to final clean/rank1 copies (dict copies from rerank).
    audit_by_group = {(str(a["country_code"]), str(a["metric"])): a for a in audits}
    for collection in (clean, rank1):
        for row in collection:
            if _int(row.get("stage4_rank")) != 1:
                continue
            audit = audit_by_group.get((str(row.get("country_code", "")), str(row.get("metric", ""))))
            if audit:
                row["stage4_country_record_status"] = audit["anchor_status"]
                row["stage4_country_record_anchor_id"] = audit["anchor_id"]

    for row in annotated:
        row["stage4_priority_score"] = _priority_score(row)
    for row in clean:
        row["stage4_priority_score"] = _priority_score(row)
    for row in rank1:
        row["stage4_priority_score"] = _priority_score(row)

    extra_fields = [
        "stage4_status", "stage4_flags", "stage4_notes", "stage4_sources",
        "stage4_flag_priority", "stage4_priority_score", "stage4_rank",
        "stage4_is_country_extreme", "stage4_country_record_status",
        "stage4_country_record_anchor_id",
    ]
    output_fields = input_fields + [f for f in extra_fields if f not in input_fields]

    # Strip internal field before writing.
    def cleaned_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        out = []
        for r in rows:
            x = dict(r)
            x.pop("__stage4_idx", None)
            out.append(x)
        return out

    annotated_out = cleaned_rows(annotated)
    clean_out = cleaned_rows(clean)
    rank1_out = cleaned_rows(rank1)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "world_country_extreme_candidates_stage4_annotated.csv", annotated_out, output_fields)
    _write_csv(output_dir / "world_country_extreme_candidates_stage4_clean.csv", clean_out, output_fields)
    _write_csv(output_dir / "world_country_rank1_stage4.csv", rank1_out, output_fields)
    _write_csv(output_dir / "rejected_confirmed_stage4.csv", [r for r in annotated_out if r["stage4_status"] == "REJECT_CONFIRMED"], output_fields)
    _write_csv(output_dir / "source_backed_event_matches_stage4.csv", [r for r in annotated_out if r["stage4_status"] == "PASS_SOURCE_BACKED" and "OFFICIAL_EVENT_MATCH__" in str(r.get("stage4_flags", ""))], output_fields)
    _write_csv(output_dir / "pacific_39c_cluster_stage4.csv", [r for r in annotated_out if "PACIFIC_1979_1981_REPEATED_39C_CLUSTER" in str(r.get("stage4_flags", ""))], output_fields)

    review_rank1 = [r for r in rank1_out if r["stage4_status"] in {"REVIEW", "REVIEW_CRITICAL"}]
    review_rank1.sort(key=lambda r: (-_priority_score(r), str(r.get("country_code")), str(r.get("metric")), str(r.get("date"))))
    _write_csv(output_dir / "review_priority_rank1_stage4.csv", review_rank1, output_fields)

    anchor_fields = [
        "anchor_id", "country_code", "country", "metric", "official_value_c", "official_date",
        "official_site", "anchor_source", "anchor_note", "ghcn_best_value_c", "ghcn_best_date",
        "ghcn_best_station_id", "ghcn_best_station_name", "exact_official_event_present",
        "official_value_present_anywhere", "anchor_status", "anchor_status_note",
    ]
    _write_csv(output_dir / "official_country_record_anchors_stage4.csv", audits, anchor_fields)
    _write_csv(output_dir / "official_coverage_gaps_stage4.csv", [a for a in audits if a["anchor_status"] == "OFFICIAL_COVERAGE_GAP"], anchor_fields)
    _write_csv(output_dir / "official_anchor_conflicts_stage4.csv", [a for a in audits if a["anchor_status"] == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR"], anchor_fields)

    summary = {
        "schema_version": 1,
        "stage": "world_ghcn_candidate_qc_stage4",
        "input_rows": len(annotated_out),
        "status_counts": dict(Counter(str(r["stage4_status"]) for r in annotated_out)),
        "stage4_clean_rows": len(clean_out),
        "stage4_country_extreme_rows_including_ties": len(rank1_out),
        "confirmed_rejected_rows_stage4": sum(r["stage4_status"] == "REJECT_CONFIRMED" for r in annotated_out),
        "new_source_backed_event_matches_stage4": sum(r["stage4_status"] == "PASS_SOURCE_BACKED" and "OFFICIAL_EVENT_MATCH__" in str(r.get("stage4_flags", "")) for r in annotated_out),
        "official_country_record_anchors": len(COUNTRY_RECORD_ANCHORS),
        "official_anchor_status_counts": dict(Counter(str(a["anchor_status"]) for a in audits)),
        "official_coverage_gaps": sum(a["anchor_status"] == "OFFICIAL_COVERAGE_GAP" for a in audits),
        "official_anchor_conflicts_more_extreme_ghcn": sum(a["anchor_status"] == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR" for a in audits),
        "pacific_39c_cluster_rows": sum("PACIFIC_1979_1981_REPEATED_39C_CLUSTER" in str(r.get("stage4_flags", "")) for r in annotated_out),
        "rank1_review_rows": len(review_rank1),
        "ranking_policy": "Tie-aware ranking by distinct extreme value; equal country-extreme values share rank 1.",
        "stage4_architecture": "Observation validity and official country-record completeness are separate dimensions.",
        "qc_policy": "Reject only same-event authoritative contradictions; official-record absence is a coverage gap, not an observation rejection.",
    }

    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "qc_report.md").write_text(_render_report(annotated_out, clean_out, rank1_out, audits), encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "rank", "value_c", "date", "first_date", "last_date", "tie_count",
        "station_id", "station_name", "latitude", "longitude", "stage3_status", "stage3_rank",
    ]
    sample = [
        # Canada: same WMO event, wrong GHCN value -> confirmed reject.
        {"country_code":"CA","country":"Canada","metric":"tmin_lowest","rank":"1","value_c":"-63.9","date":"1947-02-03","first_date":"1947-02-03","last_date":"1947-02-03","tie_count":"1","station_id":"CA002101000","station_name":"SNAG A","latitude":"62.38","longitude":"-140.37","stage3_status":"PASS_PRELIMINARY","stage3_rank":"1"},
        # Canada fallback candidate after rejection.
        {"country_code":"CA","country":"Canada","metric":"tmin_lowest","rank":"2","value_c":"-61.0","date":"1950-01-01","first_date":"1950-01-01","last_date":"1950-01-01","tie_count":"1","station_id":"CA_TEST","station_name":"TEST","latitude":"62","longitude":"-140","stage3_status":"PASS_PRELIMINARY","stage3_rank":"2"},
        # US exact WMO world record -> source backed.
        {"country_code":"US","country":"United States","metric":"tmax_highest","rank":"1","value_c":"56.7","date":"1913-07-10","first_date":"1913-07-10","last_date":"1913-07-10","tie_count":"1","station_id":"USC00043603","station_name":"GREENLAND RCH","latitude":"36.45","longitude":"-116.87","stage3_status":"PASS_PRELIMINARY","stage3_rank":"1"},
        # Iceland GHCN best below official 30.5 -> coverage gap, not reject.
        {"country_code":"IC","country":"Iceland","metric":"tmax_highest","rank":"1","value_c":"29.4","date":"1974-06-23","first_date":"1974-06-23","last_date":"1974-06-23","tie_count":"1","station_id":"IC000004063","station_name":"AKUREYRI","latitude":"65.68","longitude":"-18.08","stage3_status":"REVIEW","stage3_rank":"1"},
        # New Zealand GHCN minimum misses WMO/NIWA -25.6 -> coverage gap.
        {"country_code":"NZ","country":"New Zealand","metric":"tmin_lowest","rank":"1","value_c":"-19.5","date":"1995-07-02","first_date":"1995-07-02","last_date":"1995-07-02","tie_count":"1","station_id":"NZ000937470","station_name":"TARA HILLS","latitude":"-44.52","longitude":"169.9","stage3_status":"REVIEW","stage3_rank":"1"},
        # Fiji legacy 39 C cluster -> critical review only.
        {"country_code":"FJ","country":"Fiji","metric":"tmax_highest","rank":"1","value_c":"39.0","date":"1979-01-04","first_date":"1979-01-04","last_date":"1981-12-25","tie_count":"80","station_id":"FJM00091699","station_name":"ONO-I-LAU","latitude":"-20.66","longitude":"-178.72","stage3_status":"REVIEW_CRITICAL","stage3_rank":"1"},
        # Pakistan WMO-verified Turbat event: source-back exact event, but no
        # country-record ceiling inference.
        {"country_code":"PK","country":"Pakistan","metric":"tmax_highest","rank":"2","value_c":"53.7","date":"2017-05-28","first_date":"2017-05-28","last_date":"2017-05-28","tie_count":"1","station_id":"PK_TEST","station_name":"TURBAT","latitude":"25.98","longitude":"63.07","stage3_status":"PASS_PRELIMINARY","stage3_rank":"2"},
        {"country_code":"PK","country":"Pakistan","metric":"tmax_highest","rank":"1","value_c":"53.9","date":"1985-06-22","first_date":"1985-06-22","last_date":"1985-06-22","tie_count":"1","station_id":"PK000041712","station_name":"DAL BANDIN","latitude":"28.88","longitude":"64.4","stage3_status":"PASS_PRELIMINARY","stage3_rank":"1"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader(); writer.writerows(sample)
        out = root / "out"
        summary = run(src, out)

        with (out / "world_country_extreme_candidates_stage4_annotated.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            ann = list(csv.DictReader(handle, delimiter=";"))
        by_id = {r["station_id"]: r for r in ann}
        assert by_id["CA002101000"]["stage4_status"] == "REJECT_CONFIRMED"
        assert "OFFICIAL_SAME_EVENT_VALUE_CONFLICT__WMO_CA_TMIN_1947" in by_id["CA002101000"]["stage4_flags"]
        assert by_id["USC00043603"]["stage4_status"] == "PASS_SOURCE_BACKED"
        assert "OFFICIAL_EVENT_MATCH__WMO_US_TMAX_1913" in by_id["USC00043603"]["stage4_flags"]
        assert by_id["FJM00091699"]["stage4_status"] == "REVIEW_CRITICAL"
        assert "PACIFIC_1979_1981_REPEATED_39C_CLUSTER" in by_id["FJM00091699"]["stage4_flags"]
        assert by_id["PK_TEST"]["stage4_status"] == "PASS_SOURCE_BACKED"

        with (out / "official_country_record_anchors_stage4.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            audits = list(csv.DictReader(handle, delimiter=";"))
        audit = {(r["country_code"], r["metric"]): r for r in audits}
        assert audit[("IC", "tmax_highest")]["anchor_status"] == "OFFICIAL_COVERAGE_GAP"
        assert audit[("NZ", "tmin_lowest")]["anchor_status"] == "OFFICIAL_COVERAGE_GAP"
        assert audit[("US", "tmax_highest")]["anchor_status"] == "MATCH_EXACT_OFFICIAL_EVENT"
        assert audit[("CA", "tmin_lowest")]["anchor_status"] == "OFFICIAL_COVERAGE_GAP"

        with (out / "world_country_rank1_stage4.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rank1 = list(csv.DictReader(handle, delimiter=";"))
        ca = [r for r in rank1 if r["country_code"] == "CA" and r["metric"] == "tmin_lowest"]
        assert len(ca) == 1 and ca[0]["station_id"] == "CA_TEST" and ca[0]["stage4_rank"] == "1"

        assert summary["confirmed_rejected_rows_stage4"] == 1
        assert summary["pacific_39c_cluster_rows"] == 1
        assert (out / "official_coverage_gaps_stage4.csv").exists()
        assert (out / "review_priority_rank1_stage4.csv").exists()

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
