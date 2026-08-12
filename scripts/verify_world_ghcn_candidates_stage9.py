#!/usr/bin/env python3
"""Stage 9: resolve unresolved national absolute highs/lows from Maxcrc continent tables.

The user-approved source is Maximiliano Herrera's Wikipedia User:Maxcrc collection,
split into six continent subpages.  Each page is revision-pinned to the latest
revision at/before the historical baseline cutoff 2025-12-31 23:59:59 UTC.

Policy
------
- target only Stage-8 UNRESOLVED_REVIEW rows with metric tmax_highest or tmin_lowest;
- fetch User:Maxcrc/{Africa,Asia,Europe,North_America,South_America,Oceania};
- treat parsed values as SECONDARY_SOURCE_BACKED, never as official verification;
- retain all GHCN observations, including conflicting/more-extreme raw values;
- accept a country/metric only when the Maxcrc row is unambiguous;
- leave missing/ambiguous rows unresolved;
- preserve exact source page revision, timestamp and SHA-256 snapshot per anchor.
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

SOURCE_API = "https://en.wikipedia.org/w/api.php"
HISTORICAL_CUTOFF_UTC = "2025-12-31T23:59:59Z"
HISTORICAL_CUTOFF_YEAR = 2025
TARGET_METRICS = {"tmax_highest", "tmin_lowest"}

SOURCE_PAGES = (
    ("Africa", "User:Maxcrc/Africa", "https://en.wikipedia.org/wiki/User:Maxcrc/Africa"),
    ("Asia", "User:Maxcrc/Asia", "https://en.wikipedia.org/wiki/User:Maxcrc/Asia"),
    ("Europe", "User:Maxcrc/Europe", "https://en.wikipedia.org/wiki/User:Maxcrc/Europe"),
    ("North_America", "User:Maxcrc/North_America", "https://en.wikipedia.org/wiki/User:Maxcrc/North_America"),
    ("South_America", "User:Maxcrc/South_America", "https://en.wikipedia.org/wiki/User:Maxcrc/South_America"),
    ("Oceania", "User:Maxcrc/Oceania", "https://en.wikipedia.org/wiki/User:Maxcrc/Oceania"),
)

# GHCN geopolitical labels can differ from the names used in Maxcrc's tables.
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
    "IC": ("Iceland",),
    "IT": ("Italy",),
    "JQ": ("Johnston Atoll", "Johnston Island"),
    "KN": ("North Korea", "Korea, North", "Democratic People's Republic of Korea", "DPR Korea"),
    "LE": ("Lebanon",),
    "MI": ("Malawi",),
    "NC": ("New Caledonia",),
    "NZ": ("New Zealand",),
    "RM": ("Marshall Islands",),
    "SG": ("Senegal",),
    "SH": ("Saint Helena", "St Helena"),
    "SU": ("Sudan",),
    "SX": ("South Georgia and the South Sandwich Islands", "South Georgia and South Sandwich Islands", "South Georgia"),
    "TI": ("Tajikistan",),
    "TL": ("Tokelau",),
    "TN": ("Tonga",),
    "TX": ("Turkmenistan",),
    "US": ("United States", "USA", "United States of America"),
    "WF": ("Wallis and Futuna",),
    "ZA": ("Zambia",),
}


@dataclass(frozen=True)
class ParsedAnchor:
    country_code: str
    country: str
    metric: str
    value_c: float
    site: str
    date_text: str
    date_iso: str
    source_key: str
    source_title: str
    source_url: str
    source_revision: str
    source_revision_timestamp: str
    source_snapshot_sha256: str
    source_row: str
    matched_alias: str
    table_index: int
    row_index: int
    confidence: str


@dataclass
class Cell:
    tag: str
    text: str


class TableParser(HTMLParser):
    """Minimal dependency-free parser for top-level HTML tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[Cell]]] = []
        self._depth = 0
        self._rows: list[list[Cell]] | None = None
        self._row: list[Cell] | None = None
        self._cell_tag: str | None = None
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._depth == 0:
                self._rows = []
            self._depth += 1
            return
        if self._depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_tag = tag
            self._cell_text = []
        elif tag == "br" and self._cell_tag:
            self._cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_tag:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._depth == 0:
            return
        if tag in {"td", "th"} and self._depth == 1 and self._cell_tag == tag and self._row is not None:
            self._row.append(Cell(tag, _clean_text("".join(self._cell_text))))
            self._cell_tag = None
            self._cell_text = []
        elif tag == "tr" and self._depth == 1:
            if self._row and self._rows is not None:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1
            if self._depth == 0:
                if self._rows:
                    self.tables.append(self._rows)
                self._rows = None
                self._row = None
                self._cell_tag = None
                self._cell_text = []


