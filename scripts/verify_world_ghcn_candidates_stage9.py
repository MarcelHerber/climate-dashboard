#!/usr/bin/env python3
"""Stage-9 resolution of remaining absolute national high/low records using User:Maxcrc.

The user-approved source is the Wikipedia user page of Maximiliano Herrera
(User:Maxcrc).  Stage 9 treats it as a *secondary record reference*, never as
an official national weather-service verification.  Only currently unresolved
absolute maxima (tmax_highest) and absolute minima (tmin_lowest) are targeted.
Warmest daily minima (tmin_highest) and coldest daily maxima (tmax_lowest) are
outside the scope because a normal national absolute-record table does not
represent those metrics.

Important safety properties:
- the current page is fetched at workflow runtime and its MediaWiki revision ID
  and SHA-256 snapshot are stored for auditability;
- the parser accepts only unambiguous country rows with explicit Celsius values;
- ambiguous/missing/conflicting rows remain UNRESOLVED_REVIEW;
- underlying GHCN observations are never changed or deleted;
- official_verified always stays "no" for Maxcrc-derived rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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

MAXCRC_PAGE = "User:Maxcrc"
MAXCRC_CANONICAL_URL = "https://en.wikipedia.org/wiki/User:Maxcrc"
MAXCRC_API = "https://en.wikipedia.org/w/api.php"
TARGET_METRICS = {"tmax_highest", "tmin_lowest"}

# GHCN country labels sometimes differ from common/Wikipedia wording.  Keep the
# aliases deliberately narrow; a target is only resolved when one row matches
# uniquely after normalization.
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "AF": ("Afghanistan",),
    "AQ": ("American Samoa",),
    "BF": ("Bahamas", "The Bahamas"),
    "BM": ("Myanmar", "Burma"),
    "CE": ("Sri Lanka", "Ceylon"),
    "CM": ("Cameroon",),
    "CV": ("Cape Verde", "Cabo Verde"),
    "EC": ("Ecuador",),
    "EK": ("Equatorial Guinea",),
    "ER": ("Eritrea",),
    "FJ": ("Fiji",),
    "FK": ("Falkland Islands", "Falkland Islands (Islas Malvinas)", "Islas Malvinas"),
    "FM": ("Federated States of Micronesia", "Micronesia"),
    "FS": ("French Southern and Antarctic Lands", "French Southern Territories", "French Southern and Antarctic Territories"),
    "GH": ("Ghana",),
    "HO": ("Honduras",),
    "IT": ("Italy",),
    "JQ": ("Johnston Atoll", "Johnston Island"),
    "KN": ("North Korea", "Korea, North", "Democratic People's Republic of Korea"),
    "LE": ("Lebanon",),
    "MI": ("Malawi",),
    "RM": ("Marshall Islands",),
    "SG": ("Senegal",),
    "SU": ("Sudan",),
    "SX": ("South Georgia and the South Sandwich Islands", "South Georgia and South Sandwich Islands", "South Georgia"),
    "TI": ("Tajikistan",),
    "TL": ("Tokelau",),
    "TN": ("Tonga",),
    "TX": ("Turkmenistan",),
    "WF": ("Wallis and Futuna",),
    "ZA": ("Zambia",),
}


@dataclass(frozen=True)
class ParsedAnchor:
    country_code: str
    country: str
    metric: str
    value_c: float
    source_row: str
    matched_alias: str
    table_index: int
    row_index: int
    confidence: str


@dataclass
class Cell:
    tag: str
    text: str


class _TableParser(HTMLParser):
    """Small dependency-free HTML table extractor for MediaWiki rendered HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[Cell]]] = []
        self._table_depth = 0
        self._table: list[list[Cell]] | None = None
        self._row: list[Cell] | None = None
        self._cell_tag: str | None = None
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._table_depth == 0:
                self._table = []
            self._table_depth += 1
            return
        if self._table_depth == 0:
            return
        if tag == "tr" and self._table_depth == 1:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth == 1 and self._row is not None:
            self._cell_tag = tag
            self._cell_text = []
        elif tag == "br" and self._cell_tag:
            self._cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_tag:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._table_depth == 0:
            return
        if tag in {"td", "th"} and self._cell_tag == tag and self._row is not None:
            text = _clean_text("".join(self._cell_text))
            self._row.append(Cell(tag, text))
            self._cell_tag = None
            self._cell_text = []
        elif tag == "tr" and self._table_depth == 1:
            if self._row and self._table is not None:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                if self._table:
                    self.tables.append(self._table)
                self._table = None
                self._row = None
                self._cell_tag = None
                self._cell_text = []


