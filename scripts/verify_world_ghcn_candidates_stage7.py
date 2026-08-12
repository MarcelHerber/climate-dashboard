#!/usr/bin/env python3
"""Stage-7 targeted resolution of the remaining Stage-6 country-record reviews.

Stage 7 is deliberately conservative. It does not re-run global observation QC.
It only resolves Stage-6 UNRESOLVED_REVIEW rows when one of two conditions holds:

1) a new authoritative official/national-service anchor is available; or
2) the remaining review is *only* the inherited isolated-rank-1-gap heuristic,
   the candidate is not REVIEW_CRITICAL / held, and GHCN provenance is explicitly
   government-supplied (SFLAG=G).

Everything else stays UNRESOLVED_REVIEW. In particular, HOLDs are never silently
promoted to lower fallback records.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

MASTER_REQUIRED = {
    "country_code", "country", "metric", "master_status", "publishable",
    "canonical_value_c", "canonical_date", "canonical_site",
    "canonical_station_id", "canonical_source", "canonical_source_type",
    "official_verified", "official_anchor_id", "official_coverage_status",
    "ghcn_support_count", "ghcn_candidate_tie_count", "fallback_candidate_value_c",
    "fallback_candidate_events", "held_more_extreme_count", "held_more_extreme_events",
    "unresolved_reason", "notes",
}

CANDIDATE_REQUIRED = {
    "country_code", "country", "metric", "value_c", "date", "station_id",
    "station_name", "stage5_status", "stage5_record_eligibility",
    "stage5_record_eligible", "stage5_record_candidate_rank",
}

CMA_CHINA_2023_URL = "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xjctz/202307/t20230717_5652897.html"


@dataclass(frozen=True)
class Stage7Anchor:
    anchor_id: str
    country_code: str
    country: str
    metric: str
    value_c: float
    date: str
    site: str
    source: str
    note: str
    site_keywords: tuple[str, ...] = ()


STAGE7_ANCHORS: tuple[Stage7Anchor, ...] = (
    Stage7Anchor(
        "CMA_CH_TMAX_2023_SANBAO_52_2",
        "CH",
        "China",
        "tmax_highest",
        52.2,
        "2023-07-16",
        "Sanbao Township, Gaochang District, Turpan, Xinjiang",
        CMA_CHINA_2023_URL,
        "China Meteorological Administration reported 52.2 C at Sanbao/Turpan on 16 Jul 2023 as a new historical extreme.",
        ("SANBAO", "SAN BAO", "三堡"),
    ),
)

ALLOWED_HEURISTIC_FLAGS = {"ISOLATED_COUNTRY_RANK1_GAP"}
FLAG_FIELDS = (
    "qc_flags", "stage2_flags", "stage3_flags", "stage4_flags", "stage5_flags",
)


def _float(v: object) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return math.nan


def _int(v: object, default: int = 999999) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _norm(v: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(v or "").upper()).strip()


def _same_value(a: float, b: float, tol: float = 0.051) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _read_csv(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fields = list(reader.fieldnames or [])
        missing = required - set(fields)
        if missing:
            raise SystemExit(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        return list(reader), fields


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _candidate_groups(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        out[(r.get("country_code", ""), r.get("metric", ""))].append(r)
    return out


def _rank1(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and r.get("stage5_record_eligible") == "yes"
        and _int(r.get("stage5_record_candidate_rank")) == 1
    ]


def _holds(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and str(r.get("stage5_record_eligibility", "")).startswith("HOLD")
    ]


def _split_flags(value: object) -> set[str]:
    return {x.strip() for x in str(value or "").split("|") if x.strip()}


def _substantive_flags(row: dict[str, str]) -> set[str]:
    flags: set[str] = set()
    for f in FLAG_FIELDS:
        flags |= _split_flags(row.get(f, ""))
    return {f for f in flags if f not in ALLOWED_HEURISTIC_FLAGS}


def _government_provenance(row: dict[str, str]) -> bool:
    provenance = _split_flags(row.get("provenance_flags", ""))
    return "SFLAG_G_SOURCE" in provenance


def _heuristic_only_government_review(rank1: list[dict[str, str]]) -> bool:
    if not rank1:
        return False
    for r in rank1:
        if r.get("stage5_status") != "REVIEW":
            return False
        if _substantive_flags(r):
            return False
        if not _government_provenance(r):
            return False
    return True


def _anchor_exact_support(anchor: Stage7Anchor, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    exact: list[dict[str, str]] = []
    for r in rows:
        if r.get("stage5_status") == "REJECT_CONFIRMED":
            continue
        if not _same_value(_float(r.get("value_c")), anchor.value_c):
            continue
        if anchor.date and r.get("date") != anchor.date:
            continue
        if anchor.site_keywords:
            hay = _norm(f"{r.get('station_name','')} {r.get('station_id','')}")
            if not any(_norm(k) in hay for k in anchor.site_keywords):
                continue
        exact.append(r)
    return exact


def _join_unique(values: list[str]) -> str:
    return " | ".join(dict.fromkeys(v for v in values if v))


def _candidate_canonical(rank1: list[dict[str, str]]) -> dict[str, str]:
    if not rank1:
        return {"value": "", "date": "", "site": "", "station_id": "", "source": ""}
    return {
        "value": str(rank1[0].get("value_c", "")),
        "date": _join_unique([str(r.get("date", "")) for r in rank1]),
        "site": _join_unique([str(r.get("station_name", "")) for r in rank1]),
        "station_id": _join_unique([str(r.get("station_id", "")) for r in rank1]),
        "source": _join_unique([str(r.get("stage5_sources", "")) or "GHCN-Daily" for r in rank1]),
    }


def run(master_input: Path, candidate_input: Path, output_dir: Path) -> dict[str, object]:
    master, master_fields = _read_csv(master_input, MASTER_REQUIRED)
    candidates, _candidate_fields = _read_csv(candidate_input, CANDIDATE_REQUIRED)
    groups = _candidate_groups(candidates)
    anchors = {(a.country_code, a.metric): a for a in STAGE7_ANCHORS}

    extra_fields = [
        "stage7_previous_master_status", "stage7_resolution", "stage7_resolution_code",
        "stage7_resolution_source", "stage7_resolution_notes",
    ]
    out_fields = master_fields + [f for f in extra_fields if f not in master_fields]

    updated: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []

    for src in master:
        row: dict[str, object] = dict(src)
        key = (src.get("country_code", ""), src.get("metric", ""))
        group = groups.get(key, [])
        rank1 = _rank1(group)
        holds = _holds(group)
        previous = src.get("master_status", "")

        row.update({
            "stage7_previous_master_status": previous,
            "stage7_resolution": "CARRIED_FORWARD",
            "stage7_resolution_code": "",
            "stage7_resolution_source": "",
            "stage7_resolution_notes": "",
        })

        if previous != "UNRESOLVED_REVIEW":
            updated.append(row)
            continue

        anchor = anchors.get(key)
        if anchor is not None:
            exact = _anchor_exact_support(anchor, group)
            status = "OFFICIAL_SOURCE_BACKED" if exact else "OFFICIAL_COVERAGE_GAP"
            row.update({
                "master_status": status,
                "publishable": "yes",
                "canonical_value_c": f"{anchor.value_c:.1f}",
                "canonical_date": anchor.date,
                "canonical_site": anchor.site,
                "canonical_station_id": _join_unique([str(r.get("station_id", "")) for r in exact]),
                "canonical_source": anchor.source,
                "canonical_source_type": "OFFICIAL_ANCHOR_STAGE7",
                "official_verified": "yes",
                "official_anchor_id": anchor.anchor_id,
                "official_coverage_status": "OFFICIAL_EVENT_PRESENT_IN_GHCN" if exact else "OFFICIAL_COVERAGE_GAP",
                "ghcn_support_count": len(exact),
                "unresolved_reason": "",
                "notes": anchor.note,
                "stage7_resolution": "RESOLVED",
                "stage7_resolution_code": "OFFICIAL_ANCHOR_ADDED_STAGE7",
                "stage7_resolution_source": anchor.source,
                "stage7_resolution_notes": anchor.note,
            })
            decisions.append({
                "country_code": key[0], "country": src.get("country", ""), "metric": key[1],
                "previous_status": previous, "new_status": status,
                "resolution_code": "OFFICIAL_ANCHOR_ADDED_STAGE7",
                "canonical_value_c": f"{anchor.value_c:.1f}", "canonical_date": anchor.date,
                "canonical_site": anchor.site, "source": anchor.source, "notes": anchor.note,
            })

        elif holds:
            row.update({
                "stage7_resolution": "STILL_UNRESOLVED",
                "stage7_resolution_code": "RECORD_HOLD_REMAINS",
                "stage7_resolution_notes": "A Stage-5 record HOLD remains; Stage 7 does not promote the fallback candidate.",
            })

        elif _heuristic_only_government_review(rank1):
            can = _candidate_canonical(rank1)
            row.update({
                "master_status": "GHCN_CANDIDATE",
                "publishable": "yes",
                "canonical_value_c": can["value"],
                "canonical_date": can["date"],
                "canonical_site": can["site"],
                "canonical_station_id": can["station_id"],
                "canonical_source": can["source"],
                "canonical_source_type": "GHCN_GOVERNMENT_PROVENANCE",
                "official_verified": "no",
                "unresolved_reason": "",
                "notes": "Stage-6 review was only the isolated-rank-1-gap heuristic; all tied rank-1 rows have GHCN SFLAG=G government-supplied provenance and no additional substantive QC flag.",
                "stage7_resolution": "RESOLVED",
                "stage7_resolution_code": "HEURISTIC_ONLY_REVIEW_CLEARED_SFLAG_G",
                "stage7_resolution_source": "NOAA/NCEI GHCN-Daily provenance (SFLAG=G)",
                "stage7_resolution_notes": "Heuristic-only review cleared; this remains a GHCN candidate, not an official national-service record.",
            })
            decisions.append({
                "country_code": key[0], "country": src.get("country", ""), "metric": key[1],
                "previous_status": previous, "new_status": "GHCN_CANDIDATE",
                "resolution_code": "HEURISTIC_ONLY_REVIEW_CLEARED_SFLAG_G",
                "canonical_value_c": can["value"], "canonical_date": can["date"],
                "canonical_site": can["site"], "source": "NOAA/NCEI GHCN-Daily provenance (SFLAG=G)",
                "notes": "No substantive QC flag beyond isolated rank-1 gap; government-supplied provenance.",
            })

        else:
            code = "REVIEW_CRITICAL_REMAINS" if any(r.get("stage5_status") == "REVIEW_CRITICAL" for r in rank1) else "REVIEW_NOT_YET_SOURCE_RESOLVED"
            row.update({
                "stage7_resolution": "STILL_UNRESOLVED",
                "stage7_resolution_code": code,
                "stage7_resolution_notes": "No Stage-7 authoritative anchor or conservative provenance-only resolution applies.",
            })

        updated.append(row)

    publishable = [r for r in updated if r.get("publishable") == "yes"]
    unresolved = [r for r in updated if r.get("master_status") == "UNRESOLVED_REVIEW"]
    resolved = [r for r in updated if r.get("stage7_resolution") == "RESOLVED"]

    decision_fields = [
        "country_code", "country", "metric", "previous_status", "new_status",
        "resolution_code", "canonical_value_c", "canonical_date", "canonical_site",
        "source", "notes",
    ]

    _write_csv(output_dir / "world_country_record_master_stage7.csv", updated, out_fields)
    _write_csv(output_dir / "world_country_record_master_publishable_stage7.csv", publishable, out_fields)
    _write_csv(output_dir / "world_country_record_master_unresolved_stage7.csv", unresolved, out_fields)
    _write_csv(output_dir / "resolved_stage7.csv", resolved, out_fields)
    _write_csv(output_dir / "resolution_decisions_stage7.csv", decisions, decision_fields)

    status_counts = Counter(str(r.get("master_status", "")) for r in updated)
    resolution_counts = Counter(str(r.get("stage7_resolution", "")) for r in updated)
    code_counts = Counter(str(r.get("stage7_resolution_code", "")) for r in updated if r.get("stage7_resolution_code"))

    summary: dict[str, object] = {
        "schema_version": 1,
        "stage": "world_ghcn_country_record_targeted_resolution_stage7",
        "master_rows": len(updated),
        "stage6_unresolved_input_rows": sum(r.get("master_status") == "UNRESOLVED_REVIEW" for r in master),
        "resolved_in_stage7": len(resolved),
        "unresolved_after_stage7": len(unresolved),
        "publishable_after_stage7": len(publishable),
        "master_status_counts": dict(sorted(status_counts.items())),
        "stage7_resolution_counts": dict(sorted(resolution_counts.items())),
        "stage7_resolution_code_counts": dict(sorted(code_counts.items())),
        "stage7_official_anchors_added": len(STAGE7_ANCHORS),
        "policy": "Resolve only authoritative-anchor cases or heuristic-only REVIEW rows with explicit GHCN SFLAG=G government provenance; REVIEW_CRITICAL and HOLD cases remain unresolved.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = [
        "# World GHCN country record master · Stage 7",
        "",
        "Stage 7 bearbeitet ausschließlich die in Stage 6 offenen Country+Metric-Zeilen.",
        "",
        "## Ergebnis",
        f"- Stage-6 unresolved am Eingang: {summary['stage6_unresolved_input_rows']}",
        f"- In Stage 7 aufgelöst: {summary['resolved_in_stage7']}",
        f"- Danach weiterhin unresolved: {summary['unresolved_after_stage7']}",
        f"- Publishable nach Stage 7: {summary['publishable_after_stage7']}",
        "",
        "## Auflösungsregeln",
        "- Neue belastbare Nationaldienst-/WMO-Anker dürfen eine offene Masterzeile direkt auflösen.",
        "- Ein REVIEW darf ohne zusätzlichen externen Rekordanker nur freigegeben werden, wenn ausschließlich der heuristische ISOLATED_COUNTRY_RANK1_GAP verbleibt und alle Rank-1-Zeilen GHCN SFLAG=G tragen.",
        "- REVIEW_CRITICAL und Stage-5-HOLDs bleiben offen.",
        "",
        "## Neuer offizieller Anker",
        "- China tmax_highest: 52.2 °C, Sanbao/Turpan, 2023-07-16, China Meteorological Administration.",
        "",
        "## Wichtig",
        "Eine durch SFLAG=G freigegebene Zeile bleibt GHCN_CANDIDATE und wird nicht als offiziell national verifizierter Rekord ausgegeben.",
    ]
    (output_dir / "qc_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def self_test() -> None:
    master_fields = [
        "country_code", "country", "metric", "master_status", "publishable",
        "canonical_value_c", "canonical_date", "canonical_site", "canonical_station_id",
        "canonical_source", "canonical_source_type", "official_verified", "official_anchor_id",
        "official_coverage_status", "ghcn_support_count", "ghcn_candidate_tie_count",
        "fallback_candidate_value_c", "fallback_candidate_events", "held_more_extreme_count",
        "held_more_extreme_events", "unresolved_reason", "notes",
    ]
    candidate_fields = [
        "country_code", "country", "metric", "value_c", "date", "station_id", "station_name",
        "stage5_status", "stage5_record_eligibility", "stage5_record_eligible",
        "stage5_record_candidate_rank", "stage5_sources", "stage5_notes", "qc_flags",
        "stage2_flags", "stage3_flags", "stage4_flags", "stage5_flags", "provenance_flags",
    ]

    def m(cc: str, country: str, metric: str, held: int = 0) -> dict[str, object]:
        return {
            "country_code": cc, "country": country, "metric": metric,
            "master_status": "UNRESOLVED_REVIEW", "publishable": "no",
            "canonical_value_c": "", "canonical_date": "", "canonical_site": "",
            "canonical_station_id": "", "canonical_source": "", "canonical_source_type": "NONE_UNRESOLVED",
            "official_verified": "no", "official_anchor_id": "", "official_coverage_status": "",
            "ghcn_support_count": 0, "ghcn_candidate_tie_count": 1,
            "fallback_candidate_value_c": "", "fallback_candidate_events": "",
            "held_more_extreme_count": held, "held_more_extreme_events": "",
            "unresolved_reason": "RANK1_REVIEW_REMAINS", "notes": "",
        }

    masters = [
        m("CH", "China", "tmax_highest"),
        m("BK", "Bosnia and Herzegovina", "tmax_lowest"),
        m("GH", "Ghana", "tmax_highest"),
        m("TX", "Turkmenistan", "tmax_highest", held=1),
        m("CE", "Sri Lanka", "tmin_lowest"),
    ]
    cands = [
        {"country_code":"CH","country":"China","metric":"tmax_highest","value_c":"48.7","date":"2023-07-16","station_id":"CH1","station_name":"TURPAN","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":"SFLAG_S_SOURCE"},
        {"country_code":"BK","country":"Bosnia and Herzegovina","metric":"tmax_lowest","value_c":"-26.8","date":"1963-01-23","station_id":"BK1","station_name":"BJELASNICA","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":"SFLAG_G_SOURCE"},
        {"country_code":"GH","country":"Ghana","metric":"tmax_highest","value_c":"48.8","date":"1993-03-05","station_id":"GH1","station_name":"TAMALE","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":"SFLAG_S_SOURCE"},
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","value_c":"56.5","date":"1890-06-20","station_id":"TX1","station_name":"BAJRAMALY","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"HOLD_WMO_HEMISPHERE_CONFLICT","stage5_record_eligible":"no","stage5_record_candidate_rank":"","stage5_sources":"","stage5_notes":"","qc_flags":"ABOVE_WMO_EASTERN_HEMISPHERE_HIGH","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":""},
        {"country_code":"CE","country":"Sri Lanka","metric":"tmin_lowest","value_c":"-2.6","date":"1929-01-14","station_id":"CE1","station_name":"NUWARA ELIYA","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":"SFLAG_G_SOURCE"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mp = root / "master.csv"
        cp = root / "cands.csv"
        out = root / "out"
        with mp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=master_fields, delimiter=";")
            w.writeheader(); w.writerows(masters)
        with cp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=candidate_fields, delimiter=";")
            w.writeheader(); w.writerows(cands)
        summary = run(mp, cp, out)
        assert summary["resolved_in_stage7"] == 2, summary
        rows, _ = _read_csv(out / "world_country_record_master_stage7.csv", MASTER_REQUIRED)
        by = {(r["country_code"], r["metric"]): r for r in rows}
        assert by[("CH","tmax_highest")]["master_status"] == "OFFICIAL_COVERAGE_GAP"
        assert by[("CH","tmax_highest")]["canonical_value_c"] == "52.2"
        assert by[("BK","tmax_lowest")]["master_status"] == "GHCN_CANDIDATE"
        assert by[("GH","tmax_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert by[("TX","tmax_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert by[("CE","tmin_lowest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert (out / "resolved_stage7.csv").exists()
        assert (out / "world_country_record_master_unresolved_stage7.csv").exists()
    print("Stage-7 self-test: OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-input", type=Path)
    parser.add_argument("--candidate-input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.master_input is None or args.candidate_input is None or args.output_dir is None:
        parser.error("--master-input, --candidate-input and --output-dir are required unless --self-test is used")
    summary = run(args.master_input, args.candidate_input, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
