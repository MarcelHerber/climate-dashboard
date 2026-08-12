#!/usr/bin/env python3
"""Stage-5 QC / record adjudication for world GHCN country extremes.

Stage 5 builds on Stage 4's separation between observation validity and
country-record completeness. It focuses on the highest-priority unresolved
cases from the Stage-4 log:

* Ireland: reject the GHCN Phoenix Park 33.5 C / 1876 observation because
  Met Eireann states that 33.0 C in 2022 was Phoenix Park's highest shaded-air
  temperature since observations began there in the early 1800s, while the
  national record remains 33.3 C at Kilkenny Castle (1887).
* Mexico: use WMO's 2026 State-of-the-Climate reporting that 52.7 C at
  Mexicali in 2025 is a new Mexican national record. Older GHCN values above
  that threshold are retained as observations but excluded/held from the
  official-record candidate ranking unless independently verified.
* Turkmenistan: keep the 56.5 C Bajramaly observation in the clean observation
  pool, but hold it out of the official-record candidate ranking because it
  exceeds the WMO-published Eastern-Hemisphere record of 55.0 C.
* Pacific 39.0 C cluster: Fiji/Tokelau/Tonga exact 39.0 C repeated-value rows
  from 1979-1981 are kept as observations but held out of the official-record
  ranking pending event-specific source verification.

The output therefore has TWO rankings:
  - stage5_rank: clean-observation country ranking after confirmed rejects;
  - stage5_record_candidate_rank: ranking only among rows currently eligible
    to serve as record candidates.

This is deliberately conservative: 'hold from record ranking' is not the same
as 'bad observation'.
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

# Authoritative / primary sources used by this stage.
MET_EIREANN_PHOENIX_2022 = "https://www.met.ie/temperature-records-broken-as-met-eireann-establish-new-climate-services-division"
MET_EIREANN_KILKENNY_2026 = "https://www.met.ie/139th-anniversary-of-irelands-hottest-day"
WMO_LAC_2025_REPORT_NEWS = "https://public.wmo.int/news/media-centre/rising-land-and-ocean-temperatures-wilder-water-cycle-glacier-retreat-hit-latin-america-and"
WMO_RECORD_TABLE_2025 = "https://public.wmo.int/sites/default/files/2025-07/Table_Records_25Jul2025.pdf"
NOAA_GHCN_README = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt"
FIJI_CLIMATE_SUMMARIES = "https://www.met.gov.fj/climate-services/fiji-climate-summaries/"

REQUIRED_COLUMNS = {
    "country_code", "country", "metric", "value_c", "date", "station_id",
    "station_name", "stage4_status", "stage4_rank",
}

METRIC_DIRECTION = {
    "tmax_highest": "desc",
    "tmin_highest": "desc",
    "tmin_lowest": "asc",
    "tmax_lowest": "asc",
}

RECORD_ELIGIBLE = {"ELIGIBLE_CANDIDATE", "SOURCE_BACKED_RECORD"}


@dataclass(frozen=True)
class OfficialRecordAnchor:
    anchor_id: str
    country_code: str
    country: str
    metric: str
    value_c: float
    site: str
    event_date: str
    event_year: int
    source: str
    note: str
    site_keywords: tuple[str, ...] = ()


STAGE5_ANCHORS: tuple[OfficialRecordAnchor, ...] = (
    OfficialRecordAnchor(
        "MET_EIREANN_IE_TMAX_1887", "EI", "Ireland", "tmax_highest", 33.3,
        "Kilkenny Castle", "1887-06-26", 1887, MET_EIREANN_KILKENNY_2026,
        "Met Eireann reconfirmed 33.3 C at Kilkenny Castle on 26 Jun 1887 as Ireland's all-time highest air temperature after a 2025 review.",
        ("KILKENNY",),
    ),
    OfficialRecordAnchor(
        "WMO_MX_TMAX_2025", "MX", "Mexico", "tmax_highest", 52.7,
        "Mexicali", "", 2025, WMO_LAC_2025_REPORT_NEWS,
        "WMO State-of-the-Climate reporting identifies 52.7 C at Mexicali in 2025 as a new Mexican national record.",
        ("MEXICALI",),
    ),
)


@dataclass(frozen=True)
class Decision:
    observation_status: str = ""
    record_eligibility: str = ""
    code: str = ""
    note: str = ""
    source: str = ""
    priority: int = 0


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


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fields = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - set(fields)
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader), fields


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _row_key(row: dict[str, object]) -> tuple[str, str]:
    return str(row.get("country_code", "")), str(row.get("metric", ""))


def _sort_group(rows: list[dict[str, object]], metric: str) -> list[dict[str, object]]:
    reverse = METRIC_DIRECTION.get(metric, "desc") == "desc"
    return sorted(
        rows,
        key=lambda r: (
            _float(r.get("value_c")),
            str(r.get("date", "")),
            str(r.get("station_id", "")),
        ),
        reverse=reverse,
    )


def _tie_rank(rows: list[dict[str, object]], rank_field: str, extreme_field: str) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        groups[_row_key(r)].append(dict(r))

    out: list[dict[str, object]] = []
    for key in sorted(groups):
        metric = key[1]
        ordered = _sort_group(groups[key], metric)
        distinct_values: list[float] = []
        for r in ordered:
            v = _float(r.get("value_c"))
            rank = None
            for i, seen in enumerate(distinct_values, start=1):
                if _same_value(v, seen):
                    rank = i
                    break
            if rank is None:
                distinct_values.append(v)
                rank = len(distinct_values)
            r[rank_field] = rank
            r[extreme_field] = "yes" if rank == 1 else "no"
            out.append(r)
    return out


def _anchor_matches_row(anchor: OfficialRecordAnchor, row: dict[str, object]) -> bool:
    if _row_key(row) != (anchor.country_code, anchor.metric):
        return False
    if not _same_value(_float(row.get("value_c")), anchor.value_c):
        return False
    if anchor.event_date and str(row.get("date", "")) != anchor.event_date:
        return False
    if anchor.event_year and str(row.get("date", ""))[:4].isdigit():
        if int(str(row.get("date"))[:4]) != anchor.event_year:
            return False
    hay = _norm(f"{row.get('station_name','')} {row.get('station_id','')}")
    return not anchor.site_keywords or any(_norm(k) in hay for k in anchor.site_keywords)


def _initial_record_eligibility(row: dict[str, object]) -> str:
    inherited_record = str(row.get("stage4_country_record_status", "")).strip()
    inherited_status = str(row.get("stage4_status", "PASS_PRELIMINARY")).strip()
    if inherited_status == "REJECT_CONFIRMED":
        return "NOT_ELIGIBLE_REJECTED_OBSERVATION"
    if inherited_record == "OFFICIAL_COVERAGE_GAP":
        return "OFFICIAL_COVERAGE_GAP"
    if inherited_record == "GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR":
        return "HOLD_OFFICIAL_CONFLICT"
    if inherited_status == "PASS_SOURCE_BACKED":
        return "ELIGIBLE_CANDIDATE"
    return "ELIGIBLE_CANDIDATE"


def _stage5_decisions(row: dict[str, object]) -> list[Decision]:
    cc, metric = _row_key(row)
    v = _float(row.get("value_c"))
    date = str(row.get("date", ""))
    station_id = str(row.get("station_id", ""))
    station_name = _norm(row.get("station_name", ""))
    first_date = str(row.get("first_date", date))
    last_date = str(row.get("last_date", date))
    tie_count = _int(row.get("tie_count"), 1)
    out: list[Decision] = []

    # Ireland: this is a direct station-history contradiction, not merely a
    # national-record ceiling issue. Met Eireann said Phoenix Park's 33.0 C in
    # July 2022 was its highest shaded-air temperature since observations began
    # there in the early 1800s. Therefore 33.5 C at the same site in 1876 is
    # excluded as a confirmed bad record observation for this application.
    if (
        cc == "EI" and metric == "tmax_highest" and station_id == "EI000003969"
        and _same_value(v, 33.5) and date == "1876-07-16" and "PHOENIX PARK" in station_name
    ):
        out.append(Decision(
            observation_status="REJECT_CONFIRMED",
            record_eligibility="NOT_ELIGIBLE_REJECTED_OBSERVATION",
            code="MET_EIREANN_PHOENIX_1876_33_5_CONTRADICTED_BY_STATION_HISTORY",
            note="Met Eireann reported 33.0 C at Phoenix Park on 18 Jul 2022 as the station's highest shaded-air temperature since observations began there in the early 1800s; the GHCN 33.5 C Phoenix Park value for 16 Jul 1876 is therefore incompatible with the authoritative station history.",
            source=MET_EIREANN_PHOENIX_2022,
            priority=100,
        ))

    # Mexico: WMO's 2025 climate report (published 2026) identifies 52.7 C at
    # Mexicali as a new national record. Preserve older/higher GHCN observations
    # for traceability, but do not let them define the official record list.
    if cc == "MX" and metric == "tmax_highest":
        if v > 52.7 + 0.051:
            out.append(Decision(
                record_eligibility="HOLD_OFFICIAL_CONFLICT",
                code="WMO_MEXICO_2025_NATIONAL_RECORD_CEILING_CONFLICT",
                note=f"GHCN candidate {v:.1f} C exceeds WMO's reported new Mexican national record of 52.7 C at Mexicali in 2025. Preserve the observation, but hold it out of the official-record ranking pending event-specific authoritative validation.",
                source=WMO_LAC_2025_REPORT_NEWS,
                priority=99,
            ))
        elif _same_value(v, 52.7) and date.startswith("2025") and "MEXICALI" in station_name:
            out.append(Decision(
                record_eligibility="SOURCE_BACKED_RECORD",
                code="WMO_MEXICO_2025_52_7_SOURCE_BACKED",
                note="Candidate matches WMO's 52.7 C Mexicali 2025 national-record statement.",
                source=WMO_LAC_2025_REPORT_NEWS,
                priority=0,
            ))

    # Turkmenistan: not a direct observation rejection. It is a guardrail for
    # official record use because the candidate exceeds the WMO-published
    # Eastern-Hemisphere record of 55.0 C (Kebili, Tunisia).
    if cc == "TX" and metric == "tmax_highest" and v > 55.0 + 0.051:
        out.append(Decision(
            record_eligibility="HOLD_WMO_HEMISPHERE_CONFLICT",
            code="WMO_EASTERN_HEMISPHERE_55_0_GUARDRAIL",
            note=f"Candidate {v:.1f} C exceeds the WMO-published Eastern-Hemisphere record of 55.0 C. Keep the GHCN observation, but do not use it as an official country record without a WMO/national-service validation specific to this event.",
            source=WMO_RECORD_TABLE_2025,
            priority=98,
        ))

    # Pacific repeated exact 39 C cluster. Do not call it false solely from the
    # pattern, but do not allow it to become the official record reference.
    if cc in {"FJ", "TL", "TN"} and metric == "tmax_highest" and _same_value(v, 39.0):
        year1 = int(first_date[:4]) if first_date[:4].isdigit() else 0
        year2 = int(last_date[:4]) if last_date[:4].isdigit() else 0
        if 1979 <= year1 <= 1981 and 1979 <= year2 <= 1981 and (tie_count >= 10 or first_date != last_date):
            out.append(Decision(
                record_eligibility="HOLD_CLUSTER_UNVERIFIED",
                code="PACIFIC_1979_1981_39C_RECORD_HOLD",
                note=f"Exact 39.0 C occurs {tie_count} times from {first_date} to {last_date} within the cross-country Fiji/Tokelau/Tonga 1979-1981 cluster. Retain for observation traceability, but hold from official-record selection until source documents confirm the event(s).",
                source=f"{NOAA_GHCN_README} | {FIJI_CLIMATE_SUMMARIES}",
                priority=97,
            ))

    return out


def _apply_stage5(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for idx, raw in enumerate(rows):
        r: dict[str, object] = dict(raw)
        inherited_status = str(raw.get("stage4_status", "PASS_PRELIMINARY"))
        obs_status = inherited_status
        eligibility = _initial_record_eligibility(r)
        decisions = _stage5_decisions(r)

        # Stage 5 only confirms new rejection if an authoritative station/event
        # contradiction is available. Otherwise inherited observation status stays.
        if any(d.observation_status == "REJECT_CONFIRMED" for d in decisions):
            obs_status = "REJECT_CONFIRMED"

        # Highest-priority explicit record decision wins over inherited default.
        rec_decisions = [d for d in decisions if d.record_eligibility]
        if rec_decisions:
            rec_decisions.sort(key=lambda d: d.priority, reverse=True)
            eligibility = rec_decisions[0].record_eligibility

        # Exact official anchor match can promote record eligibility unless the
        # observation itself is rejected.
        if obs_status != "REJECT_CONFIRMED":
            for anchor in STAGE5_ANCHORS:
                if _anchor_matches_row(anchor, r):
                    eligibility = "SOURCE_BACKED_RECORD"
                    decisions.append(Decision(
                        record_eligibility="SOURCE_BACKED_RECORD",
                        code=f"OFFICIAL_RECORD_EVENT_MATCH__{anchor.anchor_id}",
                        note=anchor.note,
                        source=anchor.source,
                        priority=0,
                    ))

        r["__stage5_idx"] = idx
        r["stage5_status"] = obs_status
        r["stage5_record_eligibility"] = eligibility
        r["stage5_record_eligible"] = "yes" if eligibility in RECORD_ELIGIBLE and obs_status != "REJECT_CONFIRMED" else "no"
        r["stage5_flags"] = "|".join(dict.fromkeys(d.code for d in decisions if d.code))
        r["stage5_notes"] = " || ".join(dict.fromkeys(d.note for d in decisions if d.note))
        r["stage5_sources"] = " || ".join(dict.fromkeys(d.source for d in decisions if d.source))
        r["stage5_priority"] = max((d.priority for d in decisions), default=0)
        r["stage5_rank"] = ""
        r["stage5_is_country_extreme"] = ""
        r["stage5_record_candidate_rank"] = ""
        r["stage5_is_record_candidate"] = ""
        out.append(r)
    return out


def _rerank_observations(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    survivors = [dict(r) for r in rows if r.get("stage5_status") != "REJECT_CONFIRMED"]
    ranked = _tie_rank(survivors, "stage5_rank", "stage5_is_country_extreme")
    by_idx = {int(r["__stage5_idx"]): r for r in ranked}
    for r in rows:
        idx = int(r["__stage5_idx"])
        if idx in by_idx:
            r["stage5_rank"] = by_idx[idx]["stage5_rank"]
            r["stage5_is_country_extreme"] = by_idx[idx]["stage5_is_country_extreme"]
    return ranked


def _rerank_record_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    eligible = [
        dict(r) for r in rows
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and r.get("stage5_record_eligible") == "yes"
    ]
    ranked = _tie_rank(eligible, "stage5_record_candidate_rank", "stage5_is_record_candidate")
    by_idx = {int(r["__stage5_idx"]): r for r in ranked}
    for r in rows:
        idx = int(r["__stage5_idx"])
        if idx in by_idx:
            r["stage5_record_candidate_rank"] = by_idx[idx]["stage5_record_candidate_rank"]
            r["stage5_is_record_candidate"] = by_idx[idx]["stage5_is_record_candidate"]
    return ranked


def _anchor_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for anchor in STAGE5_ANCHORS:
        group = [r for r in rows if _row_key(r) == (anchor.country_code, anchor.metric) and r.get("stage5_status") != "REJECT_CONFIRMED"]
        exact = [r for r in group if _anchor_matches_row(anchor, r)]
        value_match = [r for r in group if _same_value(_float(r.get("value_c")), anchor.value_c)]
        if exact:
            status = "OFFICIAL_RECORD_PRESENT"
            note = "Authoritative official record event is represented in the Stage-5 GHCN candidate pool."
        elif value_match:
            status = "OFFICIAL_VALUE_PRESENT_EVENT_UNRESOLVED"
            note = "Official record value exists in the candidate pool, but site/year does not match the authoritative event closely enough for source-backed promotion."
        else:
            status = "OFFICIAL_COVERAGE_GAP"
            note = "Authoritative official country record is absent from the surviving GHCN candidate pool; use the official anchor in the final record reference."

        best = None
        if group:
            best = _sort_group(group, anchor.metric)[0]
        out.append({
            "anchor_id": anchor.anchor_id,
            "country_code": anchor.country_code,
            "country": anchor.country,
            "metric": anchor.metric,
            "official_value_c": f"{anchor.value_c:.1f}",
            "official_date": anchor.event_date,
            "official_year": anchor.event_year,
            "official_site": anchor.site,
            "anchor_source": anchor.source,
            "anchor_note": anchor.note,
            "anchor_status": status,
            "anchor_status_note": note,
            "ghcn_best_surviving_value_c": "" if best is None else best.get("value_c", ""),
            "ghcn_best_surviving_date": "" if best is None else best.get("date", ""),
            "ghcn_best_surviving_station_id": "" if best is None else best.get("station_id", ""),
            "ghcn_best_surviving_station_name": "" if best is None else best.get("station_name", ""),
        })
    return out


def _priority_groups(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    # One compact diagnostic row per special group.
    groups = []
    specs = [
        ("EI", "tmax_highest", "IRELAND"),
        ("MX", "tmax_highest", "MEXICO"),
        ("TX", "tmax_highest", "TURKMENISTAN"),
        ("FJ", "tmax_highest", "FIJI_39C_CLUSTER"),
        ("TL", "tmax_highest", "TOKELAU_39C_CLUSTER"),
        ("TN", "tmax_highest", "TONGA_39C_CLUSTER"),
    ]
    for cc, metric, label in specs:
        subset = [r for r in rows if _row_key(r) == (cc, metric)]
        held = [r for r in subset if str(r.get("stage5_record_eligibility", "")).startswith("HOLD")]
        rejected = [r for r in subset if r.get("stage5_status") == "REJECT_CONFIRMED"]
        record_rank1 = [r for r in subset if _int(r.get("stage5_record_candidate_rank")) == 1]
        groups.append({
            "group": label,
            "country_code": cc,
            "metric": metric,
            "input_rows": len(subset),
            "rejected_observations": len(rejected),
            "held_from_record_ranking": len(held),
            "next_record_candidate_count": len(record_rank1),
            "next_record_candidate_values": " | ".join(
                f"{r.get('value_c')} C @ {r.get('station_name')} ({r.get('date')})" for r in record_rank1[:8]
            ),
        })
    return groups


def _render_report(rows: list[dict[str, object]], anchors: list[dict[str, object]], groups: list[dict[str, object]]) -> str:
    status_counts = Counter(str(r.get("stage5_status")) for r in rows)
    eligibility_counts = Counter(str(r.get("stage5_record_eligibility")) for r in rows)
    rejected = [r for r in rows if r.get("stage5_status") == "REJECT_CONFIRMED"]
    holds = [r for r in rows if str(r.get("stage5_record_eligibility", "")).startswith("HOLD")]
    source_records = [r for r in rows if r.get("stage5_record_eligibility") == "SOURCE_BACKED_RECORD"]

    lines = [
        "# World GHCN candidate QC · Stage 5",
        "",
        "Stage 5 trennt weiterhin Beobachtungs-QC und offizielle Rekordverwendung, löst aber die priorisierten Stage-4-Fälle gezielter auf.",
        "",
        "## Ergebnis",
        f"- Eingangszeilen: {len(rows):,}",
        f"- Neue/fortgeschriebene REJECT_CONFIRMED: {status_counts.get('REJECT_CONFIRMED', 0):,}",
        f"- Source-backed offizielle Rekordzeilen: {len(source_records):,}",
        f"- Aus offizieller Rekordauswahl gehaltene Zeilen: {len(holds):,}",
        "",
        "### Record eligibility",
    ]
    for k in sorted(eligibility_counts):
        lines.append(f"- {k}: {eligibility_counts[k]:,}")

    lines += ["", "## Irland"]
    ei_rej = [r for r in rejected if r.get("country_code") == "EI"]
    if ei_rej:
        for r in ei_rej:
            lines.append(f"- REJECT: {r.get('value_c')} °C | {r.get('date')} | {r.get('station_name')} | {r.get('stage5_flags')}")
    else:
        lines.append("- Kein neuer bestätigter Irland-Ausschluss gefunden.")
    lines.append("- Offizieller Anker: 33.3 °C Kilkenny Castle, 26.06.1887 (Met Eireann).")

    lines += ["", "## Mexiko"]
    mx = [r for r in rows if r.get("country_code") == "MX" and r.get("metric") == "tmax_highest" and (str(r.get("stage5_record_eligibility", "")).startswith("HOLD") or r.get("stage5_record_eligibility") == "SOURCE_BACKED_RECORD")]
    for r in mx[:30]:
        lines.append(f"- {r.get('value_c')} °C | {r.get('date')} | {r.get('station_name')} | {r.get('stage5_record_eligibility')} | {r.get('stage5_flags')}")
    lines.append("- WMO-Anker: 52.7 °C Mexicali in 2025, als neuer nationaler Rekord berichtet.")

    lines += ["", "## Turkmenistan"]
    tx = [r for r in rows if r.get("country_code") == "TX" and r.get("metric") == "tmax_highest"]
    for r in tx[:15]:
        if str(r.get("stage5_record_eligibility", "")).startswith("HOLD") or _int(r.get("stage5_record_candidate_rank")) == 1:
            lines.append(f"- {r.get('value_c')} °C | {r.get('date')} | {r.get('station_name')} | {r.get('stage5_record_eligibility')} | record-rank={r.get('stage5_record_candidate_rank') or '-'}")

    lines += ["", "## Pazifik-39.0-°C-Komplex"]
    pac = [r for r in rows if r.get("stage5_record_eligibility") == "HOLD_CLUSTER_UNVERIFIED"]
    for r in pac[:40]:
        lines.append(f"- {r.get('country_code')} | {r.get('station_name')} | {r.get('value_c')} °C | {r.get('first_date')}–{r.get('last_date')} | ties={r.get('tie_count')} | HOLD")

    lines += ["", "## Offizielle Anker-Audit"]
    for a in anchors:
        lines.append(f"- {a['country_code']} | {a['metric']} | official {a['official_value_c']} °C | {a['official_site']} | {a['anchor_status']} | GHCN-best={a['ghcn_best_surviving_value_c'] or '-'}")

    lines += ["", "## Prioritätsgruppen nach Stage 5"]
    for g in groups:
        lines.append(
            f"- {g['group']}: rejected={g['rejected_observations']}, hold={g['held_from_record_ranking']}, "
            f"next={g['next_record_candidate_values'] or '-'}"
        )

    lines += [
        "",
        "## Quellen",
        f"- Met Eireann Phoenix Park 2022 station-history statement: {MET_EIREANN_PHOENIX_2022}",
        f"- Met Eireann 2026 Kilkenny record re-evaluation: {MET_EIREANN_KILKENNY_2026}",
        f"- WMO State of Climate in Latin America and the Caribbean 2025 / Mexico 52.7 C: {WMO_LAC_2025_REPORT_NEWS}",
        f"- WMO Weather and Climate Extremes table: {WMO_RECORD_TABLE_2025}",
        f"- NOAA GHCN-Daily documentation: {NOAA_GHCN_README}",
        f"- Fiji Meteorological Service climate summaries: {FIJI_CLIMATE_SUMMARIES}",
        "",
        "## Nächster Schritt",
        "Stage 6 sollte nicht wieder breit filtern, sondern die verbleibenden Record-HOLDs und die nächsten nachgerückten Country-Rank-1-Kandidaten gezielt gegen nationale Quellen prüfen. Noch keine 2026-Live-Integration.",
        "",
    ]
    return "\n".join(lines)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    raw, input_fields = _read_rows(input_path)
    annotated = _apply_stage5(raw)
    observation_ranked = _rerank_observations(annotated)
    record_ranked = _rerank_record_candidates(annotated)

    # Build clean observation output from surviving annotated rows, preserving
    # Stage-5 ranks already attached to the annotated objects.
    clean = [dict(r) for r in annotated if r.get("stage5_status") != "REJECT_CONFIRMED"]
    record_candidates = [dict(r) for r in annotated if r.get("stage5_record_eligible") == "yes" and r.get("stage5_status") != "REJECT_CONFIRMED"]
    record_rank1 = [r for r in record_candidates if _int(r.get("stage5_record_candidate_rank")) == 1]

    anchors = _anchor_audit(annotated)
    groups = _priority_groups(annotated)

    extra_fields = [
        "stage5_status", "stage5_record_eligibility", "stage5_record_eligible",
        "stage5_flags", "stage5_notes", "stage5_sources", "stage5_priority",
        "stage5_rank", "stage5_is_country_extreme", "stage5_record_candidate_rank",
        "stage5_is_record_candidate",
    ]
    output_fields = input_fields + [f for f in extra_fields if f not in input_fields]

    def strip_internal(items: list[dict[str, object]]) -> list[dict[str, object]]:
        out = []
        for r in items:
            x = dict(r)
            x.pop("__stage5_idx", None)
            out.append(x)
        return out

    ann_out = strip_internal(annotated)
    clean_out = strip_internal(clean)
    record_out = strip_internal(record_candidates)
    record_rank1_out = strip_internal(record_rank1)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "world_country_extreme_candidates_stage5_annotated.csv", ann_out, output_fields)
    _write_csv(output_dir / "world_country_extreme_candidates_stage5_clean.csv", clean_out, output_fields)
    _write_csv(output_dir / "world_country_record_candidates_stage5.csv", record_out, output_fields)
    _write_csv(output_dir / "world_country_record_rank1_stage5.csv", record_rank1_out, output_fields)
    _write_csv(output_dir / "rejected_confirmed_stage5.csv", [r for r in ann_out if r["stage5_status"] == "REJECT_CONFIRMED"], output_fields)
    _write_csv(output_dir / "record_holds_stage5.csv", [r for r in ann_out if str(r["stage5_record_eligibility"]).startswith("HOLD")], output_fields)
    _write_csv(output_dir / "source_backed_records_stage5.csv", [r for r in ann_out if r["stage5_record_eligibility"] == "SOURCE_BACKED_RECORD"], output_fields)
    _write_csv(output_dir / "pacific_39c_hold_stage5.csv", [r for r in ann_out if r["stage5_record_eligibility"] == "HOLD_CLUSTER_UNVERIFIED"], output_fields)

    anchor_fields = [
        "anchor_id", "country_code", "country", "metric", "official_value_c",
        "official_date", "official_year", "official_site", "anchor_source", "anchor_note",
        "anchor_status", "anchor_status_note", "ghcn_best_surviving_value_c",
        "ghcn_best_surviving_date", "ghcn_best_surviving_station_id",
        "ghcn_best_surviving_station_name",
    ]
    _write_csv(output_dir / "official_record_anchors_stage5.csv", anchors, anchor_fields)
    _write_csv(output_dir / "official_coverage_gaps_stage5.csv", [a for a in anchors if a["anchor_status"] == "OFFICIAL_COVERAGE_GAP"], anchor_fields)

    group_fields = [
        "group", "country_code", "metric", "input_rows", "rejected_observations",
        "held_from_record_ranking", "next_record_candidate_count", "next_record_candidate_values",
    ]
    _write_csv(output_dir / "priority_groups_stage5.csv", groups, group_fields)

    eligibility_counts = Counter(str(r["stage5_record_eligibility"]) for r in ann_out)
    status_counts = Counter(str(r["stage5_status"]) for r in ann_out)
    summary = {
        "schema_version": 1,
        "stage": "world_ghcn_candidate_qc_stage5",
        "input_rows": len(ann_out),
        "observation_status_counts": dict(status_counts),
        "record_eligibility_counts": dict(eligibility_counts),
        "stage5_clean_observation_rows": len(clean_out),
        "stage5_record_candidate_rows": len(record_out),
        "stage5_record_rank1_rows_including_ties": len(record_rank1_out),
        "confirmed_rejected_rows_stage5": sum(r["stage5_status"] == "REJECT_CONFIRMED" for r in ann_out),
        "record_hold_rows_stage5": sum(str(r["stage5_record_eligibility"]).startswith("HOLD") for r in ann_out),
        "source_backed_record_rows_stage5": sum(r["stage5_record_eligibility"] == "SOURCE_BACKED_RECORD" for r in ann_out),
        "official_anchor_status_counts": dict(Counter(str(a["anchor_status"]) for a in anchors)),
        "pacific_39c_hold_rows": sum(r["stage5_record_eligibility"] == "HOLD_CLUSTER_UNVERIFIED" for r in ann_out),
        "architecture": "Observation validity and record eligibility are separate; holds do not delete observations.",
        "record_ranking_policy": "Tie-aware ranking only among currently record-eligible candidates; official anchors remain a separate overlay.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "qc_report.md").write_text(_render_report(annotated, anchors, groups), encoding="utf-8")
    return summary


def self_test() -> None:
    import tempfile

    fields = [
        "country_code", "country", "metric", "rank", "value_c", "date", "first_date", "last_date", "tie_count",
        "station_id", "station_name", "latitude", "longitude", "stage4_status", "stage4_rank",
        "stage4_country_record_status", "stage4_country_record_anchor_id",
    ]
    sample = [
        # Ireland confirmed station-history contradiction and fallback.
        {"country_code":"EI","country":"Ireland","metric":"tmax_highest","rank":"1","value_c":"33.5","date":"1876-07-16","first_date":"1876-07-16","last_date":"1876-07-16","tie_count":"1","station_id":"EI000003969","station_name":"DUBLIN PHOENIX PARK","latitude":"53.36","longitude":"-6.32","stage4_status":"REVIEW_CRITICAL","stage4_rank":"1","stage4_country_record_status":"GHCN_MORE_EXTREME_THAN_OFFICIAL_ANCHOR","stage4_country_record_anchor_id":"MET_EIREANN_EI_TMAX_1887"},
        {"country_code":"EI","country":"Ireland","metric":"tmax_highest","rank":"2","value_c":"33.0","date":"2022-07-18","first_date":"2022-07-18","last_date":"2022-07-18","tie_count":"1","station_id":"EI_PHOENIX_2022","station_name":"DUBLIN PHOENIX PARK","latitude":"53.36","longitude":"-6.32","stage4_status":"PASS_PRELIMINARY","stage4_rank":"2","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        # Mexico: bad-for-official old higher candidates, plus exact 2025 WMO value.
        {"country_code":"MX","country":"Mexico","metric":"tmax_highest","rank":"1","value_c":"56.7","date":"1949-08-20","first_date":"1949-08-20","last_date":"1949-08-20","tie_count":"1","station_id":"MX_OLD","station_name":"MEXICALI (SMN)","latitude":"32.55","longitude":"-115.47","stage4_status":"REVIEW_CRITICAL","stage4_rank":"1","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        {"country_code":"MX","country":"Mexico","metric":"tmax_highest","rank":"5","value_c":"52.7","date":"2025-07-15","first_date":"2025-07-15","last_date":"2025-07-15","tie_count":"1","station_id":"MX_2025","station_name":"MEXICALI","latitude":"32.6","longitude":"-115.5","stage4_status":"PASS_PRELIMINARY","stage4_rank":"5","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        # Turkmenistan: 56.5 held, 49.1 becomes record-candidate rank 1.
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","rank":"1","value_c":"56.5","date":"1890-06-20","first_date":"1890-06-20","last_date":"1890-06-20","tie_count":"1","station_id":"TX_BAJ","station_name":"BAJRAMALY","latitude":"37.6","longitude":"62.18","stage4_status":"REVIEW_CRITICAL","stage4_rank":"1","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        {"country_code":"TX","country":"Turkmenistan","metric":"tmax_highest","rank":"2","value_c":"49.1","date":"1983-07-01","first_date":"1983-07-01","last_date":"1983-07-01","tie_count":"1","station_id":"TX_NEXT","station_name":"TEST","latitude":"37","longitude":"62","stage4_status":"PASS_PRELIMINARY","stage4_rank":"2","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        # Fiji 39C hold and fallback.
        {"country_code":"FJ","country":"Fiji","metric":"tmax_highest","rank":"1","value_c":"39.0","date":"1979-01-04","first_date":"1979-01-04","last_date":"1981-12-25","tie_count":"80","station_id":"FJ39","station_name":"ONO-I-LAU","latitude":"-20.66","longitude":"-178.72","stage4_status":"REVIEW_CRITICAL","stage4_rank":"1","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
        {"country_code":"FJ","country":"Fiji","metric":"tmax_highest","rank":"5","value_c":"36.0","date":"2016-02-01","first_date":"2016-02-01","last_date":"2016-02-01","tie_count":"1","station_id":"FJ_NEXT","station_name":"NADI","latitude":"-17.75","longitude":"177.45","stage4_status":"PASS_PRELIMINARY","stage4_rank":"5","stage4_country_record_status":"","stage4_country_record_anchor_id":""},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "in.csv"
        with src.open("w", encoding="utf-8-sig", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            w.writeheader(); w.writerows(sample)
        out = root / "out"
        summary = run(src, out)
        with (out / "world_country_extreme_candidates_stage5_annotated.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            ann = list(csv.DictReader(handle, delimiter=";"))
        by_id = {r["station_id"]: r for r in ann}
        assert by_id["EI000003969"]["stage5_status"] == "REJECT_CONFIRMED"
        assert by_id["EI_PHOENIX_2022"]["stage5_rank"] == "1"
        assert by_id["MX_OLD"]["stage5_status"] != "REJECT_CONFIRMED"
        assert by_id["MX_OLD"]["stage5_record_eligibility"] == "HOLD_OFFICIAL_CONFLICT"
        assert by_id["MX_2025"]["stage5_record_eligibility"] == "SOURCE_BACKED_RECORD"
        assert by_id["MX_2025"]["stage5_record_candidate_rank"] == "1"
        assert by_id["TX_BAJ"]["stage5_record_eligibility"] == "HOLD_WMO_HEMISPHERE_CONFLICT"
        assert by_id["TX_NEXT"]["stage5_record_candidate_rank"] == "1"
        assert by_id["FJ39"]["stage5_record_eligibility"] == "HOLD_CLUSTER_UNVERIFIED"
        assert by_id["FJ_NEXT"]["stage5_record_candidate_rank"] == "1"
        assert summary["confirmed_rejected_rows_stage5"] == 1
        assert (out / "official_record_anchors_stage5.csv").exists()
        assert (out / "priority_groups_stage5.csv").exists()
        assert (out / "record_holds_stage5.csv").exists()

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