def _clean_text(value: object) -> str:
    s = html.unescape(str(value or ""))
    s = s.replace("−", "-").replace("–", "-").replace("—", "-").replace("\xa0", " ")
    s = re.sub(r"\[\s*(?:edit|\d+|[a-z])\s*\]", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm(value: object) -> str:
    s = _clean_text(value).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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


def _fetch_maxcrc(retries: int = 3, timeout: int = 30) -> tuple[str, dict[str, object]]:
    query = urlencode({
        "action": "parse",
        "page": MAXCRC_PAGE,
        "prop": "text|revid",
        "format": "json",
        "formatversion": "2",
    })
    url = f"{MAXCRC_API}?{query}"
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "climate-dashboard-ghcn-qc/1.0 (secondary record audit; GitHub Actions)",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed HTTPS endpoint
                raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
            parsed = payload.get("parse") or {}
            text = parsed.get("text") or ""
            if not text:
                raise ValueError("MediaWiki API returned no parsed HTML")
            meta = {
                "fetch_status": "OK",
                "canonical_url": MAXCRC_CANONICAL_URL,
                "api_url": url,
                "page": parsed.get("title", MAXCRC_PAGE),
                "revision_id": parsed.get("revid", ""),
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "html_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "html_bytes": len(text.encode("utf-8")),
                "attempt": attempt,
            }
            return text, meta
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(2 * attempt)
    return "", {
        "fetch_status": "FAILED",
        "canonical_url": MAXCRC_CANONICAL_URL,
        "page": MAXCRC_PAGE,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": last_error,
    }


_C_RE = re.compile(r"(?<!\d)([-+]?\d{1,3}(?:[.,]\d+)?)\s*(?:°|º)\s*C\b", re.I)


def _celsius_values(text: str) -> list[float]:
    s = _clean_text(text)
    vals: list[float] = []
    for m in _C_RE.finditer(s):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if -100.0 <= v <= 60.0:
            vals.append(v)
    return vals


def _row_matches_alias(row: list[Cell], aliases: Iterable[str]) -> tuple[bool, str]:
    alias_norms = [(_norm(a), a) for a in aliases]
    # Country is normally the first cell.  Prefer exact first-cell matches and
    # then exact matches in another cell; never use free substring matching.
    for cell in row[:2]:
        n = _norm(cell.text)
        for an, raw in alias_norms:
            if n == an or n.startswith(an + " ") or n.endswith(" " + an):
                return True, raw
    return False, ""


def _header_text(table: list[list[Cell]]) -> str:
    parts: list[str] = []
    for row in table[:4]:
        ths = [c.text for c in row if c.tag == "th"]
        if ths:
            parts.extend(ths)
    return _norm(" ".join(parts))


def _record_value_from_row(metric: str, row: list[Cell], table_headers: str) -> tuple[float, str]:
    temps: list[float] = []
    for cell in row:
        temps.extend(_celsius_values(cell.text))
    # Dedupe while retaining numeric values.
    distinct = sorted(set(round(v, 4) for v in temps))
    if len(distinct) >= 2:
        value = max(distinct) if metric == "tmax_highest" else min(distinct)
        return value, "ROW_HAS_HIGH_AND_LOW_CELSIUS"
    if len(distinct) == 1:
        # A single-temperature table is only safe when its header clearly says
        # it is a high-only or low-only record table.
        h = table_headers
        has_high = any(x in h for x in ("HIGHEST", "RECORD HIGH", "MAXIMUM", "MAX TEMP"))
        has_low = any(x in h for x in ("LOWEST", "RECORD LOW", "MINIMUM", "MIN TEMP"))
        if metric == "tmax_highest" and has_high and not has_low:
            return distinct[0], "HIGH_ONLY_TABLE"
        if metric == "tmin_lowest" and has_low and not has_high:
            return distinct[0], "LOW_ONLY_TABLE"
    return math.nan, "AMBIGUOUS_TEMPERATURE_ROW"


def parse_maxcrc_anchors(html_text: str, targets: list[dict[str, str]]) -> tuple[list[ParsedAnchor], list[dict[str, object]], dict[str, int]]:
    parser = _TableParser()
    parser.feed(html_text)
    tables = parser.tables

    target_map: dict[tuple[str, str], dict[str, str]] = {
        (r.get("country_code", ""), r.get("metric", "")): r for r in targets
    }
    matches: dict[tuple[str, str], list[ParsedAnchor]] = defaultdict(list)
    diagnostics: list[dict[str, object]] = []

    for ti, table in enumerate(tables):
        headers = _header_text(table)
        for ri, row in enumerate(table):
            if not row or all(c.tag == "th" for c in row):
                continue
            row_text = " | ".join(c.text for c in row if c.text)
            for (cc, metric), target in target_map.items():
                aliases = COUNTRY_ALIASES.get(cc, (target.get("country", ""),))
                ok, matched_alias = _row_matches_alias(row, aliases)
                if not ok:
                    continue
                value, parse_rule = _record_value_from_row(metric, row, headers)
                if not math.isfinite(value):
                    diagnostics.append({
                        "country_code": cc, "country": target.get("country", ""), "metric": metric,
                        "status": "MATCHED_COUNTRY_BUT_AMBIGUOUS_TEMPERATURE", "matched_alias": matched_alias,
                        "table_index": ti, "row_index": ri, "parse_rule": parse_rule,
                        "source_row": row_text,
                    })
                    continue
                anchor = ParsedAnchor(
                    cc, target.get("country", ""), metric, value, row_text,
                    matched_alias, ti, ri, "HIGH" if parse_rule == "ROW_HAS_HIGH_AND_LOW_CELSIUS" else "MEDIUM",
                )
                matches[(cc, metric)].append(anchor)
                diagnostics.append({
                    "country_code": cc, "country": target.get("country", ""), "metric": metric,
                    "status": "PARSED_CANDIDATE", "matched_alias": matched_alias,
                    "table_index": ti, "row_index": ri, "parse_rule": parse_rule,
                    "value_c": f"{value:.1f}", "source_row": row_text,
                })

    accepted: list[ParsedAnchor] = []
    for key, target in target_map.items():
        found = matches.get(key, [])
        by_value: dict[float, list[ParsedAnchor]] = defaultdict(list)
        for a in found:
            by_value[round(a.value_c, 3)].append(a)
        if len(by_value) == 1:
            # Multiple identical rows are harmless; keep the first deterministic match.
            accepted.append(next(iter(by_value.values()))[0])
        elif len(by_value) > 1:
            diagnostics.append({
                "country_code": key[0], "country": target.get("country", ""), "metric": key[1],
                "status": "CONFLICTING_MAXCRC_ROWS_NOT_RESOLVED",
                "values": " | ".join(f"{v:.1f}" for v in sorted(by_value)),
                "source_row": " || ".join(a.source_row for rows in by_value.values() for a in rows),
            })
        else:
            diagnostics.append({
                "country_code": key[0], "country": target.get("country", ""), "metric": key[1],
                "status": "NO_USABLE_MAXCRC_ROW", "source_row": "",
            })

    stats = {
        "html_tables": len(tables),
        "target_rows": len(targets),
        "accepted_anchor_rows": len(accepted),
        "diagnostic_rows": len(diagnostics),
    }
    return accepted, diagnostics, stats


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
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    if metric in {"tmax_highest", "tmin_highest"}:
        return a > b + 0.051
    return a < b - 0.051


def _exact_support(anchor: ParsedAnchor, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("stage5_status") != "REJECT_CONFIRMED"
        and _same_value(_float(r.get("value_c")), anchor.value_c)
    ]


def _relation(anchor: ParsedAnchor, group: list[dict[str, str]]) -> tuple[str, str]:
    exact = _exact_support(anchor, group)
    if exact:
        return "GHCN_VALUE_MATCH", f"{len(exact)} surviving GHCN candidate row(s) contain the Maxcrc record value."
    comparison = _rank1(group) + _holds(group)
    vals = [_float(r.get("value_c")) for r in comparison]
    vals = [v for v in vals if math.isfinite(v)]
    if not vals:
        return "GHCN_COVERAGE_GAP", "No comparable surviving GHCN candidate is available."
    more = [v for v in vals if _is_more_extreme(anchor.metric, v, anchor.value_c)]
    if more:
        x = max(more) if anchor.metric == "tmax_highest" else min(more)
        return "GHCN_MORE_EXTREME_THAN_MAXCRC", f"A surviving/held GHCN value ({x:.1f} C) is more extreme than the Maxcrc reference ({anchor.value_c:.1f} C); raw GHCN is retained but the master follows the approved secondary reference."
    best = max(vals) if anchor.metric == "tmax_highest" else min(vals)
    if _is_more_extreme(anchor.metric, anchor.value_c, best):
        return "MAXCRC_MORE_EXTREME_COVERAGE_GAP", f"Maxcrc reference ({anchor.value_c:.1f} C) is more extreme than the best surviving GHCN candidate ({best:.1f} C)."
    return "MAXCRC_REPLACES_UNRESOLVED", "Maxcrc resolves the open master row; no exact GHCN value match was found."


def _join_unique(values: list[str]) -> str:
    return " | ".join(dict.fromkeys(v for v in values if v))


def run(
    master_input: Path,
    candidate_input: Path,
    output_dir: Path,
    *,
    source_html: str | None = None,
    source_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    master, master_fields = _read_csv(master_input, MASTER_REQUIRED)
    candidates, _candidate_fields = _read_csv(candidate_input, CANDIDATE_REQUIRED)
    groups = _candidate_groups(candidates)

    stage8_unresolved = [r for r in master if r.get("master_status") == "UNRESOLVED_REVIEW"]
    targets = [r for r in stage8_unresolved if r.get("metric") in TARGET_METRICS]
    non_target_unresolved = [r for r in stage8_unresolved if r.get("metric") not in TARGET_METRICS]

    if source_html is None:
        source_html, fetched_meta = _fetch_maxcrc()
        source_meta = fetched_meta
    else:
        source_meta = dict(source_meta or {})
        source_meta.setdefault("fetch_status", "TEST_OR_SUPPLIED_SNAPSHOT")
        source_meta.setdefault("canonical_url", MAXCRC_CANONICAL_URL)
        source_meta.setdefault("revision_id", "")
        source_meta.setdefault("fetched_at_utc", datetime.now(timezone.utc).isoformat())
        source_meta.setdefault("html_sha256", hashlib.sha256(source_html.encode("utf-8")).hexdigest())
        source_meta.setdefault("html_bytes", len(source_html.encode("utf-8")))

    source_meta = dict(source_meta or {})
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "maxcrc_source_metadata_stage9.json").write_text(
        json.dumps(source_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if source_html:
        (output_dir / "maxcrc_source_snapshot_stage9.html").write_text(source_html, encoding="utf-8")
        anchors, diagnostics, parser_stats = parse_maxcrc_anchors(source_html, targets)
    else:
        anchors, diagnostics = [], [
            {
                "country_code": r.get("country_code", ""), "country": r.get("country", ""),
                "metric": r.get("metric", ""), "status": "SOURCE_FETCH_FAILED_NOT_RESOLVED",
                "source_row": "",
            }
            for r in targets
        ]
        parser_stats = {"html_tables": 0, "target_rows": len(targets), "accepted_anchor_rows": 0, "diagnostic_rows": len(diagnostics)}

    anchor_map = {(a.country_code, a.metric): a for a in anchors}
    extra_fields = [
        "stage9_previous_master_status", "stage9_resolution", "stage9_resolution_code",
        "stage9_reference_type", "stage9_reference_confidence", "stage9_reference_relation",
        "stage9_reference_source", "stage9_reference_revision", "stage9_reference_snapshot_sha256",
        "stage9_reference_row", "stage9_reference_notes",
    ]
    out_fields = master_fields + [f for f in extra_fields if f not in master_fields]

    updated: list[dict[str, object]] = []
    resolved: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    revision = str(source_meta.get("revision_id", ""))
    snapshot_sha = str(source_meta.get("html_sha256", ""))

    for src in master:
        row: dict[str, object] = dict(src)
        previous = src.get("master_status", "")
        key = (src.get("country_code", ""), src.get("metric", ""))
        row.update({
            "stage9_previous_master_status": previous,
            "stage9_resolution": "CARRIED_FORWARD",
            "stage9_resolution_code": "",
            "stage9_reference_type": "",
            "stage9_reference_confidence": "",
            "stage9_reference_relation": "",
            "stage9_reference_source": "",
            "stage9_reference_revision": "",
            "stage9_reference_snapshot_sha256": "",
            "stage9_reference_row": "",
            "stage9_reference_notes": "",
        })

        anchor = anchor_map.get(key)
        if previous != "UNRESOLVED_REVIEW" or src.get("metric") not in TARGET_METRICS or anchor is None:
            updated.append(row)
            continue

        group = groups.get(key, [])
        exact = _exact_support(anchor, group)
        relation, relation_note = _relation(anchor, group)
        row.update({
            "master_status": "SECONDARY_SOURCE_BACKED",
            "publishable": "yes",
            "canonical_value_c": f"{anchor.value_c:.1f}",
            # The generic parser intentionally does not guess a date/site from
            # neighboring table cells.  The exact source row is preserved below.
            "canonical_date": "",
            "canonical_site": "",
            "canonical_station_id": _join_unique([str(r.get("station_id", "")) for r in exact]),
            "canonical_source": MAXCRC_CANONICAL_URL,
            "canonical_source_type": "SECONDARY_REFERENCE_MAXCRC_WIKIPEDIA",
            "official_verified": "no",
            "ghcn_support_count": len(exact),
            "unresolved_reason": "",
            "notes": "Maximiliano Herrera / User:Maxcrc national absolute temperature record used as an explicitly approved secondary reference. The exact parsed source row and revision are retained in Stage-9 provenance fields; not an official national-service verification.",
            "stage9_resolution": "RESOLVED",
            "stage9_resolution_code": "MAXCRC_SECONDARY_NATIONAL_RECORD_ACCEPTED",
            "stage9_reference_type": "MAXCRC_WIKIPEDIA_SECONDARY",
            "stage9_reference_confidence": anchor.confidence,
            "stage9_reference_relation": relation,
            "stage9_reference_source": MAXCRC_CANONICAL_URL,
            "stage9_reference_revision": revision,
            "stage9_reference_snapshot_sha256": snapshot_sha,
            "stage9_reference_row": anchor.source_row,
            "stage9_reference_notes": relation_note,
        })
        updated.append(row)
        resolved.append(row)
        decisions.append({
            "country_code": anchor.country_code,
            "country": anchor.country,
            "metric": anchor.metric,
            "previous_status": previous,
            "new_status": "SECONDARY_SOURCE_BACKED",
            "canonical_value_c": f"{anchor.value_c:.1f}",
            "matched_alias": anchor.matched_alias,
            "confidence": anchor.confidence,
            "relation_to_ghcn": relation,
            "source": MAXCRC_CANONICAL_URL,
            "source_revision": revision,
            "source_row": anchor.source_row,
            "notes": relation_note,
        })

    publishable = [r for r in updated if r.get("publishable") == "yes"]
    unresolved = [r for r in updated if r.get("master_status") == "UNRESOLVED_REVIEW"]

    decision_fields = [
        "country_code", "country", "metric", "previous_status", "new_status",
        "canonical_value_c", "matched_alias", "confidence", "relation_to_ghcn",
        "source", "source_revision", "source_row", "notes",
    ]
    anchor_fields = [
        "country_code", "country", "metric", "value_c", "matched_alias",
        "confidence", "table_index", "row_index", "source", "source_revision", "source_row",
    ]
    anchor_rows = [
        {
            "country_code": a.country_code, "country": a.country, "metric": a.metric,
            "value_c": f"{a.value_c:.1f}", "matched_alias": a.matched_alias,
            "confidence": a.confidence, "table_index": a.table_index, "row_index": a.row_index,
            "source": MAXCRC_CANONICAL_URL, "source_revision": revision, "source_row": a.source_row,
        }
        for a in anchors
    ]
    diagnostic_fields = [
        "country_code", "country", "metric", "status", "matched_alias", "table_index",
        "row_index", "parse_rule", "value_c", "values", "source_row",
    ]

    _write_csv(output_dir / "world_country_record_master_stage9.csv", updated, out_fields)
    _write_csv(output_dir / "world_country_record_master_publishable_stage9.csv", publishable, out_fields)
    _write_csv(output_dir / "world_country_record_master_unresolved_stage9.csv", unresolved, out_fields)
    _write_csv(output_dir / "resolved_stage9.csv", resolved, out_fields)
    _write_csv(output_dir / "resolution_decisions_stage9.csv", decisions, decision_fields)
    _write_csv(output_dir / "maxcrc_reference_anchors_stage9.csv", anchor_rows, anchor_fields)
    _write_csv(output_dir / "maxcrc_parse_diagnostics_stage9.csv", diagnostics, diagnostic_fields)

    status_counts = Counter(str(r.get("master_status", "")) for r in updated)
    relation_counts = Counter(str(r.get("stage9_reference_relation", "")) for r in resolved)
    target_metric_counts = Counter(str(r.get("metric", "")) for r in targets)

    summary: dict[str, object] = {
        "schema_version": 1,
        "stage": "world_ghcn_country_record_maxcrc_resolution_stage9",
        "master_rows": len(updated),
        "stage8_unresolved_input_rows": len(stage8_unresolved),
        "stage9_target_rows_absolute_high_low": len(targets),
        "stage9_non_target_unresolved_rows": len(non_target_unresolved),
        "target_metric_counts": dict(sorted(target_metric_counts.items())),
        "maxcrc_fetch_status": source_meta.get("fetch_status", ""),
        "maxcrc_revision_id": source_meta.get("revision_id", ""),
        "maxcrc_snapshot_sha256": source_meta.get("html_sha256", ""),
        "maxcrc_html_tables": parser_stats.get("html_tables", 0),
        "maxcrc_anchor_rows": len(anchors),
        "resolved_in_stage9": len(resolved),
        "unresolved_after_stage9": len(unresolved),
        "publishable_after_stage9": len(publishable),
        "master_status_counts": dict(sorted(status_counts.items())),
        "stage9_relation_counts": dict(sorted(relation_counts.items())),
        "policy": "User:Maxcrc is an explicitly approved secondary national absolute-record reference. Stage 9 targets only tmax_highest and tmin_lowest, records the exact MediaWiki revision/snapshot, never sets official_verified=yes, never deletes GHCN observations, and leaves ambiguous/unmatched rows unresolved.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = [
        "# World GHCN country record master · Stage 9",
        "",
        "Stage 9 uses the user-approved Wikipedia User:Maxcrc / Maximiliano Herrera record table as a revision-pinned secondary reference for national absolute highs and lows.",
        "",
        "## Ergebnis",
        f"- Stage-8 unresolved am Eingang: {len(stage8_unresolved)}",
        f"- Davon Stage-9-Zielmetrik tmax_highest/tmin_lowest: {len(targets)}",
        f"- Andere offene Metriken (tmin_highest/tmax_lowest), bewusst nicht angefasst: {len(non_target_unresolved)}",
        f"- Maxcrc-Anker eindeutig geparst: {len(anchors)}",
        f"- In Stage 9 aufgelöst: {len(resolved)}",
        f"- Danach weiterhin unresolved: {len(unresolved)}",
        f"- Publishable nach Stage 9: {len(publishable)}",
        "",
        "## Quellen-/Sicherheitsregeln",
        f"- Quelle: {MAXCRC_CANONICAL_URL}",
        f"- MediaWiki revision_id: {revision or 'n/a'}",
        f"- Snapshot SHA-256: {snapshot_sha or 'n/a'}",
        "- Maxcrc/Herrera bleibt SECONDARY_SOURCE_BACKED; official_verified bleibt no.",
        "- Nur eindeutige Länderzeilen mit expliziten Celsiuswerten werden akzeptiert.",
        "- Widersprüchliche oder nicht gefundene Länderzeilen bleiben UNRESOLVED_REVIEW.",
        "- GHCN-Rohbeobachtungen werden nicht verändert oder gelöscht.",
        "- tmin_highest und tmax_lowest bleiben für eine spätere Spezialquellen-Stufe offen.",
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
        "stage5_record_candidate_rank",
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
        }

    masters = [
        m("GH", "Ghana", "tmax_highest"),
        m("KN", "Korea, North", "tmin_lowest"),
        m("IS", "Israel", "tmin_highest"),  # non-target metric: must stay unresolved
    ]
    cands = [
        {"country_code":"GH","country":"Ghana","metric":"tmax_highest","value_c":"48.8","date":"1993-03-05","station_id":"GH1","station_name":"TAMALE","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
        {"country_code":"KN","country":"Korea, North","metric":"tmin_lowest","value_c":"-37.2","date":"1958-01-23","station_id":"KN1","station_name":"CHUNGGANG","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
        {"country_code":"IS","country":"Israel","metric":"tmin_highest","value_c":"37.0","date":"1997-07-05","station_id":"IS1","station_name":"ELAT","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
    ]
    sample_html = """
    <table class='wikitable'>
      <tr><th>Country</th><th>Highest temperature</th><th>Location/date</th><th>Lowest temperature</th><th>Location/date</th></tr>
      <tr><td>Ghana</td><td>44.0 °C</td><td>Example High</td><td>5.0 °C</td><td>Example Low</td></tr>
      <tr><td>North Korea</td><td>41.0 °C</td><td>Example High</td><td>−43.6 °C</td><td>Example Low</td></tr>
    </table>
    """

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mp, cp, out = root / "master.csv", root / "cands.csv", root / "out"
        with mp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=master_fields, delimiter=";")
            w.writeheader(); w.writerows(masters)
        with cp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=candidate_fields, delimiter=";")
            w.writeheader(); w.writerows(cands)
        summary = run(
            mp, cp, out,
            source_html=sample_html,
            source_meta={"fetch_status":"TEST", "revision_id":12345, "html_sha256":"testsha"},
        )
        assert summary["stage8_unresolved_input_rows"] == 3, summary
        assert summary["stage9_target_rows_absolute_high_low"] == 2, summary
        assert summary["resolved_in_stage9"] == 2, summary
        rows, _ = _read_csv(out / "world_country_record_master_stage9.csv", MASTER_REQUIRED)
        by = {(r["country_code"], r["metric"]): r for r in rows}
        assert by[("GH","tmax_highest")]["master_status"] == "SECONDARY_SOURCE_BACKED"
        assert by[("GH","tmax_highest")]["canonical_value_c"] == "44.0"
        assert by[("GH","tmax_highest")]["official_verified"] == "no"
        assert by[("KN","tmin_lowest")]["canonical_value_c"] == "-43.6"
        assert by[("IS","tmin_highest")]["master_status"] == "UNRESOLVED_REVIEW"
        assert (out / "maxcrc_source_metadata_stage9.json").exists()
        assert (out / "maxcrc_parse_diagnostics_stage9.csv").exists()
    print("Stage-9 self-test: OK")


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
