#!/usr/bin/env python3
"""Stage-1 QC for world GHCN temperature-extreme candidates.

This script is deliberately conservative:
- It NEVER calls an unflagged candidate "verified".
- It removes only observations for which we have a concrete external
  contradiction or an explicitly encoded station/date rule.
- Everything else is kept, but suspicious values are marked for review.

Inputs are the Top-10 candidate rows produced by build_world_ghcn_baseline.py.
Outputs include an annotated raw candidate table, a stage-1 cleaned/reranked
candidate table, a stage-1 rank-1 table, and a human-readable QC report.
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
WMO_TABLE_URL = "https://wmo.int/sites/default/files/2025-07/Table_Records_25Jul2025.pdf"
WMO_QURIYAT_URL = "https://wmo.int/media/july-sees-extreme-weather-high-impacts"
FIJI_DEC_2025_URL = "https://www.met.gov.fj/media/climate_product_files/Fiji_Climate_Summary_December_2025.pdf"
FIJI_AUG_2025_URL = "https://www.met.gov.fj/media/climate_product_files/Fiji_Climate_Summary_August_2025.pdf"
NWS_HAWAII_URL = "https://www.weather.gov/hfo/climate_summary"
SAWS_CLIMATE_URL = "https://www.weathersa.co.za/home/climateques"
SAWS_VIOOLSDRIF_URL = "https://www.citizen.co.za/news/south-africa/weather/record-temperature-in-vioolsdrif-invalid-sa-weather-service/"

# Official WMO Archive anchors (table as of 31 July 2025).
WMO_WORLD_HIGH_C = 56.7
WMO_WORLD_LOW_C = -89.2
WMO_NH_LOW_C = -69.6
WMO_SH_HIGH_C = 50.7
WMO_EH_HIGH_C = 55.0

# Not a formal WMO Archive category. WMO described this 24-hour minimum as
# believed to be the highest such thermometer observation.
QURIYAT_24H_MIN_C = 42.6

STATUS_ORDER = {
    "PASS_PRELIMINARY": 0,
    "REVIEW": 1,
    "REVIEW_CRITICAL": 2,
    "REJECT_CONFIRMED": 3,
}

METRIC_DIRECTION = {
    "tmax_highest": "desc",
    "tmin_highest": "desc",
    "tmin_lowest": "asc",
    "tmax_lowest": "asc",
}

REQUIRED_COLUMNS = {
    "country_code",
    "country",
    "metric",
    "rank",
    "value_c",
    "date",
    "station_id",
    "station_name",
    "latitude",
    "longitude",
}


@dataclass(frozen=True)
class Flag:
    status: str
    code: str
    note: str
    source: str = ""


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


def _iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None


def _same_value(a: float, b: float, tol: float = 0.051) -> bool:
    return math.isfinite(a) and abs(a - b) <= tol


def _known_external_flags(row: dict[str, str], value: float) -> list[Flag]:
    """Hard-coded, source-backed contradictions found in the first QC pass."""
    flags: list[Flag] = []
    station = row.get("station_id", "").strip()
    metric = row.get("metric", "").strip()
    obs_date = row.get("date", "").strip()

    # Fiji / Vanuabalavu: the GHCN candidate list contained -39.4 °C TMIN
    # on 2025-12-31 and -39.2 °C TMAX on 2025-08-09. Fiji Met's official
    # December 2025 summary gives Vanuabalavu's monthly mean minimum as
    # 21.8 °C and its monthly daily minimum extreme as 20.5 °C; the country's
    # coolest night that month was 14.7 °C at Nadarivatu. The August 2025
    # official summary gives the country's coolest daytime maximum as 19.9 °C
    # and reports no usable Vanuabalavu temperature series for that month.
    if station == "FJM00091676" and metric in {"tmin_lowest", "tmax_lowest"} and value < 0.0:
        flags.append(
            Flag(
                "REJECT_CONFIRMED",
                "FIJI_VANUABALAVU_NEGATIVE",
                "Negative Vanuabalavu temperature contradicts Fiji Met's official 2025 monthly climate summaries.",
                f"{FIJI_DEC_2025_URL} | {FIJI_AUG_2025_URL}",
            )
        )

    # Hawaii / Kaupo Gap: NWS Honolulu states Hawaii's all-time state high is
    # 100 °F = 37.8 °C at Pahala (1931). The 55.6 °C GHCN candidate is thus
    # incompatible with the official state climate extreme.
    if station == "USR0000HKAU" and metric == "tmax_highest" and value > 37.8:
        flags.append(
            Flag(
                "REJECT_CONFIRMED",
                "HAWAII_KAUPO_ABOVE_STATE_RECORD",
                "Kaupo Gap candidate exceeds the NWS Honolulu official Hawaii all-time high of 100 °F (37.8 °C).",
                NWS_HAWAII_URL,
            )
        )

    # South Africa / Vioolsdrif: SAWS lists 50.0 °C (Dunbrody, 1918) as the
    # national record. SAWS also invalidated the late-November 2019 Vioolsdrif
    # readings after finding the recently replaced sensor questionable.
    if station == "SF002760720" and metric == "tmax_highest":
        if (obs_date == "2019-11-28" and value >= 50.1) or (obs_date == "2019-11-29" and value >= 53.2):
            flags.append(
                Flag(
                    "REJECT_CONFIRMED",
                    "VIOOLSDRIF_2019_SENSOR_INVALID",
                    "Late-November 2019 Vioolsdrif extreme was invalidated after SAWS found the replacement sensor questionable.",
                    f"{SAWS_CLIMATE_URL} | {SAWS_VIOOLSDRIF_URL}",
                )
            )

    return flags


def _wmo_envelope_flags(row: dict[str, str], value: float) -> list[Flag]:
    flags: list[Flag] = []
    metric = row.get("metric", "").strip()
    station = row.get("station_id", "").strip()
    obs_date = row.get("date", "").strip()
    lat = _float(row.get("latitude"))
    lon = _float(row.get("longitude"))

    if metric == "tmax_highest":
        if value > WMO_WORLD_HIGH_C + 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "ABOVE_WMO_WORLD_HIGH",
                    f"Candidate exceeds the WMO world high ({WMO_WORLD_HIGH_C:.1f} °C). Do not use without formal verification.",
                    WMO_TABLE_URL,
                )
            )
        elif value >= WMO_WORLD_HIGH_C - 0.05 and not (
            station == "USC00043603" and obs_date == "1913-07-10"
        ):
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "TIES_WMO_WORLD_HIGH_OTHER_SITE",
                    "Candidate ties the WMO world high but is not the recognized Furnace Creek / Greenland Ranch observation.",
                    WMO_TABLE_URL,
                )
            )

        if math.isfinite(lat) and lat < 0 and value > WMO_SH_HIGH_C + 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "ABOVE_WMO_SOUTHERN_HEMISPHERE_HIGH",
                    f"Southern-hemisphere candidate exceeds WMO's published {WMO_SH_HIGH_C:.1f} °C hemispheric high.",
                    WMO_TABLE_URL,
                )
            )

        if math.isfinite(lon) and lon > 0 and value > WMO_EH_HIGH_C + 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "ABOVE_WMO_EASTERN_HEMISPHERE_HIGH",
                    f"Eastern-hemisphere candidate exceeds WMO's published {WMO_EH_HIGH_C:.1f} °C hemispheric high.",
                    WMO_TABLE_URL,
                )
            )

    elif metric == "tmin_lowest":
        if value < WMO_WORLD_LOW_C - 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "BELOW_WMO_WORLD_LOW",
                    f"Candidate is colder than the WMO world low ({WMO_WORLD_LOW_C:.1f} °C).",
                    WMO_TABLE_URL,
                )
            )
        if math.isfinite(lat) and lat >= 0 and value < WMO_NH_LOW_C - 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "BELOW_WMO_NORTHERN_HEMISPHERE_LOW",
                    f"Northern-hemisphere candidate is colder than WMO's published {WMO_NH_LOW_C:.1f} °C hemispheric low.",
                    WMO_TABLE_URL,
                )
            )

    elif metric == "tmax_lowest":
        if value < WMO_WORLD_LOW_C - 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "DAILY_MAX_BELOW_WMO_WORLD_LOW",
                    "Daily maximum is below the WMO all-time world minimum temperature; this requires immediate source review.",
                    WMO_TABLE_URL,
                )
            )

    elif metric == "tmin_highest":
        if value > QURIYAT_24H_MIN_C + 0.05:
            flags.append(
                Flag(
                    "REVIEW_CRITICAL",
                    "HIGH_MIN_ABOVE_QURIYAT_REFERENCE",
                    f"Daily TMIN exceeds the {QURIYAT_24H_MIN_C:.1f} °C Quriyat 24-hour-minimum reference. Definitions/observation windows may differ, so review rather than reject.",
                    WMO_QURIYAT_URL,
                )
            )

    return flags


def _rank_gap_flags(rows: list[dict[str, str]]) -> dict[int, list[Flag]]:
    """Flag unusually isolated rank-1 values. Heuristic only; never rejects."""
    by_group: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        metric = row.get("metric", "").strip()
        if metric not in METRIC_DIRECTION:
            continue
        v = _float(row.get("value_c"))
        if math.isfinite(v):
            by_group[(row.get("country_code", "").strip(), metric)].append((idx, v))

    result: dict[int, list[Flag]] = defaultdict(list)
    thresholds = {
        "tmax_highest": (3.0, 6.0),
        "tmin_highest": (3.0, 6.0),
        "tmin_lowest": (8.0, 15.0),
        "tmax_lowest": (8.0, 15.0),
    }

    for (_country, metric), entries in by_group.items():
        reverse = METRIC_DIRECTION[metric] == "desc"
        entries_sorted = sorted(entries, key=lambda x: x[1], reverse=reverse)
        if len(entries_sorted) < 2:
            continue

        best_idx, best_val = entries_sorted[0]
        # Compare with the next distinct value so ties do not create a zero gap.
        second_val = None
        for _, candidate in entries_sorted[1:]:
            if abs(candidate - best_val) > 0.051:
                second_val = candidate
                break
        if second_val is None:
            continue

        gap = (best_val - second_val) if reverse else (second_val - best_val)
        review_gap, critical_gap = thresholds[metric]
        if gap >= critical_gap:
            status = "REVIEW_CRITICAL"
        elif gap >= review_gap:
            status = "REVIEW"
        else:
            continue

        result[best_idx].append(
            Flag(
                status,
                "ISOLATED_COUNTRY_RANK1_GAP",
                f"Raw country rank-1 is isolated from the next distinct candidate by {gap:.1f} °C; heuristic review only.",
                "",
            )
        )

    return result


def _choose_status(flags: Iterable[Flag]) -> str:
    best = "PASS_PRELIMINARY"
    for flag in flags:
        if STATUS_ORDER[flag.status] > STATUS_ORDER[best]:
            best = flag.status
    return best


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


def _rerank_clean_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row["qc_status"] == "REJECT_CONFIRMED":
            continue
        groups[(str(row.get("country_code", "")), str(row.get("metric", "")))].append(dict(row))

    clean: list[dict[str, object]] = []
    for key in sorted(groups):
        group = groups[key]
        metric = key[1]
        reverse = METRIC_DIRECTION.get(metric, "desc") == "desc"
        group.sort(
            key=lambda r: (
                -_float(r.get("value_c")) if reverse else _float(r.get("value_c")),
                str(r.get("date", "")),
                str(r.get("station_id", "")),
            )
        )
        for new_rank, row in enumerate(group, start=1):
            row["stage1_rank"] = new_rank
            clean.append(row)
    return clean


def _render_report(
    annotated: list[dict[str, object]],
    clean: list[dict[str, object]],
    rank1: list[dict[str, object]],
) -> str:
    counts = Counter(str(r["qc_status"]) for r in annotated)
    rejected = [r for r in annotated if r["qc_status"] == "REJECT_CONFIRMED"]
    critical = [r for r in annotated if r["qc_status"] == "REVIEW_CRITICAL"]
    review = [r for r in annotated if r["qc_status"] == "REVIEW"]

    lines: list[str] = []
    lines.append("# World GHCN candidate QC · Stage 1")
    lines.append("")
    lines.append("Diese Stufe ist bewusst konservativ: **PASS_PRELIMINARY bedeutet nicht fachlich verifiziert.**")
    lines.append("Entfernt werden nur konkret extern widersprochene Beobachtungen; WMO-Grenzkonflikte und statistische Auffälligkeiten bleiben als REVIEW erhalten.")
    lines.append("")
    lines.append("## Ergebnis")
    lines.append(f"- Eingangszeilen: {len(annotated):,}")
    for status in ("REJECT_CONFIRMED", "REVIEW_CRITICAL", "REVIEW", "PASS_PRELIMINARY"):
        lines.append(f"- {status}: {counts.get(status, 0):,}")
    lines.append(f"- Stage-1-Clean-Zeilen: {len(clean):,}")
    lines.append(f"- Stage-1-Rank-1-Zeilen: {len(rank1):,}")
    lines.append("")

    lines.append("## Bestätigt ausgeschlossene Beobachtungen")
    if not rejected:
        lines.append("Keine.")
    else:
        for r in sorted(rejected, key=lambda x: (str(x.get("country_code")), str(x.get("metric")), str(x.get("date")))):
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('qc_flags')}"
            )
    lines.append("")

    lines.append("## Kritische Prüf-Fälle")
    if not critical:
        lines.append("Keine.")
    else:
        def sev_key(r: dict[str, object]) -> tuple:
            metric = str(r.get("metric", ""))
            v = _float(r.get("value_c"))
            if metric in {"tmax_highest", "tmin_highest"}:
                v = -v
            return (metric, v, str(r.get("country_code", "")), _int(r.get("rank")))
        for r in sorted(critical, key=sev_key)[:120]:
            lines.append(
                f"- {r.get('country_code')} | raw rank {r.get('rank')} | {r.get('metric')} | "
                f"{float(r.get('value_c')):.1f} °C | {r.get('date')} | {r.get('station_id')} | "
                f"{r.get('station_name')} | {r.get('qc_flags')}"
            )
        if len(critical) > 120:
            lines.append(f"- … weitere {len(critical) - 120:,} kritische Fälle in `world_country_extreme_candidates_qc.csv`.")
    lines.append("")

    lines.append("## Stage-1 Rank-1 nach bestätigten Ausschlüssen")
    for metric in ("tmax_highest", "tmin_lowest", "tmax_lowest", "tmin_highest"):
        subset = [r for r in rank1 if r.get("metric") == metric]
        reverse = METRIC_DIRECTION[metric] == "desc"
        subset.sort(key=lambda r: _float(r.get("value_c")), reverse=reverse)
        lines.append("")
        lines.append(f"### {metric}")
        for r in subset[:25]:
            lines.append(
                f"- {r.get('country_code')} | {float(r.get('value_c')):.1f} °C | {r.get('date')} | "
                f"{r.get('station_id')} | {r.get('station_name')} | {r.get('qc_status')}"
            )

    lines.append("")
    lines.append("## Referenzen dieser Stufe")
    lines.append(f"- WMO World Weather and Climate Extremes Archive, table as of {WMO_TABLE_DATE}: {WMO_TABLE_URL}")
    lines.append(f"- WMO Quriyat 24-hour minimum reference: {WMO_QURIYAT_URL}")
    lines.append(f"- Fiji Meteorological Service, December 2025 climate summary: {FIJI_DEC_2025_URL}")
    lines.append(f"- Fiji Meteorological Service, August 2025 climate summary: {FIJI_AUG_2025_URL}")
    lines.append(f"- NWS Honolulu, Climate of Hawaii: {NWS_HAWAII_URL}")
    lines.append(f"- South African Weather Service, climate extremes: {SAWS_CLIMATE_URL}")
    lines.append("")
    lines.append("## Wichtig")
    lines.append("Diese Stufe baut **noch keine endgültige Länder-Rekordliste**. Nach dem Log-Check folgt die gezielte Verifikation der verbleibenden Rank-1/REVIEW-Fälle gegen nationale Wetterdienste, WMO und weitere belastbare Rekordquellen.")
    lines.append("")
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    rows, input_fields = _read_rows(input_path)
    gap_flags = _rank_gap_flags(rows)

    annotated: list[dict[str, object]] = []
    for idx, raw in enumerate(rows):
        row: dict[str, object] = dict(raw)
        value = _float(raw.get("value_c"))
        flags: list[Flag] = []
        if not math.isfinite(value):
            flags.append(Flag("REVIEW_CRITICAL", "NON_NUMERIC_VALUE", "value_c is not numeric."))
        else:
            flags.extend(_known_external_flags(raw, value))
            flags.extend(_wmo_envelope_flags(raw, value))
            flags.extend(gap_flags.get(idx, []))

        status = _choose_status(flags)
        row["qc_status"] = status
        row["qc_flags"] = "|".join(dict.fromkeys(f.code for f in flags))
        row["qc_notes"] = " || ".join(dict.fromkeys(f.note for f in flags))
        row["qc_sources"] = " || ".join(dict.fromkeys(f.source for f in flags if f.source))
        row["stage1_rank"] = ""
        annotated.append(row)

    clean = _rerank_clean_rows(annotated)
    rank1 = [dict(r) for r in clean if _int(r.get("stage1_rank")) == 1]

    extra_fields = ["qc_status", "qc_flags", "qc_notes", "qc_sources", "stage1_rank"]
    output_fields = input_fields + [f for f in extra_fields if f not in input_fields]

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "world_country_extreme_candidates_qc.csv", annotated, output_fields)
    _write_csv(output_dir / "world_country_extreme_candidates_stage1_clean.csv", clean, output_fields)
    _write_csv(output_dir / "world_country_rank1_stage1.csv", rank1, output_fields)
    _write_csv(
        output_dir / "rejected_confirmed.csv",
        [r for r in annotated if r["qc_status"] == "REJECT_CONFIRMED"],
        output_fields,
    )
    _write_csv(
        output_dir / "review_cases.csv",
        [r for r in annotated if r["qc_status"] in {"REVIEW", "REVIEW_CRITICAL"}],
        output_fields,
    )

    summary: dict[str, object] = {
        "schema_version": 1,
        "stage": "world_ghcn_candidate_qc_stage1",
        "input_rows": len(annotated),
        "status_counts": dict(Counter(str(r["qc_status"]) for r in annotated)),
        "stage1_clean_rows": len(clean),
        "stage1_rank1_rows": len(rank1),
        "confirmed_rejected_rows": sum(r["qc_status"] == "REJECT_CONFIRMED" for r in annotated),
        "wmo_reference_table_date": WMO_TABLE_DATE,
        "policy": "Only source-backed contradictions are removed. REVIEW/PASS_PRELIMINARY are not final record verification.",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = _render_report(annotated, clean, rank1)
    (output_dir / "qc_report.md").write_text(report, encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "rank", "value_c", "date",
        "station_id", "station_name", "latitude", "longitude",
    ]
    sample = [
        {"country_code":"FJ","country":"Fiji","metric":"tmin_lowest","rank":"1","value_c":"-39.4","date":"2025-12-31","station_id":"FJM00091676","station_name":"Vanuabalavu","latitude":"-17.25","longitude":"-178.92"},
        {"country_code":"FJ","country":"Fiji","metric":"tmin_lowest","rank":"2","value_c":"8.0","date":"1997-07-01","station_id":"FJTEST00001","station_name":"Highland","latitude":"-17.7","longitude":"178.0"},
        {"country_code":"US","country":"United States","metric":"tmax_highest","rank":"1","value_c":"56.7","date":"1913-07-10","station_id":"USC00043603","station_name":"GREENLAND RCH","latitude":"36.46","longitude":"-116.87"},
        {"country_code":"US","country":"United States","metric":"tmax_highest","rank":"2","value_c":"55.6","date":"2015-02-13","station_id":"USR0000HKAU","station_name":"KAUPO GAP HAWAII","latitude":"20.65","longitude":"-156.14"},
        {"country_code":"SF","country":"South Africa","metric":"tmax_highest","rank":"1","value_c":"53.2","date":"2019-11-29","station_id":"SF002760720","station_name":"VIOOLSDRIF","latitude":"-28.77","longitude":"17.62"},
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","rank":"1","value_c":"56.5","date":"1890-06-20","station_id":"TX000038895","station_name":"BAJRAMALY","latitude":"37.62","longitude":"62.18"},
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","rank":"2","value_c":"49.8","date":"2021-07-01","station_id":"TXTEST00001","station_name":"TEST","latitude":"37.0","longitude":"61.0"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(sample)
        out = root / "out"
        summary = run(src, out)
        rows, _ = _read_rows(out / "world_country_extreme_candidates_qc.csv")
        # _read_rows expects original required columns and ignores extra fields.
        status_by_station = {r["station_id"]: r.get("qc_status", "") for r in rows}
        assert status_by_station["FJM00091676"] == "REJECT_CONFIRMED"
        assert status_by_station["USR0000HKAU"] == "REJECT_CONFIRMED"
        assert status_by_station["SF002760720"] == "REJECT_CONFIRMED"
        assert status_by_station["TX000038895"] == "REVIEW_CRITICAL"
        assert summary["confirmed_rejected_rows"] == 3
        assert (out / "qc_report.md").exists()
        assert (out / "world_country_rank1_stage1.csv").exists()
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
        self_test()
        return 0
    summary = run(args.input, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
