#!/usr/bin/env python3
"""Stage-2 QC for world GHCN temperature-extreme candidates.

Stage 2 consumes the Stage-1 cleaned candidate table. It remains deliberately
conservative: only source-backed contradictions are rejected. Additional
provenance and record-envelope conflicts are marked for review and preserved.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WMO_TABLE_DATE = "2025-07-31"
WMO_TABLE_URL = "https://public.wmo.int/sites/default/files/2025-07/Table_Records_25Jul2025.pdf"
WMO_QURIYAT_URL = "https://wmo.int/media/july-sees-extreme-weather-high-impacts"
GHCN_README_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt"
BOM_MURCHISON_URL = "https://www.bom.gov.au/climate/averages/tables/cw_006099_All.shtml"

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
    "country_code", "country", "metric", "value_c", "date",
    "station_id", "station_name", "latitude", "longitude", "qc_status",
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


def _same_value(a: float, b: float, tol: float = 0.051) -> bool:
    return math.isfinite(a) and abs(a - b) <= tol


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


def _choose_status(inherited: str, flags: Iterable[Flag]) -> str:
    best = inherited if inherited in STATUS_ORDER else "PASS_PRELIMINARY"
    for flag in flags:
        if STATUS_ORDER[flag.status] > STATUS_ORDER[best]:
            best = flag.status
    return best


def _provenance_flags(row: dict[str, str]) -> tuple[list[str], list[str]]:
    """Describe GHCN provenance without treating source flags as QC failures."""
    flags: list[str] = []
    notes: list[str] = []
    mflag = (row.get("mflag_first_sample") or "").strip()
    sflag = (row.get("sflag_first_sample") or "").strip()

    if mflag == "H":
        flags.append("MFLAG_H_HOURLY_EXTREME")
        notes.append("GHCN MFLAG=H: TMAX/TMIN represents the highest/lowest hourly temperature.")

    source_notes = {
        "2": "GHCN SFLAG=2: Synoptic Summary of the Day (SSOD) version 2.",
        "S": "GHCN SFLAG=S: Global Summary of the Day derived from hourly synoptic reports.",
        "U": "GHCN SFLAG=U: U.S. Remote Automatic Weather Station (RAWS) data from WRCC.",
        "a": "GHCN SFLAG=a: Australian Bureau of Meteorology source data.",
        "f": "GHCN SFLAG=f: Fiji Meteorological Service source data.",
        "m": "GHCN SFLAG=m: Mexican CONAGUA source data.",
        "G": "GHCN SFLAG=G: official GCOS or other government-supplied data.",
    }
    if sflag in source_notes:
        flags.append(f"SFLAG_{sflag}_SOURCE")
        notes.append(source_notes[sflag])

    return flags, notes


def _stage2_flags(row: dict[str, str], value: float) -> list[Flag]:
    flags: list[Flag] = []
    station = (row.get("station_id") or "").strip()
    station_name = (row.get("station_name") or "").strip().upper()
    country = (row.get("country_code") or "").strip()
    metric = (row.get("metric") or "").strip()
    obs_date = (row.get("date") or "").strip()
    lat = _float(row.get("latitude"))

    # Australia / Murchison station 006099. GHCN carried 43.0 C as TMIN on
    # 2025-01-31. BOM's official station climate statistics give an all-time
    # highest daily minimum of 34.0 C and a January record of 31.2 C.
    if station == "ASN00006099" and metric == "tmin_highest" and obs_date == "2025-01-31" and value >= 43.0:
        flags.append(Flag(
            "REJECT_CONFIRMED",
            "BOM_MURCHISON_2025_TMIN_INVALID",
            "Murchison 43.0 °C TMIN conflicts with BOM station 006099 statistics: all-time highest daily minimum 34.0 °C; January highest daily minimum 31.2 °C.",
            BOM_MURCHISON_URL,
        ))

    # WMO Southern Hemisphere record is 50.7 C at Oodnadatta, Australia,
    # 2 Jan 1960. A different southern-hemisphere site tying that value must
    # not silently pass as a country record candidate.
    if metric == "tmax_highest" and math.isfinite(lat) and lat < 0 and _same_value(value, 50.7):
        recognized = ("OODNADATTA" in station_name and obs_date == "1960-01-02")
        if not recognized:
            flags.append(Flag(
                "REVIEW_CRITICAL",
                "TIES_WMO_SH_HIGH_OTHER_SITE",
                "Candidate ties the WMO Southern Hemisphere high of 50.7 °C but is not the recognized Oodnadatta observation of 2 Jan 1960.",
                WMO_TABLE_URL,
            ))

    # The 43.3 C Greenland Ranch daily minimum is historically disputed.
    # WMO does not formally archive 'highest minimum' as a record category and
    # described Quriyat's 42.6 C 24-hour minimum as believed to be the highest
    # such thermometer observation. Keep, but never auto-verify.
    if station == "USC00043603" and metric == "tmin_highest" and obs_date == "1918-07-05" and value >= 43.3:
        flags.append(Flag(
            "REVIEW_CRITICAL",
            "GREENLAND_RANCH_1918_HIGH_MIN_DISPUTED",
            "Historical 43.3 °C daily minimum remains disputed; WMO described Quriyat 42.6 °C as believed to be the highest 24-hour minimum and does not formally archive this category.",
            WMO_QURIYAT_URL,
        ))

    # Italy: WMO formally recognizes 48.8 C at Syracuse, Sicily on 11 Aug 2021
    # as the continental European high. Any Italian candidate above it is a
    # critical review case; a tie at another site/date is also critical.
    if country == "IT" and metric == "tmax_highest":
        if value > 48.85:
            flags.append(Flag(
                "REVIEW_CRITICAL",
                "ITALY_ABOVE_WMO_EUROPE_HIGH",
                "Italian candidate exceeds WMO's continental European high of 48.8 °C at Syracuse on 11 Aug 2021.",
                WMO_TABLE_URL,
            ))
        elif _same_value(value, 48.8) and not ("SIRAC" in station_name and obs_date == "2021-08-11"):
            flags.append(Flag(
                "REVIEW_CRITICAL",
                "ITALY_TIES_WMO_EUROPE_HIGH_OTHER_SITE",
                "Italian candidate ties 48.8 °C but is not the WMO-recognized Syracuse observation of 11 Aug 2021.",
                WMO_TABLE_URL,
            ))

    return flags


def _rerank(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get("stage2_status") == "REJECT_CONFIRMED":
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
        for rank, row in enumerate(group, start=1):
            row["stage2_rank"] = rank
            out.append(row)
    return out


def _render_report(annotated: list[dict[str, object]], clean: list[dict[str, object]], rank1: list[dict[str, object]]) -> str:
    counts = Counter(str(r.get("stage2_status")) for r in annotated)
    rejected = [r for r in annotated if r.get("stage2_status") == "REJECT_CONFIRMED"]
    critical = [r for r in annotated if r.get("stage2_status") == "REVIEW_CRITICAL"]
    provenance = [r for r in annotated if r.get("provenance_flags")]

    lines = [
        "# World GHCN candidate QC · Stage 2",
        "",
        "Stage 2 setzt die konservative Politik fort: nur extern belegte Widersprüche werden entfernt.",
        "GHCN-MFLAG/SFLAG werden als Herkunftsdiagnostik ausgegeben, aber nicht pauschal als Fehler gewertet.",
        "",
        "## Ergebnis",
        f"- Eingangszeilen aus Stage 1: {len(annotated):,}",
    ]
    for status in ("REJECT_CONFIRMED", "REVIEW_CRITICAL", "REVIEW", "PASS_PRELIMINARY"):
        lines.append(f"- {status}: {counts.get(status, 0):,}")
    lines += [
        f"- Stage-2-Clean-Zeilen: {len(clean):,}",
        f"- Stage-2-Rank-1-Zeilen: {len(rank1):,}",
        f"- Zeilen mit Herkunftsdiagnostik: {len(provenance):,}",
        "",
        "## Neu bestätigt ausgeschlossene Beobachtungen",
    ]
    if rejected:
        for r in rejected:
            lines.append(
                f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
                f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('stage2_flags')}"
            )
    else:
        lines.append("Keine.")

    lines += ["", "## Kritische Prüf-Fälle nach Stage 2"]
    for r in critical[:120]:
        lines.append(
            f"- {r.get('country_code')} | {r.get('metric')} | {float(r.get('value_c')):.1f} °C | "
            f"{r.get('date')} | {r.get('station_id')} | {r.get('station_name')} | {r.get('stage2_flags')}"
        )
    if len(critical) > 120:
        lines.append(f"- … weitere {len(critical)-120:,} Fälle in `review_priority_stage2.csv`.")

    lines += ["", "## Referenzen"]
    lines.append(f"- WMO Records of Weather and Climate Extremes, {WMO_TABLE_DATE}: {WMO_TABLE_URL}")
    lines.append(f"- WMO Quriyat high-minimum context: {WMO_QURIYAT_URL}")
    lines.append(f"- NOAA/NCEI GHCN-Daily README (MFLAG/QFLAG/SFLAG): {GHCN_README_URL}")
    lines.append(f"- Australian Bureau of Meteorology, Murchison station 006099 statistics: {BOM_MURCHISON_URL}")
    lines.append("")
    lines.append("## Nächster Schritt")
    lines.append("Nach diesem Lauf prüfen wir nur die verbleibenden Stage-2-Rank-1-Fälle mit REVIEW/REVIEW_CRITICAL; noch keine 2026-Integration.")
    lines.append("")
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    rows, input_fields = _read_rows(input_path)
    annotated: list[dict[str, object]] = []

    for raw in rows:
        row: dict[str, object] = dict(raw)
        value = _float(raw.get("value_c"))
        flags: list[Flag] = []
        if not math.isfinite(value):
            flags.append(Flag("REVIEW_CRITICAL", "NON_NUMERIC_VALUE", "value_c is not numeric."))
        else:
            flags.extend(_stage2_flags(raw, value))

        inherited = (raw.get("qc_status") or "PASS_PRELIMINARY").strip()
        status = _choose_status(inherited, flags)
        pflags, pnotes = _provenance_flags(raw)

        row["stage2_status"] = status
        row["stage2_flags"] = "|".join(dict.fromkeys(f.code for f in flags))
        row["stage2_notes"] = " || ".join(dict.fromkeys(f.note for f in flags))
        row["stage2_sources"] = " || ".join(dict.fromkeys(f.source for f in flags if f.source))
        row["provenance_flags"] = "|".join(dict.fromkeys(pflags))
        row["provenance_notes"] = " || ".join(dict.fromkeys(pnotes))
        row["stage2_rank"] = ""
        annotated.append(row)

    clean = _rerank(annotated)
    rank1 = [dict(r) for r in clean if _int(r.get("stage2_rank")) == 1]

    extra_fields = [
        "stage2_status", "stage2_flags", "stage2_notes", "stage2_sources",
        "provenance_flags", "provenance_notes", "stage2_rank",
    ]
    output_fields = input_fields + [f for f in extra_fields if f not in input_fields]
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(output_dir / "world_country_extreme_candidates_stage2_annotated.csv", annotated, output_fields)
    _write_csv(output_dir / "world_country_extreme_candidates_stage2_clean.csv", clean, output_fields)
    _write_csv(output_dir / "world_country_rank1_stage2.csv", rank1, output_fields)
    _write_csv(output_dir / "rejected_confirmed_stage2.csv", [r for r in annotated if r["stage2_status"] == "REJECT_CONFIRMED"], output_fields)
    _write_csv(output_dir / "review_priority_stage2.csv", [r for r in annotated if r["stage2_status"] in {"REVIEW", "REVIEW_CRITICAL"}], output_fields)
    _write_csv(output_dir / "provenance_review_stage2.csv", [r for r in annotated if r.get("provenance_flags")], output_fields)

    summary = {
        "schema_version": 1,
        "stage": "world_ghcn_candidate_qc_stage2",
        "input_rows": len(annotated),
        "status_counts": dict(Counter(str(r["stage2_status"]) for r in annotated)),
        "stage2_clean_rows": len(clean),
        "stage2_rank1_rows": len(rank1),
        "confirmed_rejected_rows_stage2": sum(r["stage2_status"] == "REJECT_CONFIRMED" for r in annotated),
        "provenance_flagged_rows": sum(bool(r.get("provenance_flags")) for r in annotated),
        "policy": "Only source-backed contradictions are removed; provenance flags are diagnostic, not automatic rejection criteria.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "qc_report.md").write_text(_render_report(annotated, clean, rank1), encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "rank", "value_c", "date", "station_id", "station_name",
        "latitude", "longitude", "mflag_first_sample", "sflag_first_sample", "qc_status", "stage1_rank",
    ]
    sample = [
        {"country_code":"AS","country":"Australia","metric":"tmin_highest","rank":"1","value_c":"43.0","date":"2025-01-31","station_id":"ASN00006099","station_name":"MURCHISON","latitude":"-26.90","longitude":"115.96","mflag_first_sample":"H","sflag_first_sample":"2","qc_status":"REVIEW_CRITICAL","stage1_rank":"1"},
        {"country_code":"AS","country":"Australia","metric":"tmin_highest","rank":"2","value_c":"35.0","date":"2020-01-01","station_id":"ASTEST00001","station_name":"TEST","latitude":"-25.0","longitude":"130.0","mflag_first_sample":"","sflag_first_sample":"a","qc_status":"PASS_PRELIMINARY","stage1_rank":"2"},
        {"country_code":"AS","country":"Australia","metric":"tmax_highest","rank":"1","value_c":"50.7","date":"1906-01-07","station_id":"ASN00076077","station_name":"MILDURA POST OFFICE","latitude":"-34.2","longitude":"142.1","mflag_first_sample":"","sflag_first_sample":"a","qc_status":"PASS_PRELIMINARY","stage1_rank":"1"},
        {"country_code":"US","country":"United States","metric":"tmin_highest","rank":"1","value_c":"43.3","date":"1918-07-05","station_id":"USC00043603","station_name":"GREENLAND RCH","latitude":"36.46","longitude":"-116.87","mflag_first_sample":"","sflag_first_sample":"0","qc_status":"REVIEW_CRITICAL","stage1_rank":"1"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader(); writer.writerows(sample)
        out = root / "out"
        summary = run(src, out)
        with (out / "world_country_extreme_candidates_stage2_annotated.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            result = list(csv.DictReader(handle, delimiter=";"))
        by_station = {r["station_id"]: r for r in result}
        assert by_station["ASN00006099"]["stage2_status"] == "REJECT_CONFIRMED"
        assert "BOM_MURCHISON_2025_TMIN_INVALID" in by_station["ASN00006099"]["stage2_flags"]
        assert by_station["ASN00076077"]["stage2_status"] == "REVIEW_CRITICAL"
        assert "TIES_WMO_SH_HIGH_OTHER_SITE" in by_station["ASN00076077"]["stage2_flags"]
        assert summary["confirmed_rejected_rows_stage2"] == 1
        assert (out / "world_country_rank1_stage2.csv").exists()
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