def _clean_text(value: object) -> str:
    s = html.unescape(str(value or ""))
    s = s.replace("−", "-").replace("–", "-").replace("—", "-").replace("\xa0", " ")
    s = re.sub(r"\[\s*(?:edit|\d+|[a-z]+\s*\d*)\s*\]", "", s, flags=re.I)
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


_EXPLICIT_C_RE = re.compile(r"(?<!\d)([-+]?\d{1,3}(?:[.,]\d+)?)\s*(?:°|º)?\s*C\b", re.I)
_BARE_TEMP_RE = re.compile(r"^\s*([-+]?\d{1,3}(?:[.,]\d+)?)\s*(?:°|º)?\s*(?:C)?\s*(?:\[[^\]]+\])?\s*$", re.I)
_YEAR_RE = re.compile(r"\b(1[6-9]\d{2}|20\d{2}|21\d{2})\b")
_MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
    "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
    "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}


def _temp_value(text: str) -> float:
    """Parse either '44.3 C' or Maxcrc-style bare '44.3' temperature cells."""
    s = _clean_text(text)
    m = _EXPLICIT_C_RE.search(s)
    if not m:
        # strip simple footnote markers and try a cell containing only a number
        s2 = re.sub(r"\[[^\]]+\]", "", s).strip()
        m = _BARE_TEMP_RE.match(s2)
    if not m:
        return math.nan
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return math.nan
    return v if -100.0 <= v <= 60.0 else math.nan


def _years(text: str) -> list[int]:
    return [int(x) for x in _YEAR_RE.findall(_clean_text(text))]


def _iso_date(text: str) -> str:
    s = _clean_text(text)
    m = re.search(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        s, flags=re.I,
    )
    if not m:
        return ""
    day = int(m.group(1)); month = _MONTHS[m.group(2).upper()]; year = int(m.group(3))
    try:
        dt = datetime(year, month, day)
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%d")


def _row_matches_alias(row: list[Cell], aliases: Iterable[str]) -> tuple[bool, str, int]:
    alias_norms = [(_norm(a), a) for a in aliases if a]
    for idx, cell in enumerate(row[:2]):
        n = _norm(cell.text)
        for an, raw in alias_norms:
            if n == an or n.startswith(an + " ") or n.endswith(" " + an):
                return True, raw, idx
    return False, "", -1


def _header_mode(table: list[list[Cell]]) -> str:
    text = _norm(" | ".join(c.text for row in table[:4] for c in row if c.tag == "th"))
    low = any(x in text for x in ("LOWEST TEMPERATURE", "MINIMUM TEMPERATURE", "RECORD LOW", "LOWEST"))
    high = any(x in text for x in ("HIGHEST TEMPERATURE", "MAXIMUM TEMPERATURE", "RECORD HIGH", "HIGHEST"))
    if low and high:
        low_pos = min([p for x in ("LOWEST", "MINIMUM", "RECORD LOW") if (p := text.find(x)) >= 0], default=10**9)
        high_pos = min([p for x in ("HIGHEST", "MAXIMUM", "RECORD HIGH") if (p := text.find(x)) >= 0], default=10**9)
        return "COMBINED_LOW_HIGH" if low_pos <= high_pos else "COMBINED_HIGH_LOW"
    if high:
        return "HIGH_ONLY"
    if low:
        return "LOW_ONLY"
    return "UNKNOWN"


def _extract_metric_from_row(row: list[Cell], country_cell_index: int, metric: str, mode: str) -> tuple[float, str, str, str]:
    """Return value/site/date/diagnostic for a Maxcrc country row."""
    cells = [c.text for c in row]
    start = country_cell_index + 1

    # Preferred classic Maxcrc layout:
    # Country | low T | low place | low date | high T | high place | high date
    if mode in {"COMBINED_LOW_HIGH", "COMBINED_HIGH_LOW"} and len(cells) >= start + 6:
        first_v = _temp_value(cells[start])
        second_v = _temp_value(cells[start + 3])
        if math.isfinite(first_v) and math.isfinite(second_v):
            first_metric = "tmin_lowest" if mode == "COMBINED_LOW_HIGH" else "tmax_highest"
            if metric == first_metric:
                return first_v, _clean_text(cells[start + 1]), _clean_text(cells[start + 2]), "CLASSIC_7_COLUMN"
            return second_v, _clean_text(cells[start + 4]), _clean_text(cells[start + 5]), "CLASSIC_7_COLUMN"

    # Robust fallback: locate temperature-like cells after the country cell.
    temp_positions: list[tuple[int, float]] = []
    for idx in range(start, len(cells)):
        v = _temp_value(cells[idx])
        if math.isfinite(v):
            temp_positions.append((idx, v))

    if mode in {"COMBINED_LOW_HIGH", "COMBINED_HIGH_LOW"} and len(temp_positions) >= 2:
        first, second = temp_positions[0], temp_positions[1]
        first_metric = "tmin_lowest" if mode == "COMBINED_LOW_HIGH" else "tmax_highest"
        chosen = first if metric == first_metric else second
    elif mode == "HIGH_ONLY" and metric == "tmax_highest" and temp_positions:
        chosen = temp_positions[0]
    elif mode == "LOW_ONLY" and metric == "tmin_lowest" and temp_positions:
        chosen = temp_positions[0]
    elif mode == "UNKNOWN" and len(temp_positions) >= 2:
        # Maxcrc continent pages historically use low first, high second.
        chosen = temp_positions[0] if metric == "tmin_lowest" else temp_positions[1]
    else:
        return math.nan, "", "", "NO_UNAMBIGUOUS_TEMPERATURE_CELL"

    idx, value = chosen
    site = _clean_text(cells[idx + 1]) if idx + 1 < len(cells) else ""
    date_text = _clean_text(cells[idx + 2]) if idx + 2 < len(cells) else ""
    return value, site, date_text, "TEMPERATURE_CELL_FALLBACK"


