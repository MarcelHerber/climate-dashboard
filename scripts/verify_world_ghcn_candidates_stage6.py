#!/usr/bin/env python3
"""Stage-6 canonical master table for world GHCN country temperature records.

Stage 6 does NOT perform another broad observation filter. It converts the
Stage-5 observation/record-eligibility layer into a single canonical country
record reference, while keeping uncertainty explicit.

Priority per country_code + metric:
  1) authoritative official/WMO/national-service anchor;
  2) source-backed GHCN event;
  3) clean GHCN record candidate;
  4) unresolved if a more-extreme hold or REVIEW/REVIEW_CRITICAL remains.

Main master statuses:
  OFFICIAL_SOURCE_BACKED  - official event is also represented in GHCN;
  OFFICIAL_COVERAGE_GAP   - official record is authoritative but absent from
                            the surviving GHCN candidate pool;
  GHCN_SOURCE_BACKED      - no official anchor, but the GHCN rank-1 event is
                            source-backed by earlier QC;
  GHCN_CANDIDATE          - clean, eligible GHCN rank-1 candidate;
  UNRESOLVED_REVIEW       - do not publish a canonical value yet.

Important: an OFFICIAL_COVERAGE_GAP is still publishable because the canonical
value comes from the official source, not from GHCN. Holds never delete raw
observations and never silently promote a lower fallback candidate to an
'official' record.
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

import verify_world_ghcn_candidates_stage4 as stage4
import verify_world_ghcn_candidates_stage5 as stage5

REQUIRED_COLUMNS = {
    "country_code", "country", "metric", "value_c", "date", "station_id",
    "station_name", "stage5_status", "stage5_record_eligibility",
    "stage5_record_eligible", "stage5_record_candidate_rank",
}

METRIC_DIRECTION = {
    "tmax_highest": "desc",
    "tmin_highest": "desc",
    "tmin_lowest": "asc",
    "tmax_lowest": "asc",
}

MASTER_STATUSES = {
    "OFFICIAL_SOURCE_BACKED",
    "OFFICIAL_COVERAGE_GAP",
    "GHCN_SOURCE_BACKED",
    "GHCN_CANDIDATE",
    "UNRESOLVED_REVIEW",
}

PUBLISHABLE_STATUSES = {
    "OFFICIAL_SOURCE_BACKED",
    "OFFICIAL_COVERAGE_GAP",
    "GHCN_SOURCE_BACKED",
    "GHCN_CANDIDATE",
}


@dataclass(frozen=True)
class CanonicalAnchor:
    anchor_id: str
    country_code: str
    country: str
    metric: str
    value_c: float
    date: str
    year: int
    site: str
    source: str
    note: str
    site_keywords: tuple[str, ...]
    anchor_generation: str


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


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader)


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _metric_more_extreme(metric: str, a: float, b: float) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    if METRIC_DIRECTION.get(metric) == "asc":
        return a < b - 0.051
    return a > b + 0.051


def _row_sort_key(row: dict[str, object], metric: str) -> tuple[float, str, str]:
    value = _float(row.get("value_c"))
    if METRIC_DIRECTION.get(metric) == "asc":
        value = -value
    return value, str(row.get("date", "")), str(row.get("station_id", ""))


def _official_anchors() -> list[CanonicalAnchor]:
    # Stage 5 overrides a Stage-4 anchor for the same country+metric. This is
    # intentional: it lets later authoritative updates replace an older anchor
    # without editing historical QC stages.
    merged: dict[tuple[str, str], CanonicalAnchor] = {}

    for a in stage4.COUNTRY_RECORD_ANCHORS:
        year = int(a.date[:4]) if a.date and a.date[:4].isdigit() else 0
        merged[(a.country_code, a.metric)] = CanonicalAnchor(
            a.anchor_id, a.country_code, a.country, a.metric, float(a.value_c),
            a.date, year, a.site, a.source, a.note, tuple(a.site_keywords),
            "stage4",
        )

    for a in stage5.STAGE5_ANCHORS:
        merged[(a.country_code, a.metric)] = CanonicalAnchor(
            a.anchor_id, a.country_code, a.country, a.metric, float(a.value_c),
            a.event_date, int(a.event_year or 0), a.site, a.source, a.note,
            tuple(a.site_keywords), "stage5",
        )

    return [merged[k] for k in sorted(merged)]


def _anchor_matches_row(anchor: CanonicalAnchor, row: dict[str, object]) -> bool:
    if str(row.get("country_code")) != anchor.country_code or str(row.get("metric")) != anchor.metric:
        return False
    if not _same_value(_float(row.get("value_c")), anchor.value_c):
        return False
    date = str(row.get("date", ""))
    if anchor.date and date != anchor.date:
        return False
    if anchor.year and date[:4].isdigit() and int(date[:4]) != anchor.year:
        return False
    if anchor.site_keywords:
        hay = _norm(f"{row.get('station_name','')} {row.get('station_id','')}")
        if not any(_norm(k) in hay for k in anchor.site_keywords):
            return False
    return True


def _event_label(row: dict[str, object]) -> str:
    return (
        f"{row.get('value_c')} C | {row.get('date')} | "
        f"{row.get('station_name')} [{row.get('station_id')}]"
    )


def _group_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        groups[(r.get("country_code", ""), r.get("metric", ""))].append(r)
    return groups


def _rank1_candidates(group: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [
        r for r in group
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and r.get("stage5_record_eligible") == "yes"
        and _int(r.get("stage5_record_candidate_rank")) == 1
    ]
    metric = group[0].get("metric", "") if group else ""
    return sorted(rows, key=lambda r: _row_sort_key(r, metric), reverse=True)


def _held_rows(group: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in group
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and str(r.get("stage5_record_eligibility", "")).startswith("HOLD")
    ]


def _anchor_audit(anchor: CanonicalAnchor, group: list[dict[str, str]]) -> dict[str, object]:
    surviving = [r for r in group if r.get("stage5_status") != "REJECT_CONFIRMED"]
    exact = [r for r in surviving if _anchor_matches_row(anchor, r)]
    value_match = [r for r in surviving if _same_value(_float(r.get("value_c")), anchor.value_c)]
    more_extreme = [r for r in surviving if _metric_more_extreme(anchor.metric, _float(r.get("value_c")), anchor.value_c)]

    if exact:
        coverage = "OFFICIAL_EVENT_PRESENT_IN_GHCN"
    elif value_match:
        coverage = "OFFICIAL_VALUE_PRESENT_EVENT_UNRESOLVED"
    else:
        coverage = "OFFICIAL_COVERAGE_GAP"

    return {
        "anchor_id": anchor.anchor_id,
        "country_code": anchor.country_code,
        "country": anchor.country,
        "metric": anchor.metric,
        "official_value_c": f"{anchor.value_c:.1f}",
        "official_date": anchor.date,
        "official_year": anchor.year or "",
        "official_site": anchor.site,
        "official_source": anchor.source,
        "official_note": anchor.note,
        "anchor_generation": anchor.anchor_generation,
        "coverage_status": coverage,
        "exact_event_present": "yes" if exact else "no",
        "exact_event_ghcn_rows": len(exact),
        "official_value_present_anywhere": "yes" if value_match else "no",
        "ghcn_more_extreme_surviving_rows": len(more_extreme),
        "ghcn_more_extreme_examples": " | ".join(_event_label(r) for r in more_extreme[:6]),
    }


def _build_master(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    groups = _group_rows(rows)
    anchors = _official_anchors()
    anchor_by_key = {(a.country_code, a.metric): a for a in anchors}

    keys = sorted(set(groups) | set(anchor_by_key))
    master: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    anchor_audits: list[dict[str, object]] = []

    for cc, metric in keys:
        group = groups.get((cc, metric), [])
        surviving = [r for r in group if r.get("stage5_status") != "REJECT_CONFIRMED"]
        rank1 = _rank1_candidates(group)
        holds = _held_rows(group)
        anchor = anchor_by_key.get((cc, metric))
        country = (group[0].get("country", "") if group else "") or (anchor.country if anchor else "")

        fallback_value = rank1[0].get("value_c", "") if rank1 else ""
        fallback_events = " | ".join(_event_label(r) for r in rank1)
        held_values = " | ".join(_event_label(r) for r in holds[:12])

        base: dict[str, object] = {
            "country_code": cc,
            "country": country,
            "metric": metric,
            "master_status": "",
            "publishable": "no",
            "canonical_value_c": "",
            "canonical_date": "",
            "canonical_site": "",
            "canonical_station_id": "",
            "canonical_source": "",
            "canonical_source_type": "",
            "official_verified": "no",
            "official_anchor_id": "",
            "official_coverage_status": "",
            "ghcn_support_count": 0,
            "ghcn_candidate_tie_count": len(rank1),
            "fallback_candidate_value_c": fallback_value,
            "fallback_candidate_events": fallback_events,
            "held_more_extreme_count": len(holds),
            "held_more_extreme_events": held_values,
            "unresolved_reason": "",
            "notes": "",
        }

        if anchor is not None:
            audit = _anchor_audit(anchor, group)
            anchor_audits.append(audit)
            exact = [r for r in surviving if _anchor_matches_row(anchor, r)]

            status = (
                "OFFICIAL_SOURCE_BACKED"
                if audit["coverage_status"] == "OFFICIAL_EVENT_PRESENT_IN_GHCN"
                else "OFFICIAL_COVERAGE_GAP"
            )
            base.update({
                "master_status": status,
                "publishable": "yes",
                "canonical_value_c": f"{anchor.value_c:.1f}",
                "canonical_date": anchor.date or (str(anchor.year) if anchor.year else ""),
                "canonical_site": anchor.site,
                "canonical_station_id": " | ".join(str(r.get("station_id", "")) for r in exact),
                "canonical_source": anchor.source,
                "canonical_source_type": "OFFICIAL_ANCHOR",
                "official_verified": "yes",
                "official_anchor_id": anchor.anchor_id,
                "official_coverage_status": audit["coverage_status"],
                "ghcn_support_count": len(exact),
                "notes": anchor.note,
            })
            events.append({
                "country_code": cc,
                "country": country,
                "metric": metric,
                "event_role": "CANONICAL_OFFICIAL",
                "value_c": f"{anchor.value_c:.1f}",
                "date": anchor.date or (str(anchor.year) if anchor.year else ""),
                "site": anchor.site,
                "station_id": "",
                "source": anchor.source,
                "status": status,
                "note": anchor.note,
            })
            for r in exact:
                events.append({
                    "country_code": cc,
                    "country": country,
                    "metric": metric,
                    "event_role": "GHCN_SUPPORT_FOR_OFFICIAL",
                    "value_c": r.get("value_c", ""),
                    "date": r.get("date", ""),
                    "site": r.get("station_name", ""),
                    "station_id": r.get("station_id", ""),
                    "source": r.get("stage5_sources", "") or "GHCN-Daily",
                    "status": r.get("stage5_status", ""),
                    "note": r.get("stage5_notes", ""),
                })

        elif holds:
            base.update({
                "master_status": "UNRESOLVED_REVIEW",
                "publishable": "no",
                "canonical_source_type": "NONE_UNRESOLVED",
                "unresolved_reason": "MORE_EXTREME_RECORD_HOLD_EXISTS",
                "notes": "A more-extreme Stage-5 observation is intentionally held from record selection; do not silently promote the lower fallback candidate.",
            })
            for r in holds:
                events.append({
                    "country_code": cc,
                    "country": country,
                    "metric": metric,
                    "event_role": "HELD_MORE_EXTREME",
                    "value_c": r.get("value_c", ""),
                    "date": r.get("date", ""),
                    "site": r.get("station_name", ""),
                    "station_id": r.get("station_id", ""),
                    "source": r.get("stage5_sources", "") or "GHCN-Daily",
                    "status": r.get("stage5_record_eligibility", ""),
                    "note": r.get("stage5_notes", ""),
                })
            for r in rank1:
                events.append({
                    "country_code": cc,
                    "country": country,
                    "metric": metric,
                    "event_role": "FALLBACK_CANDIDATE_NOT_CANONICAL",
                    "value_c": r.get("value_c", ""),
                    "date": r.get("date", ""),
                    "site": r.get("station_name", ""),
                    "station_id": r.get("station_id", ""),
                    "source": r.get("stage5_sources", "") or "GHCN-Daily",
                    "status": r.get("stage5_status", ""),
                    "note": "Fallback only while a more-extreme held observation remains unresolved.",
                })

        elif not rank1:
            base.update({
                "master_status": "UNRESOLVED_REVIEW",
                "publishable": "no",
                "canonical_source_type": "NONE_UNRESOLVED",
                "unresolved_reason": "NO_RECORD_ELIGIBLE_CANDIDATE",
                "notes": "No surviving Stage-5 record-eligible rank-1 candidate is available.",
            })

        else:
            review_rank1 = [r for r in rank1 if r.get("stage5_status") in {"REVIEW", "REVIEW_CRITICAL"}]
            source_backed_rank1 = [
                r for r in rank1
                if r.get("stage5_status") == "PASS_SOURCE_BACKED"
                or r.get("stage5_record_eligibility") == "SOURCE_BACKED_RECORD"
            ]

            if review_rank1:
                status = "UNRESOLVED_REVIEW"
                publishable = "no"
                value = ""
                date = ""
                site = ""
                station_id = ""
                source = ""
                source_type = "NONE_UNRESOLVED"
                unresolved = "RANK1_REVIEW_REMAINS"
                notes = "The best eligible Stage-5 record candidate still carries REVIEW/REVIEW_CRITICAL."
            else:
                status = "GHCN_SOURCE_BACKED" if source_backed_rank1 else "GHCN_CANDIDATE"
                publishable = "yes"
                value = rank1[0].get("value_c", "")
                date = " | ".join(str(r.get("date", "")) for r in rank1)
                site = " | ".join(str(r.get("station_name", "")) for r in rank1)
                station_id = " | ".join(str(r.get("station_id", "")) for r in rank1)
                source = " | ".join(
                    dict.fromkeys((r.get("stage5_sources", "") or "GHCN-Daily") for r in rank1)
                )
                source_type = "GHCN_SOURCE_BACKED" if source_backed_rank1 else "GHCN_CANDIDATE"
                unresolved = ""
                notes = (
                    "No curated official anchor exists for this country/metric in Stage 6; "
                    "canonical value is the clean Stage-5 GHCN rank-1 candidate."
                )

            base.update({
                "master_status": status,
                "publishable": publishable,
                "canonical_value_c": value,
                "canonical_date": date,
                "canonical_site": site,
                "canonical_station_id": station_id,
                "canonical_source": source,
                "canonical_source_type": source_type,
                "unresolved_reason": unresolved,
                "notes": notes,
            })

            role = "CANONICAL_GHCN" if status != "UNRESOLVED_REVIEW" else "REVIEW_RANK1_NOT_CANONICAL"
            for r in rank1:
                events.append({
                    "country_code": cc,
                    "country": country,
                    "metric": metric,
                    "event_role": role,
                    "value_c": r.get("value_c", ""),
                    "date": r.get("date", ""),
                    "site": r.get("station_name", ""),
                    "station_id": r.get("station_id", ""),
                    "source": r.get("stage5_sources", "") or "GHCN-Daily",
                    "status": r.get("stage5_status", ""),
                    "note": r.get("stage5_notes", ""),
                })

        assert base["master_status"] in MASTER_STATUSES
        master.append(base)

    return master, events, anchor_audits


def _render_report(master: list[dict[str, object]], audits: list[dict[str, object]]) -> str:
    counts = Counter(str(r["master_status"]) for r in master)
    unresolved = [r for r in master if r["master_status"] == "UNRESOLVED_REVIEW"]
    gaps = [r for r in master if r["master_status"] == "OFFICIAL_COVERAGE_GAP"]
    official = [r for r in master if str(r["master_status"]).startswith("OFFICIAL_")]
    publishable = [r for r in master if r["publishable"] == "yes"]

    lines = [
        "# World GHCN country record master · Stage 6",
        "",
        "Stage 6 ist die kanonische Master-Schicht. Sie filtert keine weitere Massenbeobachtung, sondern entscheidet pro Land/GHCN-Code und Extremtyp, welche Referenz veröffentlicht werden darf.",
        "",
        "## Architektur",
        "- Offizielle WMO-/Nationaldienst-Anker haben Vorrang vor GHCN-Kandidaten.",
        "- Ein offizieller Coverage Gap bleibt publishable, weil der Wert aus der offiziellen Quelle kommt.",
        "- Ein HOLD ohne offiziellen Anker erzeugt UNRESOLVED_REVIEW; ein niedrigerer GHCN-Fallback wird nicht stillschweigend zum Rekord erklärt.",
        "- GHCN-Gleichstände bleiben als mehrere Event-Zeilen erhalten; die Master-Tabelle bleibt eine Zeile pro Land/Extremtyp.",
        "",
        "## Ergebnis",
        f"- Master-Zeilen: {len(master):,}",
        f"- Publishable: {len(publishable):,}",
        f"- Unresolved: {len(unresolved):,}",
        f"- Offizielle Master-Zeilen: {len(official):,}",
        f"- Offizielle Coverage Gaps: {len(gaps):,}",
        "",
        "### Status",
    ]
    for k in sorted(counts):
        lines.append(f"- {k}: {counts[k]:,}")

    lines += ["", "## Offizielle Coverage Gaps"]
    if gaps:
        for r in gaps:
            lines.append(
                f"- {r['country_code']} | {r['metric']} | {r['canonical_value_c']} °C | "
                f"{r['canonical_site']} | {r['official_anchor_id']}"
            )
    else:
        lines.append("- Keine.")

    lines += ["", "## Unresolved Review · Priorität"]
    for r in unresolved[:100]:
        lines.append(
            f"- {r['country_code']} | {r['metric']} | reason={r['unresolved_reason']} | "
            f"fallback={r['fallback_candidate_value_c'] or '-'} | held={r['held_more_extreme_count']}"
        )

    lines += ["", "## Offizielle Anker-Audit"]
    for a in audits:
        lines.append(
            f"- {a['country_code']} | {a['metric']} | {a['official_value_c']} °C | "
            f"{a['coverage_status']} | more-extreme-GHCN={a['ghcn_more_extreme_surviving_rows']}"
        )

    lines += [
        "",
        "## Nächster Schritt",
        "Erst nach Kontrolle dieses Stage-6-Masters sollte die 2026-Live-Schicht gegen die kanonische Baseline verglichen werden. Stage 6 selbst verändert keine 2026-Daten.",
        "",
    ]
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    rows = _read_rows(input_path)
    master, events, audits = _build_master(rows)
    output_dir.mkdir(parents=True, exist_ok=True)

    master_fields = [
        "country_code", "country", "metric", "master_status", "publishable",
        "canonical_value_c", "canonical_date", "canonical_site", "canonical_station_id",
        "canonical_source", "canonical_source_type", "official_verified",
        "official_anchor_id", "official_coverage_status", "ghcn_support_count",
        "ghcn_candidate_tie_count", "fallback_candidate_value_c", "fallback_candidate_events",
        "held_more_extreme_count", "held_more_extreme_events", "unresolved_reason", "notes",
    ]
    event_fields = [
        "country_code", "country", "metric", "event_role", "value_c", "date",
        "site", "station_id", "source", "status", "note",
    ]
    audit_fields = [
        "anchor_id", "country_code", "country", "metric", "official_value_c",
        "official_date", "official_year", "official_site", "official_source",
        "official_note", "anchor_generation", "coverage_status", "exact_event_present",
        "exact_event_ghcn_rows", "official_value_present_anywhere",
        "ghcn_more_extreme_surviving_rows", "ghcn_more_extreme_examples",
    ]

    _write_csv(output_dir / "world_country_record_master_stage6.csv", master, master_fields)
    _write_csv(output_dir / "world_country_record_events_stage6.csv", events, event_fields)
    _write_csv(
        output_dir / "world_country_record_master_publishable_stage6.csv",
        [r for r in master if r["publishable"] == "yes"], master_fields,
    )
    _write_csv(
        output_dir / "world_country_record_master_unresolved_stage6.csv",
        [r for r in master if r["master_status"] == "UNRESOLVED_REVIEW"], master_fields,
    )
    _write_csv(output_dir / "official_anchor_overlay_stage6.csv", audits, audit_fields)

    counts = Counter(str(r["master_status"]) for r in master)
    summary: dict[str, object] = {
        "schema_version": 1,
        "stage": "world_ghcn_country_record_master_stage6",
        "input_rows": len(rows),
        "country_metric_master_rows": len(master),
        "master_status_counts": dict(sorted(counts.items())),
        "publishable_master_rows": sum(r["publishable"] == "yes" for r in master),
        "unresolved_master_rows": sum(r["master_status"] == "UNRESOLVED_REVIEW" for r in master),
        "official_anchor_rows": len(audits),
        "official_coverage_gap_rows": sum(r["master_status"] == "OFFICIAL_COVERAGE_GAP" for r in master),
        "event_rows": len(events),
        "architecture": "One canonical master row per country_code+metric; official anchors override GHCN; unresolved holds never silently promote fallback candidates.",
        "publish_policy": "Publish official anchors even with GHCN coverage gaps; publish clean GHCN candidates only when rank-1 has no unresolved review/hold.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "qc_report.md").write_text(_render_report(master, audits), encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "value_c", "date", "station_id", "station_name",
        "stage5_status", "stage5_record_eligibility", "stage5_record_eligible",
        "stage5_record_candidate_rank", "stage5_sources", "stage5_notes",
    ]
    sample = [
        # Mexico: official Stage-5 anchor must override held old GHCN high and a lower fallback.
        {"country_code":"MX","country":"Mexico","metric":"tmax_highest","value_c":"56.7","date":"1949-08-20","station_id":"MX_OLD","station_name":"MEXICALI SMN","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"HOLD_OFFICIAL_CONFLICT","stage5_record_eligible":"no","stage5_record_candidate_rank":"","stage5_sources":"GHCN","stage5_notes":"hold"},
        {"country_code":"MX","country":"Mexico","metric":"tmax_highest","value_c":"51.8","date":"1998-06-01","station_id":"MX_NEXT","station_name":"NEXT","stage5_status":"PASS_PRELIMINARY","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":""},
        # Turkmenistan: no official country anchor in curated layer; hold prevents silent 49.1 promotion.
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","value_c":"56.5","date":"1890-06-20","station_id":"TX_BAJ","station_name":"BAJRAMALY","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"HOLD_WMO_HEMISPHERE_CONFLICT","stage5_record_eligible":"no","stage5_record_candidate_rank":"","stage5_sources":"","stage5_notes":""},
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","value_c":"49.1","date":"1995-07-12","station_id":"TX_NEXT","station_name":"BAKHERDEN","stage5_status":"PASS_PRELIMINARY","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":""},
        # Ordinary clean GHCN candidate.
        {"country_code":"BA","country":"Bahrain","metric":"tmax_highest","value_c":"47.5","date":"2000-07-15","station_id":"BA1","station_name":"BAHRAIN","stage5_status":"PASS_PRELIMINARY","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":""},
        # Rank-1 review must not publish.
        {"country_code":"BF","country":"Bahamas, The","metric":"tmax_highest","value_c":"38.2","date":"2024-07-25","station_id":"BF1","station_name":"NASSAU","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"","stage5_notes":""},
        # Australia official event is represented exactly and must be source-backed official.
        {"country_code":"AS","country":"Australia","metric":"tmax_highest","value_c":"50.7","date":"1960-01-02","station_id":"AS_OOD","station_name":"OODNADATTA AIRPORT","stage5_status":"PASS_SOURCE_BACKED","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1","stage5_sources":"WMO","stage5_notes":"verified"},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            w.writeheader(); w.writerows(sample)
        out = root / "out"
        summary = run(src, out)
        with (out / "world_country_record_master_stage6.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            master = list(csv.DictReader(handle, delimiter=";"))
        by_key = {(r["country_code"], r["metric"]): r for r in master}

        assert by_key[("MX", "tmax_highest")]["master_status"] == "OFFICIAL_COVERAGE_GAP"
        assert by_key[("MX", "tmax_highest")]["canonical_value_c"] == "52.7"
        assert by_key[("MX", "tmax_highest")]["publishable"] == "yes"
        assert by_key[("TX", "tmax_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert by_key[("TX", "tmax_highest")]["canonical_value_c"] == ""
        assert by_key[("TX", "tmax_highest")]["fallback_candidate_value_c"] == "49.1"
        assert by_key[("BA", "tmax_highest")]["master_status"] == "GHCN_CANDIDATE"
        assert by_key[("BA", "tmax_highest")]["canonical_value_c"] == "47.5"
        assert by_key[("BF", "tmax_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert by_key[("AS", "tmax_highest")]["master_status"] == "OFFICIAL_SOURCE_BACKED"
        assert by_key[("AS", "tmax_highest")]["canonical_value_c"] == "50.7"
        assert summary["country_metric_master_rows"] >= 5
        assert (out / "world_country_record_events_stage6.csv").exists()
        assert (out / "official_anchor_overlay_stage6.csv").exists()
        assert (out / "world_country_record_master_publishable_stage6.csv").exists()
        assert (out / "world_country_record_master_unresolved_stage6.csv").exists()

    print("SELF-TEST OK")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if not args.self_test and (args.input is None or args.output_dir is None):
        p.error("--input and --output-dir are required unless --self-test is used")
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
