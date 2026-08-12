#!/usr/bin/env python3
"""Stage-8 resolution of selected Stage-7 unresolved country records using Wikipedia.

Wikipedia is used here only as an explicitly approved *secondary reference layer*.
It never changes or deletes the underlying GHCN observations and it never sets
``official_verified=yes``.  The canonical master may become publishable as
``SECONDARY_SOURCE_BACKED`` while the relation to GHCN (coverage gap, more-
extreme GHCN conflict, or direct support) remains explicit.

Only cases with a sufficiently clear, current Wikipedia record statement are
included. Cases where Wikipedia pages currently disagree materially remain
UNRESOLVED_REVIEW.
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

WIKI_WEATHER_RECORDS = "https://en.wikipedia.org/wiki/List_of_weather_records"
WIKI_SHAHRAK = "https://en.wikipedia.org/wiki/Shahrak_District"
WIKI_UTIRIK = "https://en.wikipedia.org/wiki/Utirik_Atoll"
WIKI_DONGOLA = "https://en.wikipedia.org/wiki/Dongola"
WIKI_NIUAFOOU = "https://en.wikipedia.org/wiki/Niuafo%CA%BBou"
WIKI_REPETEK = "https://en.wikipedia.org/wiki/Repetek_Biosphere_State_Reserve"
WIKI_POINTE_VELE = "https://en.wikipedia.org/wiki/Pointe_Vele_Airport"


@dataclass(frozen=True)
class WikipediaAnchor:
    reference_id: str
    country_code: str
    country: str
    metric: str
    value_c: float
    date: str
    site: str
    source: str
    note: str
    confidence: str = "HIGH"
    site_keywords: tuple[str, ...] = ()


# Deliberately small, conservative Stage-8 batch.  Values below are restricted
# to Wikipedia pages/search results that explicitly describe the national or
# territory-wide record.  Ambiguous/conflicting Wikipedia cases are not added.
WIKIPEDIA_ANCHORS: tuple[WikipediaAnchor, ...] = (
    WikipediaAnchor(
        "WIKI_AF_TMIN_SHAHRAK_MINUS52_2",
        "AF", "Afghanistan", "tmin_lowest", -52.2, "", "Shahrak",
        WIKI_SHAHRAK,
        "Wikipedia's Shahrak District article states that Afghanistan's lowest recorded temperature is -52.2 C at Shahrak; the date is not specified there.",
        "HIGH", ("SHAHRAK",),
    ),
    WikipediaAnchor(
        "WIKI_FJ_TMAX_VATUKOULA_37_4",
        "FJ", "Fiji", "tmax_highest", 37.4, "", "Vatukoula, Viti Levu",
        WIKI_WEATHER_RECORDS,
        "Wikipedia's List of weather records gives Fiji's national maximum as 37.4 C at Vatukoula. A separate current Wikipedia record table dates the value to 2003; Stage 8 leaves the exact day blank.",
        "MEDIUM", ("VATUKOULA",),
    ),
    WikipediaAnchor(
        "WIKI_LE_TMAX_HOUCHE_ZAHLE_44_3",
        "LE", "Lebanon", "tmax_highest", 44.3, "", "Houche Al Oumara / Zahle",
        WIKI_WEATHER_RECORDS,
        "Wikipedia's List of weather records gives Lebanon's national maximum as 44.3 C at Houche Al Oumara / Zahle. The underlying Wikipedia references include a Lebanese national report and station data; Stage 8 still classifies Wikipedia itself only as a secondary source.",
        "MEDIUM", ("HOUCHE", "OUMARA", "ZAHLE"),
    ),
    WikipediaAnchor(
        "WIKI_RM_TMAX_UTIRIK_35_6_2016",
        "RM", "Marshall Islands", "tmax_highest", 35.6, "2016-08-24", "Utirik Atoll",
        WIKI_UTIRIK,
        "Wikipedia's Utirik Atoll article states that 35.6 C on 24 Aug 2016 is the highest temperature recorded in the Marshall Islands.",
        "HIGH", ("UTIRIK", "UTRIK"),
    ),
    WikipediaAnchor(
        "WIKI_SU_TMAX_DONGOLA_49_7_2010",
        "SU", "Sudan", "tmax_highest", 49.7, "2010-06-22", "Dongola",
        WIKI_DONGOLA,
        "Wikipedia's Dongola article states that 49.7 C on 22 Jun 2010 is the highest temperature recorded in Sudan.",
        "HIGH", ("DONGOLA",),
    ),
    WikipediaAnchor(
        "WIKI_TN_TMAX_NIUAFOOU_35_5_2016",
        "TN", "Tonga", "tmax_highest", 35.5, "2016-02-01", "Niuafo'ou",
        WIKI_NIUAFOOU,
        "Wikipedia's Niuafo'ou article states that 35.5 C on 1 Feb 2016 is the highest temperature recorded in Tonga.",
        "HIGH", ("NIUAFO",),
    ),
    WikipediaAnchor(
        "WIKI_TX_TMAX_REPETEK_50_1_1983",
        "TX", "Turkmenistan", "tmax_highest", 50.1, "1983-07-28", "Repetek Biosphere State Reserve, Karakum Desert",
        WIKI_REPETEK,
        "Wikipedia's Repetek Biosphere State Reserve article states that 50.1 C on 28 Jul 1983 is the highest temperature recorded in Turkmenistan.",
        "HIGH", ("REPETEK",),
    ),
    WikipediaAnchor(
        "WIKI_WF_TMAX_FUTUNA_35_8_2016",
        "WF", "Wallis and Futuna [France]", "tmax_highest", 35.8, "2016-01-10", "Pointe Vele / Futuna Airport",
        WIKI_POINTE_VELE,
        "Wikipedia's Pointe Vele Airport article states that 35.8 C on 10 Jan 2016 is the highest temperature recorded in Wallis and Futuna.",
        "HIGH", ("FUTUNA", "POINTE", "VELE", "MAOPOOPO"),
    ),
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


def _is_more_extreme(metric: str, a: float, b: float) -> bool:
    """Return True when a is more extreme than b for the metric."""
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    if metric in {"tmax_highest", "tmin_highest"}:
        return a > b + 0.051
    return a < b - 0.051


def _exact_support(anchor: WikipediaAnchor, rows: list[dict[str, str]]) -> list[dict[str, str]]:
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


def _relation(anchor: WikipediaAnchor, group: list[dict[str, str]]) -> tuple[str, str]:
    exact = _exact_support(anchor, group)
    if exact:
        return "GHCN_MATCH", f"{len(exact)} GHCN candidate row(s) support the Wikipedia value/event."

    rank1 = _rank1(group)
    holds = _holds(group)
    comparison = rank1 + holds
    vals = [_float(r.get("value_c")) for r in comparison]
    vals = [v for v in vals if math.isfinite(v)]
    if not vals:
        return "GHCN_COVERAGE_GAP", "No comparable surviving GHCN candidate is available for this country+metric."

    more_extreme_ghcn = [v for v in vals if _is_more_extreme(anchor.metric, v, anchor.value_c)]
    if more_extreme_ghcn:
        x = max(more_extreme_ghcn) if anchor.metric in {"tmax_highest", "tmin_highest"} else min(more_extreme_ghcn)
        return "GHCN_MORE_EXTREME_THAN_WIKIPEDIA", f"A surviving/held GHCN value ({x:.1f} C) is more extreme than the Wikipedia reference ({anchor.value_c:.1f} C); raw observation is retained but the master follows the approved secondary reference."

    best = max(vals) if anchor.metric in {"tmax_highest", "tmin_highest"} else min(vals)
    if _is_more_extreme(anchor.metric, anchor.value_c, best):
        return "WIKIPEDIA_MORE_EXTREME_COVERAGE_GAP", f"Wikipedia reference ({anchor.value_c:.1f} C) is more extreme than the best surviving GHCN candidate ({best:.1f} C)."
    return "WIKIPEDIA_REPLACES_UNRESOLVED", "Wikipedia reference resolves the open master row; no exact GHCN event match was found."


def _join_unique(values: list[str]) -> str:
    return " | ".join(dict.fromkeys(v for v in values if v))


def run(master_input: Path, candidate_input: Path, output_dir: Path) -> dict[str, object]:
    master, master_fields = _read_csv(master_input, MASTER_REQUIRED)
    candidates, _candidate_fields = _read_csv(candidate_input, CANDIDATE_REQUIRED)
    groups = _candidate_groups(candidates)
    anchors = {(a.country_code, a.metric): a for a in WIKIPEDIA_ANCHORS}

    extra_fields = [
        "stage8_previous_master_status", "stage8_resolution", "stage8_resolution_code",
        "stage8_reference_id", "stage8_reference_type", "stage8_reference_confidence",
        "stage8_reference_relation", "stage8_reference_source", "stage8_reference_notes",
    ]
    out_fields = master_fields + [f for f in extra_fields if f not in master_fields]

    updated: list[dict[str, object]] = []
    resolved: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []

    for src in master:
        row: dict[str, object] = dict(src)
        key = (src.get("country_code", ""), src.get("metric", ""))
        previous = src.get("master_status", "")
        row.update({
            "stage8_previous_master_status": previous,
            "stage8_resolution": "CARRIED_FORWARD",
            "stage8_resolution_code": "",
            "stage8_reference_id": "",
            "stage8_reference_type": "",
            "stage8_reference_confidence": "",
            "stage8_reference_relation": "",
            "stage8_reference_source": "",
            "stage8_reference_notes": "",
        })

        anchor = anchors.get(key)
        if previous != "UNRESOLVED_REVIEW" or anchor is None:
            updated.append(row)
            continue

        group = groups.get(key, [])
        exact = _exact_support(anchor, group)
        relation, relation_note = _relation(anchor, group)

        row.update({
            "master_status": "SECONDARY_SOURCE_BACKED",
            "publishable": "yes",
            "canonical_value_c": f"{anchor.value_c:.1f}",
            "canonical_date": anchor.date,
            "canonical_site": anchor.site,
            "canonical_station_id": _join_unique([str(r.get("station_id", "")) for r in exact]),
            "canonical_source": anchor.source,
            "canonical_source_type": "SECONDARY_REFERENCE_WIKIPEDIA",
            "official_verified": "no",
            "ghcn_support_count": len(exact),
            "unresolved_reason": "",
            "notes": anchor.note + " Secondary reference accepted by project policy; not an official national-service verification.",
            "stage8_resolution": "RESOLVED",
            "stage8_resolution_code": "WIKIPEDIA_SECONDARY_REFERENCE_ACCEPTED",
            "stage8_reference_id": anchor.reference_id,
            "stage8_reference_type": "WIKIPEDIA_SECONDARY",
            "stage8_reference_confidence": anchor.confidence,
            "stage8_reference_relation": relation,
            "stage8_reference_source": anchor.source,
            "stage8_reference_notes": relation_note,
        })
        updated.append(row)
        resolved.append(row)
        decisions.append({
            "country_code": anchor.country_code,
            "country": src.get("country", anchor.country),
            "metric": anchor.metric,
            "previous_status": previous,
            "new_status": "SECONDARY_SOURCE_BACKED",
            "canonical_value_c": f"{anchor.value_c:.1f}",
            "canonical_date": anchor.date,
            "canonical_site": anchor.site,
            "reference_id": anchor.reference_id,
            "confidence": anchor.confidence,
            "relation_to_ghcn": relation,
            "source": anchor.source,
            "notes": anchor.note + " " + relation_note,
        })

    publishable = [r for r in updated if r.get("publishable") == "yes"]
    unresolved = [r for r in updated if r.get("master_status") == "UNRESOLVED_REVIEW"]

    decision_fields = [
        "country_code", "country", "metric", "previous_status", "new_status",
        "canonical_value_c", "canonical_date", "canonical_site", "reference_id",
        "confidence", "relation_to_ghcn", "source", "notes",
    ]
    anchor_fields = [
        "reference_id", "country_code", "country", "metric", "value_c", "date",
        "site", "source", "confidence", "note",
    ]
    anchor_rows = [
        {
            "reference_id": a.reference_id, "country_code": a.country_code, "country": a.country,
            "metric": a.metric, "value_c": f"{a.value_c:.1f}", "date": a.date,
            "site": a.site, "source": a.source, "confidence": a.confidence, "note": a.note,
        }
        for a in WIKIPEDIA_ANCHORS
    ]

    _write_csv(output_dir / "world_country_record_master_stage8.csv", updated, out_fields)
    _write_csv(output_dir / "world_country_record_master_publishable_stage8.csv", publishable, out_fields)
    _write_csv(output_dir / "world_country_record_master_unresolved_stage8.csv", unresolved, out_fields)
    _write_csv(output_dir / "resolved_stage8.csv", resolved, out_fields)
    _write_csv(output_dir / "resolution_decisions_stage8.csv", decisions, decision_fields)
    _write_csv(output_dir / "wikipedia_reference_anchors_stage8.csv", anchor_rows, anchor_fields)

    status_counts = Counter(str(r.get("master_status", "")) for r in updated)
    relation_counts = Counter(str(r.get("stage8_reference_relation", "")) for r in resolved)
    confidence_counts = Counter(str(r.get("stage8_reference_confidence", "")) for r in resolved)

    summary: dict[str, object] = {
        "schema_version": 1,
        "stage": "world_ghcn_country_record_wikipedia_resolution_stage8",
        "master_rows": len(updated),
        "stage7_unresolved_input_rows": sum(r.get("master_status") == "UNRESOLVED_REVIEW" for r in master),
        "wikipedia_anchor_rows": len(WIKIPEDIA_ANCHORS),
        "resolved_in_stage8": len(resolved),
        "unresolved_after_stage8": len(unresolved),
        "publishable_after_stage8": len(publishable),
        "master_status_counts": dict(sorted(status_counts.items())),
        "stage8_relation_counts": dict(sorted(relation_counts.items())),
        "stage8_confidence_counts": dict(sorted(confidence_counts.items())),
        "policy": "Wikipedia is an explicitly approved secondary reference only. It may make a master row publishable as SECONDARY_SOURCE_BACKED, but it never sets official_verified=yes and never deletes GHCN observations. Internally conflicting Wikipedia cases remain unresolved.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = [
        "# World GHCN country record master · Stage 8",
        "",
        "Stage 8 uses a deliberately small Wikipedia-based secondary-reference batch for selected Stage-7 unresolved records.",
        "",
        "## Ergebnis",
        f"- Stage-7 unresolved am Eingang: {summary['stage7_unresolved_input_rows']}",
        f"- Wikipedia-Referenzanker in dieser Stufe: {summary['wikipedia_anchor_rows']}",
        f"- In Stage 8 aufgelöst: {summary['resolved_in_stage8']}",
        f"- Danach weiterhin unresolved: {summary['unresolved_after_stage8']}",
        f"- Publishable nach Stage 8: {summary['publishable_after_stage8']}",
        "",
        "## Quellenpolitik",
        "- Wikipedia ist SECONDARY_SOURCE_BACKED, niemals OFFICIAL_SOURCE_BACKED.",
        "- official_verified bleibt bei diesen Zeilen immer no.",
        "- GHCN-Werte, die extremer als die Wikipedia-Referenz sind, werden nicht gelöscht; der Konflikt wird in stage8_reference_relation festgehalten.",
        "- Wikipedia-Fälle mit derzeit widersprüchlichen Angaben werden bewusst nicht in diese Stufe aufgenommen.",
        "",
        "## Stage-8-Anker",
    ]
    for a in WIKIPEDIA_ANCHORS:
        d = f" on {a.date}" if a.date else ""
        report.append(f"- {a.country_code} {a.metric}: {a.value_c:.1f} C at {a.site}{d} · confidence={a.confidence}")
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
        "stage7_previous_master_status", "stage7_resolution", "stage7_resolution_code",
        "stage7_resolution_source", "stage7_resolution_notes",
    ]
    candidate_fields = [
        "country_code", "country", "metric", "value_c", "date", "station_id", "station_name",
        "stage5_status", "stage5_record_eligibility", "stage5_record_eligible",
        "stage5_record_candidate_rank", "stage5_sources", "stage5_notes", "qc_flags",
        "stage2_flags", "stage3_flags", "stage4_flags", "stage5_flags", "provenance_flags",
    ]

    def m(cc: str, country: str, metric: str) -> dict[str, object]:
        return {
            "country_code": cc, "country": country, "metric": metric,
            "master_status": "UNRESOLVED_REVIEW", "publishable": "no",
            "canonical_value_c": "", "canonical_date": "", "canonical_site": "",
            "canonical_station_id": "", "canonical_source": "", "canonical_source_type": "NONE_UNRESOLVED",
            "official_verified": "no", "official_anchor_id": "", "official_coverage_status": "",
            "ghcn_support_count": 0, "ghcn_candidate_tie_count": 1,
            "fallback_candidate_value_c": "", "fallback_candidate_events": "",
            "held_more_extreme_count": 0, "held_more_extreme_events": "",
            "unresolved_reason": "RANK1_REVIEW_REMAINS", "notes": "",
            "stage7_previous_master_status": "UNRESOLVED_REVIEW", "stage7_resolution": "STILL_UNRESOLVED",
            "stage7_resolution_code": "REVIEW_NOT_YET_SOURCE_RESOLVED", "stage7_resolution_source": "",
            "stage7_resolution_notes": "",
        }

    masters = [
        m("AF", "Afghanistan", "tmin_lowest"),
        m("RM", "Marshall Islands", "tmax_highest"),
        m("GH", "Ghana", "tmax_highest"),
    ]
    cands = [
        {"country_code":"AF","country":"Afghanistan","metric":"tmin_lowest","value_c":"-28.5","date":"1984-02-20","station_id":"AF1","station_name":"NORTH-SALANG","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":""},
        {"country_code":"RM","country":"Marshall Islands","metric":"tmax_highest","value_c":"40.6","date":"1960-10-13","station_id":"RM1","station_name":"JABOR","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":""},
        {"country_code":"GH","country":"Ghana","metric":"tmax_highest","value_c":"48.8","date":"1993-03-05","station_id":"GH1","station_name":"TAMALE","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":"","qc_flags":"ISOLATED_COUNTRY_RANK1_GAP","stage2_flags":"","stage3_flags":"","stage4_flags":"","stage5_flags":"","provenance_flags":""},
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
        assert summary["resolved_in_stage8"] == 2, summary
        rows, _ = _read_csv(out / "world_country_record_master_stage8.csv", MASTER_REQUIRED)
        by = {(r["country_code"], r["metric"]): r for r in rows}
        assert by[("AF","tmin_lowest")]["master_status"] == "SECONDARY_SOURCE_BACKED"
        assert by[("AF","tmin_lowest")]["canonical_value_c"] == "-52.2"
        assert by[("AF","tmin_lowest")]["official_verified"] == "no"
        assert by[("RM","tmax_highest")]["canonical_value_c"] == "35.6"
        assert by[("GH","tmax_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert (out / "wikipedia_reference_anchors_stage8.csv").exists()
        assert (out / "world_country_record_master_unresolved_stage8.csv").exists()
    print("Stage-8 self-test: OK")


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