def _fetch_json(url: str, *, retries: int = 3, timeout: int = 30) -> dict[str, object]:
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": "climate-dashboard-ghcn-qc/1.0 (Maxcrc national-record audit; GitHub Actions)",
                "Accept": "application/json",
            })
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed HTTPS endpoint
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(last_error or "Wikipedia API request failed")


def _fetch_cutoff_snapshot(key: str, title: str, url: str) -> tuple[str, dict[str, object]]:
    try:
        q1 = urlencode({
            "action": "query", "prop": "revisions", "titles": title,
            "rvprop": "ids|timestamp", "rvstart": HISTORICAL_CUTOFF_UTC,
            "rvdir": "older", "rvlimit": "1", "format": "json", "formatversion": "2",
        })
        p1 = _fetch_json(f"{SOURCE_API}?{q1}")
        pages = ((p1.get("query") or {}).get("pages") or []) if isinstance(p1, dict) else []
        if not pages or pages[0].get("missing") is not None:
            raise RuntimeError(f"Wikipedia page missing: {title}")
        revisions = pages[0].get("revisions") or []
        if not revisions:
            raise RuntimeError(f"No revision at/before cutoff: {title}")
        rev = revisions[0]; revid = int(rev.get("revid")); rev_ts = str(rev.get("timestamp", ""))

        q2 = urlencode({
            "action": "parse", "oldid": str(revid), "prop": "text|revid",
            "format": "json", "formatversion": "2",
        })
        p2 = _fetch_json(f"{SOURCE_API}?{q2}")
        parsed = p2.get("parse") or {}; text = str(parsed.get("text") or "")
        if not text:
            raise RuntimeError(f"Parse API returned no HTML: {title}")
        raw = text.encode("utf-8")
        return text, {
            "key": key, "fetch_status": "OK", "title": title, "canonical_url": url,
            "cutoff_utc": HISTORICAL_CUTOFF_UTC, "revision_id": revid,
            "revision_timestamp": rev_ts, "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "html_sha256": hashlib.sha256(raw).hexdigest(), "html_bytes": len(raw),
        }
    except Exception as exc:
        return "", {
            "key": key, "fetch_status": "FAILED", "title": title, "canonical_url": url,
            "cutoff_utc": HISTORICAL_CUTOFF_UTC, "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _fetch_all_sources() -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    html_by_key: dict[str, str] = {}
    meta_by_key: dict[str, dict[str, object]] = {}
    for key, title, url in SOURCE_PAGES:
        text, meta = _fetch_cutoff_snapshot(key, title, url)
        html_by_key[key] = text
        meta_by_key[key] = meta
    return html_by_key, meta_by_key


def parse_reference_anchors(
    html_by_key: dict[str, str],
    meta_by_key: dict[str, dict[str, object]],
    targets: list[dict[str, str]],
) -> tuple[list[ParsedAnchor], list[dict[str, object]], dict[str, object]]:
    target_map = {(r.get("country_code", ""), r.get("metric", "")): r for r in targets}
    matches: dict[tuple[str, str], list[ParsedAnchor]] = defaultdict(list)
    diagnostics: list[dict[str, object]] = []
    tables_by_source: dict[str, int] = {}

    for source_key, html_text in html_by_key.items():
        if not html_text:
            tables_by_source[source_key] = 0
            continue
        parser = TableParser(); parser.feed(html_text); tables = parser.tables
        tables_by_source[source_key] = len(tables)
        meta = meta_by_key.get(source_key, {})
        source_title = str(meta.get("title", "")); source_url = str(meta.get("canonical_url", ""))
        revision = str(meta.get("revision_id", "")); revision_ts = str(meta.get("revision_timestamp", ""))
        sha = str(meta.get("html_sha256", ""))

        for ti, table in enumerate(tables):
            mode = _header_mode(table)
            for ri, row in enumerate(table):
                if not row or all(c.tag == "th" for c in row):
                    continue
                row_text = " | ".join(c.text for c in row if c.text)
                for (cc, metric), target in target_map.items():
                    aliases = COUNTRY_ALIASES.get(cc, (target.get("country", ""),))
                    ok, matched_alias, country_idx = _row_matches_alias(row, aliases)
                    if not ok:
                        continue
                    value, site, date_text, extraction = _extract_metric_from_row(row, country_idx, metric, mode)
                    if not math.isfinite(value):
                        diagnostics.append({
                            "country_code": cc, "country": target.get("country", ""), "metric": metric,
                            "status": "MATCHED_COUNTRY_BUT_METRIC_NOT_PARSED", "source_key": source_key,
                            "source_title": source_title, "source_revision": revision, "matched_alias": matched_alias,
                            "table_index": ti, "row_index": ri, "table_mode": mode,
                            "extraction": extraction, "source_row": row_text,
                        })
                        continue
                    years = _years(date_text)
                    if years and min(years) > HISTORICAL_CUTOFF_YEAR:
                        diagnostics.append({
                            "country_code": cc, "country": target.get("country", ""), "metric": metric,
                            "status": "REFERENCE_EVENT_AFTER_2025_CUTOFF_NOT_USED", "source_key": source_key,
                            "source_title": source_title, "source_revision": revision, "matched_alias": matched_alias,
                            "table_index": ti, "row_index": ri, "table_mode": mode, "extraction": extraction,
                            "value_c": f"{value:.1f}", "date_text": date_text, "source_row": row_text,
                        })
                        continue
                    confidence = "HIGH" if site and years else ("MEDIUM" if site or years else "LOW")
                    a = ParsedAnchor(
                        cc, target.get("country", ""), metric, value, site, date_text, _iso_date(date_text),
                        source_key, source_title, source_url, revision, revision_ts, sha, row_text,
                        matched_alias, ti, ri, confidence,
                    )
                    matches[(cc, metric)].append(a)
                    diagnostics.append({
                        "country_code": cc, "country": target.get("country", ""), "metric": metric,
                        "status": "PARSED_MAXCRC_CANDIDATE", "source_key": source_key,
                        "source_title": source_title, "source_revision": revision, "matched_alias": matched_alias,
                        "table_index": ti, "row_index": ri, "table_mode": mode, "extraction": extraction,
                        "value_c": f"{value:.1f}", "date_text": date_text, "source_row": row_text,
                    })

    accepted: list[ParsedAnchor] = []
    for key, target in target_map.items():
        found = matches.get(key, [])
        by_value: dict[float, list[ParsedAnchor]] = defaultdict(list)
        for a in found:
            by_value[round(a.value_c, 3)].append(a)
        if len(by_value) == 1:
            candidates = next(iter(by_value.values()))
            candidates.sort(key=lambda a: (
                0 if a.confidence == "HIGH" else 1 if a.confidence == "MEDIUM" else 2,
                0 if a.date_iso else 1, 0 if a.site else 1, a.source_key, a.table_index, a.row_index,
            ))
            accepted.append(candidates[0])
        elif len(by_value) > 1:
            diagnostics.append({
                "country_code": key[0], "country": target.get("country", ""), "metric": key[1],
                "status": "AMBIGUOUS_MULTIPLE_MAXCRC_VALUES", "source_key": "MULTIPLE",
                "values": " | ".join(str(v) for v in sorted(by_value)),
                "source_row": " || ".join(a.source_row for a in found[:10]),
            })
        else:
            diagnostics.append({
                "country_code": key[0], "country": target.get("country", ""), "metric": key[1],
                "status": "NO_MAXCRC_MATCH", "source_key": "", "source_row": "",
            })

    stats: dict[str, object] = {
        "source_pages": len(SOURCE_PAGES),
        "source_pages_ok": sum(1 for m in meta_by_key.values() if m.get("fetch_status") == "OK"),
        "html_tables_total": sum(tables_by_source.values()),
        "html_tables_by_source": tables_by_source,
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
    return [r for r in rows if r.get("stage5_record_eligible") == "yes" and r.get("stage5_record_candidate_rank") == "1"]


def _holds(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if r.get("stage5_status") != "REJECT_CONFIRMED" and str(r.get("stage5_record_eligibility", "")).startswith("HOLD")]


def _is_more_extreme(metric: str, a: float, b: float) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return a > b + 0.051 if metric == "tmax_highest" else a < b - 0.051


def _exact_support(anchor: ParsedAnchor, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if r.get("stage5_status") != "REJECT_CONFIRMED" and _same_value(_float(r.get("value_c")), anchor.value_c)]


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
        return "GHCN_MORE_EXTREME_THAN_MAXCRC", (
            f"A surviving/held GHCN value ({x:.1f} C) is more extreme than the Maxcrc reference "
            f"({anchor.value_c:.1f} C); raw GHCN is retained but the master follows the approved secondary reference."
        )
    best = max(vals) if anchor.metric == "tmax_highest" else min(vals)
    if _is_more_extreme(anchor.metric, anchor.value_c, best):
        return "MAXCRC_MORE_EXTREME_COVERAGE_GAP", (
            f"Maxcrc reference ({anchor.value_c:.1f} C) is more extreme than the best surviving GHCN candidate ({best:.1f} C)."
        )
    return "MAXCRC_REPLACES_UNRESOLVED", "Maxcrc resolves the open master row; no exact GHCN value match was found."


def _join_unique(values: list[str]) -> str:
    return " | ".join(dict.fromkeys(v for v in values if v))


def run(
    master_input: Path,
    candidate_input: Path,
    output_dir: Path,
    *,
    source_html_by_key: dict[str, str] | None = None,
    source_meta_by_key: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    master, master_fields = _read_csv(master_input, MASTER_REQUIRED)
    candidates, _ = _read_csv(candidate_input, CANDIDATE_REQUIRED)
    groups = _candidate_groups(candidates)

    stage8_unresolved = [r for r in master if r.get("master_status") == "UNRESOLVED_REVIEW"]
    targets = [r for r in stage8_unresolved if r.get("metric") in TARGET_METRICS]
    non_targets = [r for r in stage8_unresolved if r.get("metric") not in TARGET_METRICS]

    if source_html_by_key is None:
        source_html_by_key, source_meta_by_key = _fetch_all_sources()
    else:
        source_meta_by_key = dict(source_meta_by_key or {})
        for key, text in source_html_by_key.items():
            meta = dict(source_meta_by_key.get(key, {}))
            meta.setdefault("key", key); meta.setdefault("fetch_status", "TEST_OR_SUPPLIED_SNAPSHOT")
            meta.setdefault("title", f"User:Maxcrc/{key}")
            meta.setdefault("canonical_url", f"https://en.wikipedia.org/wiki/User:Maxcrc/{key}")
            meta.setdefault("cutoff_utc", HISTORICAL_CUTOFF_UTC); meta.setdefault("revision_id", "")
            meta.setdefault("revision_timestamp", ""); meta.setdefault("fetched_at_utc", datetime.now(timezone.utc).isoformat())
            meta.setdefault("html_sha256", hashlib.sha256(text.encode("utf-8")).hexdigest())
            meta.setdefault("html_bytes", len(text.encode("utf-8")))
            source_meta_by_key[key] = meta

    source_meta_by_key = dict(source_meta_by_key or {})
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir = output_dir / "maxcrc_source_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    for key, text in source_html_by_key.items():
        if text:
            (snapshots_dir / f"{key}.html").write_text(text, encoding="utf-8")
    (output_dir / "maxcrc_source_metadata_stage9.json").write_text(
        json.dumps(source_meta_by_key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    anchors, diagnostics, parser_stats = parse_reference_anchors(source_html_by_key, source_meta_by_key, targets)
    anchor_map = {(a.country_code, a.metric): a for a in anchors}

    extra_fields = [
        "stage9_previous_master_status", "stage9_resolution", "stage9_resolution_code",
        "stage9_reference_type", "stage9_reference_confidence", "stage9_reference_relation",
        "stage9_reference_source", "stage9_reference_page", "stage9_reference_revision",
        "stage9_reference_revision_timestamp", "stage9_reference_snapshot_sha256",
        "stage9_reference_row", "stage9_reference_date_text", "stage9_reference_notes",
    ]
    out_fields = master_fields + [f for f in extra_fields if f not in master_fields]

    updated: list[dict[str, object]] = []
    resolved: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []

    for src in master:
        row: dict[str, object] = dict(src)
        previous = src.get("master_status", "")
        key = (src.get("country_code", ""), src.get("metric", ""))
        row.update({
            "stage9_previous_master_status": previous, "stage9_resolution": "CARRIED_FORWARD",
            "stage9_resolution_code": "", "stage9_reference_type": "", "stage9_reference_confidence": "",
            "stage9_reference_relation": "", "stage9_reference_source": "", "stage9_reference_page": "",
            "stage9_reference_revision": "", "stage9_reference_revision_timestamp": "",
            "stage9_reference_snapshot_sha256": "", "stage9_reference_row": "",
            "stage9_reference_date_text": "", "stage9_reference_notes": "",
        })
        anchor = anchor_map.get(key)
        if previous != "UNRESOLVED_REVIEW" or src.get("metric") not in TARGET_METRICS or anchor is None:
            updated.append(row); continue

        group = groups.get(key, [])
        exact = _exact_support(anchor, group)
        relation, relation_note = _relation(anchor, group)
        row.update({
            "master_status": "SECONDARY_SOURCE_BACKED", "publishable": "yes",
            "canonical_value_c": f"{anchor.value_c:.1f}", "canonical_date": anchor.date_iso,
            "canonical_site": anchor.site,
            "canonical_station_id": _join_unique([str(r.get("station_id", "")) for r in exact]),
            "canonical_source": anchor.source_url,
            "canonical_source_type": "SECONDARY_REFERENCE_MAXCRC_CONTINENT",
            "official_verified": "no", "ghcn_support_count": len(exact), "unresolved_reason": "",
            "notes": "Maximiliano Herrera / Wikipedia User:Maxcrc continent table used as an explicitly approved secondary national absolute-record reference from the final revision at/before the 2025 historical cutoff. Not an official national-service verification.",
            "stage9_resolution": "RESOLVED", "stage9_resolution_code": "MAXCRC_NATIONAL_ABSOLUTE_RECORD_ACCEPTED",
            "stage9_reference_type": "MAXCRC_CONTINENT_SECONDARY",
            "stage9_reference_confidence": anchor.confidence, "stage9_reference_relation": relation,
            "stage9_reference_source": anchor.source_url, "stage9_reference_page": anchor.source_title,
            "stage9_reference_revision": anchor.source_revision,
            "stage9_reference_revision_timestamp": anchor.source_revision_timestamp,
            "stage9_reference_snapshot_sha256": anchor.source_snapshot_sha256,
            "stage9_reference_row": anchor.source_row, "stage9_reference_date_text": anchor.date_text,
            "stage9_reference_notes": relation_note,
        })
        updated.append(row); resolved.append(row)
        decisions.append({
            "country_code": anchor.country_code, "country": anchor.country, "metric": anchor.metric,
            "previous_status": previous, "new_status": "SECONDARY_SOURCE_BACKED",
            "canonical_value_c": f"{anchor.value_c:.1f}", "canonical_date": anchor.date_iso,
            "canonical_site": anchor.site, "matched_alias": anchor.matched_alias,
            "confidence": anchor.confidence, "relation_to_ghcn": relation,
            "source_page": anchor.source_title, "source": anchor.source_url,
            "source_revision": anchor.source_revision, "source_revision_timestamp": anchor.source_revision_timestamp,
            "source_row": anchor.source_row, "notes": relation_note,
        })

    publishable = [r for r in updated if r.get("publishable") == "yes"]
    unresolved = [r for r in updated if r.get("master_status") == "UNRESOLVED_REVIEW"]

    decision_fields = [
        "country_code", "country", "metric", "previous_status", "new_status", "canonical_value_c",
        "canonical_date", "canonical_site", "matched_alias", "confidence", "relation_to_ghcn",
        "source_page", "source", "source_revision", "source_revision_timestamp", "source_row", "notes",
    ]
    anchor_fields = [
        "country_code", "country", "metric", "value_c", "site", "date_text", "date_iso",
        "matched_alias", "confidence", "source_key", "source_title", "source_url", "source_revision",
        "source_revision_timestamp", "source_snapshot_sha256", "table_index", "row_index", "source_row",
    ]
    anchor_rows = [{
        "country_code": a.country_code, "country": a.country, "metric": a.metric,
        "value_c": f"{a.value_c:.1f}", "site": a.site, "date_text": a.date_text, "date_iso": a.date_iso,
        "matched_alias": a.matched_alias, "confidence": a.confidence, "source_key": a.source_key,
        "source_title": a.source_title, "source_url": a.source_url, "source_revision": a.source_revision,
        "source_revision_timestamp": a.source_revision_timestamp,
        "source_snapshot_sha256": a.source_snapshot_sha256, "table_index": a.table_index,
        "row_index": a.row_index, "source_row": a.source_row,
    } for a in anchors]
    diagnostic_fields = [
        "country_code", "country", "metric", "status", "source_key", "source_title", "source_revision",
        "matched_alias", "table_index", "row_index", "table_mode", "extraction", "value_c", "date_text",
        "values", "source_row",
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
    fetch_counts = Counter(str(m.get("fetch_status", "")) for m in source_meta_by_key.values())
    revisions = {k: m.get("revision_id", "") for k, m in source_meta_by_key.items()}
    revision_timestamps = {k: m.get("revision_timestamp", "") for k, m in source_meta_by_key.items()}
    snapshot_sha = {k: m.get("html_sha256", "") for k, m in source_meta_by_key.items()}

    summary: dict[str, object] = {
        "schema_version": 3,
        "stage": "world_ghcn_country_record_maxcrc_continent_resolution_stage9",
        "master_rows": len(updated), "stage8_unresolved_input_rows": len(stage8_unresolved),
        "stage9_target_rows_absolute_high_low": len(targets),
        "stage9_non_target_unresolved_rows": len(non_targets),
        "target_metric_counts": dict(sorted(target_metric_counts.items())),
        "source_pages_requested": len(SOURCE_PAGES), "source_fetch_status_counts": dict(sorted(fetch_counts.items())),
        "source_cutoff_utc": HISTORICAL_CUTOFF_UTC, "source_revision_ids": revisions,
        "source_revision_timestamps": revision_timestamps, "source_snapshot_sha256": snapshot_sha,
        "source_html_tables_total": parser_stats.get("html_tables_total", 0),
        "source_html_tables_by_source": parser_stats.get("html_tables_by_source", {}),
        "reference_anchor_rows": len(anchors), "resolved_in_stage9": len(resolved),
        "unresolved_after_stage9": len(unresolved), "publishable_after_stage9": len(publishable),
        "master_status_counts": dict(sorted(status_counts.items())),
        "stage9_relation_counts": dict(sorted(relation_counts.items())),
        "policy": "User:Maxcrc continent subpages are approved secondary national absolute-record references. Stage 9 targets only tmax_highest and tmin_lowest, revision-pins all six pages at/before 2025-12-31, never sets official_verified=yes, never deletes GHCN observations, and leaves ambiguous/unmatched rows unresolved.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = [
        "# World GHCN country record master · Stage 9 · Maxcrc continent tables",
        "",
        "Stage 9 uses the six user-approved Maximiliano Herrera / Wikipedia User:Maxcrc continent pages for unresolved national absolute maximum/minimum records.",
        "",
        "## Ergebnis",
        f"- Stage-8 unresolved am Eingang: {len(stage8_unresolved)}",
        f"- Zielmetrik tmax_highest/tmin_lowest: {len(targets)}",
        f"- Andere offene Metriken bewusst nicht angefasst: {len(non_targets)}",
        f"- Maxcrc-Anker eindeutig geparst: {len(anchors)}",
        f"- In Stage 9 aufgelöst: {len(resolved)}",
        f"- Danach weiterhin unresolved: {len(unresolved)}",
        f"- Publishable nach Stage 9: {len(publishable)}",
        "",
        "## Quellen",
    ]
    for key, title, url in SOURCE_PAGES:
        meta = source_meta_by_key.get(key, {})
        report.append(f"- {title}: {url} | status={meta.get('fetch_status','')} | revision={meta.get('revision_id','')} | {meta.get('revision_timestamp','')}")
    report += [
        "",
        "## Regeln",
        f"- Historischer Cutoff: {HISTORICAL_CUTOFF_UTC}",
        "- Jede der sechs Seiten wird separat auf die letzte Revision am/vor dem Cutoff gepinnt.",
        "- Maxcrc bleibt SECONDARY_SOURCE_BACKED; official_verified bleibt no.",
        "- GHCN-Rohbeobachtungen werden nie verändert oder gelöscht.",
        "- Mehrdeutige/fehlende Länder bleiben UNRESOLVED_REVIEW.",
        "- tmin_highest und tmax_lowest bleiben für eine spätere Spezialquellen-Stufe offen.",
    ]
    (output_dir / "qc_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def self_test() -> None:
    master_fields = [
        "country_code", "country", "metric", "master_status", "publishable", "canonical_value_c",
        "canonical_date", "canonical_site", "canonical_station_id", "canonical_source",
        "canonical_source_type", "official_verified", "official_anchor_id", "official_coverage_status",
        "ghcn_support_count", "ghcn_candidate_tie_count", "fallback_candidate_value_c",
        "fallback_candidate_events", "held_more_extreme_count", "held_more_extreme_events",
        "unresolved_reason", "notes",
    ]
    candidate_fields = [
        "country_code", "country", "metric", "value_c", "date", "station_id", "station_name",
        "stage5_status", "stage5_record_eligibility", "stage5_record_eligible", "stage5_record_candidate_rank",
    ]

    def m(cc: str, country: str, metric: str) -> dict[str, object]:
        return {
            "country_code": cc, "country": country, "metric": metric, "master_status": "UNRESOLVED_REVIEW",
            "publishable": "no", "canonical_value_c": "", "canonical_date": "", "canonical_site": "",
            "canonical_station_id": "", "canonical_source": "", "canonical_source_type": "NONE_UNRESOLVED",
            "official_verified": "no", "official_anchor_id": "", "official_coverage_status": "",
            "ghcn_support_count": 0, "ghcn_candidate_tie_count": 1, "fallback_candidate_value_c": "",
            "fallback_candidate_events": "", "held_more_extreme_count": 0, "held_more_extreme_events": "",
            "unresolved_reason": "RANK1_REVIEW_REMAINS", "notes": "",
        }

    masters = [
        m("GH", "Ghana", "tmax_highest"), m("KN", "Korea, North", "tmin_lowest"),
        m("IT", "Italy", "tmin_lowest"), m("IS", "Israel", "tmin_highest"),
    ]
    cands = [
        {"country_code":"GH","country":"Ghana","metric":"tmax_highest","value_c":"48.8","date":"1993-03-05","station_id":"GH1","station_name":"TAMALE","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
        {"country_code":"KN","country":"Korea, North","metric":"tmin_lowest","value_c":"-37.2","date":"1958-01-23","station_id":"KN1","station_name":"CHUNGGANG","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
        {"country_code":"IT","country":"Italy","metric":"tmin_lowest","value_c":"-35.0","date":"1971-03-06","station_id":"IT1","station_name":"PIAN ROSA","stage5_status":"REVIEW","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
        {"country_code":"IS","country":"Israel","metric":"tmin_highest","value_c":"37.0","date":"1997-07-05","station_id":"IS1","station_name":"ELAT","stage5_status":"REVIEW_CRITICAL","stage5_record_eligibility":"ELIGIBLE_CANDIDATE","stage5_record_eligible":"yes","stage5_record_candidate_rank":"1"},
    ]
    # Maxcrc classic layout: Country | Lowest T | place | date | Highest T | place | date
    africa_html = """
    <table class='wikitable'>
      <tr><th>Country</th><th colspan='3'>Lowest Temperature</th><th colspan='3'>Highest Temperature</th></tr>
      <tr><th></th><th>T C</th><th>Place</th><th>Date</th><th>T C</th><th>Place</th><th>Date</th></tr>
      <tr><td>Ghana</td><td>9.4</td><td>Bole</td><td>10 January 1971</td><td>43.8</td><td>Navrongo</td><td>6 March 2013</td></tr>
    </table>"""
    asia_html = """
    <table><tr><th>Country</th><th colspan='3'>Lowest Temperature</th><th colspan='3'>Highest Temperature</th></tr>
      <tr><td>North Korea</td><td>-43.6</td><td>Sinmusong</td><td>2 January 1977</td><td>40.5</td><td>Hoeryong</td><td>30 July 2018</td></tr></table>"""
    europe_html = """
    <table><tr><th>Country</th><th colspan='3'>Lowest Temperature</th><th colspan='3'>Highest Temperature</th></tr>
      <tr><td>Italy</td><td>-49.6</td><td>Busa Fradusta</td><td>10 February 2013</td><td>48.8</td><td>Floridia</td><td>11 August 2021</td></tr></table>"""

    supplied = {"Africa": africa_html, "Asia": asia_html, "Europe": europe_html,
                "North_America": "", "South_America": "", "Oceania": ""}
    meta = {k: {"fetch_status":"TEST", "revision_id":100+i, "revision_timestamp":"2025-12-30T00:00:00Z",
                "title":f"User:Maxcrc/{k}", "canonical_url":f"https://en.wikipedia.org/wiki/User:Maxcrc/{k}",
                "html_sha256":f"sha{i}"} for i, k in enumerate(supplied)}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td); mp = root / "master.csv"; cp = root / "cands.csv"; out = root / "out"
        with mp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=master_fields, delimiter=";"); w.writeheader(); w.writerows(masters)
        with cp.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.DictWriter(h, fieldnames=candidate_fields, delimiter=";"); w.writeheader(); w.writerows(cands)
        summary = run(mp, cp, out, source_html_by_key=supplied, source_meta_by_key=meta)
        assert summary["stage8_unresolved_input_rows"] == 4, summary
        assert summary["stage9_target_rows_absolute_high_low"] == 3, summary
        assert summary["reference_anchor_rows"] == 3, summary
        assert summary["resolved_in_stage9"] == 3, summary
        rows, _ = _read_csv(out / "world_country_record_master_stage9.csv", MASTER_REQUIRED)
        by = {(r["country_code"], r["metric"]): r for r in rows}
        assert by[("GH","tmax_highest")]["canonical_value_c"] == "43.8", by[("GH","tmax_highest")]
        assert by[("GH","tmax_highest")]["canonical_date"] == "2013-03-06"
        assert by[("KN","tmin_lowest")]["canonical_value_c"] == "-43.6"
        assert by[("IT","tmin_lowest")]["canonical_value_c"] == "-49.6"
        assert by[("IS","tmin_highest")]["master_status"] == "UNRESOLVED_REVIEW"
    print("SELF-TEST OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--master-input", type=Path)
    p.add_argument("--candidate-input", type=Path)
    p.add_argument("--output-dir", type=Path, default=Path("world_ghcn_baseline/qc_stage9"))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.master_input or not args.candidate_input:
        p.error("--master-input and --candidate-input are required unless --self-test is used")
    summary = run(args.master_input, args.candidate_input, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
