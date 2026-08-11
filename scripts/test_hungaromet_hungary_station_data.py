#!/usr/bin/env python3
"""
HungaroMet Hungary station-data probe for climate-dashboard.

Official sources
----------------
Long controlled daily station series (10 stations, from 1901):
  https://odp.met.hu/climate/station_data_series/daily/from_1901/

Operational daily observations, historical archive:
  https://odp.met.hu/climate/observations_hungary/daily/historical/

Operational daily observations, current year:
  https://odp.met.hu/climate/observations_hungary/daily/recent/

Automatic-station metadata:
  https://odp.met.hu/climate/observations_hungary/meta/station_meta_auto.csv

The probe intentionally does NOT yet build a production baseline. It discovers
what HungaroMet currently publishes and prints enough schema/details to make the
production integration deterministic:
- count and date coverage of historical daily station ZIPs
- count of current-year station ZIPs and overlap with history
- current automatic-station metadata schema and coordinate-like columns
- inventory of the 10 long official TX/TN series (1901 through previous year)
- ZIP member names, CSV headers and sample rows for long, historical and current
  products
- schema consistency across a configurable current/historical sample

No API key or secret is required.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

BASE = "https://odp.met.hu/climate"
LONG_TX_INDEX = f"{BASE}/station_data_series/daily/from_1901/maximum_temperature/"
LONG_TN_INDEX = f"{BASE}/station_data_series/daily/from_1901/minimum_temperature/"
LONG_META_INDEX = f"{BASE}/station_data_series/daily/from_1901/meta/"
OBS_HIST_INDEX = f"{BASE}/observations_hungary/daily/historical/"
OBS_RECENT_INDEX = f"{BASE}/observations_hungary/daily/recent/"
OBS_META_URL = f"{BASE}/observations_hungary/meta/station_meta_auto.csv"

UA = "climate-dashboard-hungaromet-hungary-probe/2.0"
TIMEOUT = 120
TRIES = 5


def log(msg: str = "") -> None:
    print(msg, flush=True)


def http_bytes(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            RuntimeError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(30, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)
    raise RuntimeError(str(last))


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def hrefs(html: str) -> list[str]:
    return re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)


def list_urls(index_url: str, pattern: str) -> list[tuple[re.Match[str], str]]:
    text = decode(http_bytes(index_url))
    rx = re.compile(pattern, flags=re.I)
    out: list[tuple[re.Match[str], str]] = []
    for href in hrefs(text):
        name = urllib.parse.unquote(href).rsplit("/", 1)[-1]
        m = rx.fullmatch(name)
        if m:
            out.append((m, urllib.parse.urljoin(index_url, href)))
    return out


def sniff_table(text: str) -> tuple[str, list[list[str]]]:
    sample = "\n".join(text.splitlines()[:30])
    delimiter = None
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    if delimiter is None:
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        delimiter = max(counts, key=counts.get)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return delimiter, rows


def compact(row: Iterable[str], max_len: int = 220) -> str:
    text = " | ".join(str(x).strip() for x in row)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


@dataclass
class ZipSchema:
    url: str
    members: list[str]
    data_member: str
    delimiter: str
    header: tuple[str, ...]
    first_row: tuple[str, ...]
    rows: int
    markers: tuple[str, ...] = tuple()
    meta_header: tuple[str, ...] = tuple()
    meta_row: tuple[str, ...] = tuple()
    measurement_header: tuple[str, ...] = tuple()
    measurement_rows: tuple[tuple[str, ...], ...] = tuple()
    raw_preview: tuple[str, ...] = tuple()


def _clean_row(row: list[str]) -> tuple[str, ...]:
    return tuple(str(x).strip() for x in row)


def _first_table_row(rows: list[list[str]], start: int, stop: int | None = None) -> tuple[int, tuple[str, ...]] | None:
    stop = len(rows) if stop is None else min(stop, len(rows))
    for i in range(max(0, start), stop):
        row = _clean_row(rows[i])
        nonempty = [x for x in row if x]
        if len(nonempty) >= 2:
            return i, row
    return None


def _section_bounds(rows: list[list[str]], marker_name: str) -> tuple[int, int] | None:
    marker_name = marker_name.lower()
    starts: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        first = str(row[0]).strip() if row else ""
        if first.startswith("##"):
            starts.append((i, first.lower()))
    for pos, (idx, name) in enumerate(starts):
        if name == marker_name:
            end = starts[pos + 1][0] if pos + 1 < len(starts) else len(rows)
            return idx + 1, end
    return None


def inspect_zip(url: str) -> ZipSchema:
    raw = http_bytes(url)
    if not raw.startswith(b"PK"):
        raise RuntimeError(f"Kein ZIP: {url} ({raw[:20]!r})")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if not members:
            raise RuntimeError(f"Leeres ZIP: {url}")
        csv_members = [n for n in members if n.lower().endswith((".csv", ".txt", ".dat"))]
        member = csv_members[0] if csv_members else members[0]
        text = decode(zf.read(member))

    delimiter, rows = sniff_table(text)
    nonempty = [r for r in rows if any(str(x).strip() for x in r)]
    header = tuple(nonempty[0]) if nonempty else tuple()
    first = tuple(nonempty[1]) if len(nonempty) > 1 else tuple()

    markers = tuple(
        str(row[0]).strip()
        for row in rows
        if row and str(row[0]).strip().startswith("##")
    )

    meta_header: tuple[str, ...] = tuple()
    meta_row: tuple[str, ...] = tuple()
    meta_bounds = _section_bounds(rows, "##meta")
    if meta_bounds:
        mh = _first_table_row(rows, *meta_bounds)
        if mh:
            hi, meta_header = mh
            mr = _first_table_row(rows, hi + 1, meta_bounds[1])
            if mr:
                _, meta_row = mr

    measurement_header: tuple[str, ...] = tuple()
    measurement_rows: list[tuple[str, ...]] = []
    data_bounds = _section_bounds(rows, "##data")
    if data_bounds:
        dh = _first_table_row(rows, *data_bounds)
        if dh:
            hi, measurement_header = dh
            for i in range(hi + 1, data_bounds[1]):
                row = _clean_row(rows[i])
                if len([x for x in row if x]) >= 2:
                    measurement_rows.append(row)
                    if len(measurement_rows) >= 3:
                        break

    # Defensive fallback: some ODP products may not label the measurement
    # section exactly as ##Data. Find the first multi-column row after Meta
    # whose field names look date/time/meteorology-like.
    if not measurement_header:
        candidates = ("date", "time", "datum", "tx", "tn", "tmax", "tmin", "ta", "temperature")
        for i, row0 in enumerate(rows):
            row = _clean_row(row0)
            if len([x for x in row if x]) < 2:
                continue
            low = " | ".join(row).lower().lstrip("#")
            if any(token in low for token in candidates):
                if row == meta_header:
                    continue
                measurement_header = row
                for j in range(i + 1, min(len(rows), i + 8)):
                    rr = _clean_row(rows[j])
                    if rr and rr[0].startswith("##"):
                        break
                    if len([x for x in rr if x]) >= 2:
                        measurement_rows.append(rr)
                        if len(measurement_rows) >= 3:
                            break
                break

    raw_preview = tuple(text.splitlines()[:24])
    return ZipSchema(
        url=url,
        members=members,
        data_member=member,
        delimiter=delimiter,
        header=header,
        first_row=first,
        rows=max(0, len(nonempty) - 1),
        markers=markers,
        meta_header=meta_header,
        meta_row=meta_row,
        measurement_header=measurement_header,
        measurement_rows=tuple(measurement_rows),
        raw_preview=raw_preview,
    )


def print_schema(title: str, schema: ZipSchema) -> None:
    log(f"\n--- {title} ---")
    log(f"URL: {schema.url}")
    log(f"ZIP-Mitglieder: {schema.members[:8]}" + (" …" if len(schema.members) > 8 else ""))
    log(f"Datendatei: {schema.data_member}")
    log(f"Trennzeichen: {repr(schema.delimiter)}")
    log(f"Abschnittsmarker: {list(schema.markers)}")
    log(f"Erste nichtleere Zeile ({len(schema.header)}): {compact(schema.header, 700)}")
    log(f"Zweite nichtleere Zeile: {compact(schema.first_row, 700)}")
    log(f"Nichtleere Folgezeilen: {schema.rows:,}")
    if schema.meta_header:
        log(f"META-Header ({len(schema.meta_header)}): {compact(schema.meta_header, 900)}")
    if schema.meta_row:
        log(f"META-Beispiel: {compact(schema.meta_row, 900)}")
    if schema.measurement_header:
        log(f"MESSDATEN-Header ({len(schema.measurement_header)}): {compact(schema.measurement_header, 1200)}")
        for i, row in enumerate(schema.measurement_rows, 1):
            log(f"MESSDATEN-Beispiel {i}: {compact(row, 1200)}")
    else:
        log("WARNUNG: Kein Messdaten-Header erkannt. Rohvorschau folgt:")
        for i, line in enumerate(schema.raw_preview, 1):
            log(f"RAW {i:02d}: {line[:1400]}")


def long_inventory() -> dict[str, object]:
    tx_items = list_urls(LONG_TX_INDEX, r"tx_o_(.+)_(\d{4})(\d{4})\.csv\.zip")
    tn_items = list_urls(LONG_TN_INDEX, r"tn_o_(.+)_(\d{4})(\d{4})\.csv\.zip")
    tx = {m.group(1): (int(m.group(2)), int(m.group(3)), url) for m, url in tx_items}
    tn = {m.group(1): (int(m.group(2)), int(m.group(3)), url) for m, url in tn_items}
    paired = sorted(set(tx) & set(tn))
    return {"tx": tx, "tn": tn, "paired": paired}


def obs_inventory() -> dict[str, object]:
    hist_items = list_urls(
        OBS_HIST_INDEX,
        r"HABP_1D_(\d+)_(\d{8})_(\d{8})_hist\.zip",
    )
    recent_items = list_urls(
        OBS_RECENT_INDEX,
        r"HABP_1D_(\d+)_akt\.zip",
    )

    hist_by_station: dict[str, list[tuple[str, str, str]]] = {}
    starts: list[str] = []
    ends: list[str] = []
    for m, url in hist_items:
        sid, start, end = m.group(1), m.group(2), m.group(3)
        hist_by_station.setdefault(sid, []).append((start, end, url))
        starts.append(start)
        ends.append(end)

    recent = {m.group(1): url for m, url in recent_items}
    return {
        "hist_items": hist_items,
        "hist_by_station": hist_by_station,
        "recent": recent,
        "earliest": min(starts) if starts else None,
        "latest": max(ends) if ends else None,
    }


def inspect_metadata() -> None:
    text = decode(http_bytes(OBS_META_URL))
    delim, rows = sniff_table(text)
    nonempty = [r for r in rows if any(str(x).strip() for x in r)]
    log("\n=== AUTOMATEN-METADATEN ===")
    log(f"Quelle: {OBS_META_URL}")
    log(f"Trennzeichen: {repr(delim)}")
    log(f"Zeilen inkl. Header: {len(nonempty):,}")
    if nonempty:
        log(f"Header ({len(nonempty[0])}): {compact(nonempty[0], 500)}")
    for i, row in enumerate(nonempty[1:4], 1):
        log(f"Beispiel {i}: {compact(row, 500)}")


def schema_signature(schema: ZipSchema) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    suffixes = tuple(sorted(n.rsplit(".", 1)[-1].lower() for n in schema.members if "." in n))
    effective = schema.measurement_header or schema.header
    return schema.delimiter, effective, suffixes


def inspect_many(label: str, urls: list[str], workers: int) -> None:
    if not urls:
        log(f"{label}: keine URLs")
        return
    counts: Counter[tuple[str, tuple[str, ...], tuple[str, ...]]] = Counter()
    failures: list[tuple[str, str]] = []
    examples: dict[tuple[str, tuple[str, ...], tuple[str, ...]], ZipSchema] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(inspect_zip, url): url for url in urls}
        for fut in as_completed(futs):
            url = futs[fut]
            try:
                schema = fut.result()
                sig = schema_signature(schema)
                counts[sig] += 1
                examples.setdefault(sig, schema)
            except Exception as exc:
                failures.append((url, str(exc)))
    log(f"\n=== SCHEMA-STICHPROBE: {label} ===")
    log(f"Geprüft: {len(urls)} | erfolgreich: {sum(counts.values())} | Fehler: {len(failures)}")
    for n, (sig, count) in enumerate(counts.most_common(), 1):
        delim, header, suffixes = sig
        log(f"Schema {n}: {count} Datei(en), delimiter={repr(delim)}, members={suffixes}")
        log(f"  Messdaten-Header: {compact(header, 1200)}")
        ex = examples[sig]
        log(f"  Beispiel: {ex.url}")
        log(f"  Erstes Messdaten-Beispiel: {compact(ex.measurement_rows[0] if ex.measurement_rows else ex.first_row, 1200)}")
    for url, err in failures[:5]:
        log(f"FEHLER: {url}: {err}")


def self_test() -> None:
    html = '<a href="HABP_1D_13711_akt.zip">x</a><a href="foo">y</a>'
    assert hrefs(html)[0] == "HABP_1D_13711_akt.zip"

    text = "date;tx;tn\n20260101;5.2;-1.0\n"
    delim, rows = sniff_table(text)
    assert delim == ";"
    assert rows[0] == ["date", "tx", "tn"]

    section_text = "##Meta\n#StationNumber;StartDate;EndDate\n13704;20050727;20260811\n##Data\n#StationNumber;Date;TA;TX;TN\n13704;20260810;24.1;31.2;17.4\n"
    d2, r2 = sniff_table(section_text)
    assert d2 == ";"
    mb = _section_bounds(r2, "##meta")
    db = _section_bounds(r2, "##data")
    assert mb and db
    assert _first_table_row(r2, *db)[1][1] == "Date"

    m = re.fullmatch(r"HABP_1D_(\d+)_(\d{8})_(\d{8})_hist\.zip", "HABP_1D_13711_20031107_20251231_hist.zip", flags=re.I)
    assert m and m.group(1) == "13711" and m.group(2) == "20031107"

    m2 = re.fullmatch(r"tx_o_(.+)_(\d{4})(\d{4})\.csv\.zip", "tx_o_Budapest_19012025.csv.zip", flags=re.I)
    assert m2 and m2.group(1) == "Budapest" and m2.group(2) == "1901"

    log("HungaroMet Hungary probe self-test OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--sample-current", type=int, default=12)
    ap.add_argument("--sample-historical", type=int, default=4)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    log("=== HUNGAROMET UNGARN PROBE ===")
    log("Offizielle ODP-Quelle, kein API-Key erforderlich.\n")

    long = long_inventory()
    tx = long["tx"]
    tn = long["tn"]
    paired = long["paired"]
    assert isinstance(tx, dict) and isinstance(tn, dict) and isinstance(paired, list)

    log("=== LANGE KONTROLLIERTE TAGESREIHEN ===")
    log(f"TX-Reihen: {len(tx)}")
    log(f"TN-Reihen: {len(tn)}")
    log(f"Gemeinsame TX+TN-Orte: {len(paired)}")
    log("Orte: " + ", ".join(paired))
    if paired:
        spans = [(name, tx[name][0], min(tx[name][1], tn[name][1])) for name in paired]
        earliest = min(spans, key=lambda x: x[1])
        latest_end = max(x[2] for x in spans)
        log(f"Frühester Beginn: {earliest[1]} ({earliest[0]})")
        log(f"Jüngstes Endjahr im Bestand: {latest_end}")
        name = paired[0]
        print_schema(f"Lange TX-Reihe · {name}", inspect_zip(tx[name][2]))
        print_schema(f"Lange TN-Reihe · {name}", inspect_zip(tn[name][2]))

    obs = obs_inventory()
    hist_items = obs["hist_items"]
    hist_by_station = obs["hist_by_station"]
    recent = obs["recent"]
    assert isinstance(hist_items, list) and isinstance(hist_by_station, dict) and isinstance(recent, dict)

    log("\n=== OPERATIVES TAGESNETZ ===")
    log(f"Historische ZIP-Segmente: {len(hist_items):,}")
    log(f"Historische Stations-IDs: {len(hist_by_station):,}")
    log(f"Dateibereich laut Namen: {obs['earliest']} bis {obs['latest']}")
    log(f"Aktuelles Jahr · Stations-ZIPs: {len(recent):,}")
    log(f"Historisch ∩ aktuell: {len(set(hist_by_station) & set(recent)):,}")
    log(f"Nur aktuell ohne historisches Segment: {len(set(recent) - set(hist_by_station)):,}")

    inspect_metadata()

    current_urls = [recent[k] for k in sorted(recent)[: max(0, args.sample_current)]]
    hist_urls: list[str] = []
    for sid in sorted(hist_by_station):
        segs = sorted(hist_by_station[sid])
        if segs:
            hist_urls.append(segs[-1][2])
        if len(hist_urls) >= max(0, args.sample_historical):
            break

    if current_urls:
        print_schema("Aktuelles Tagesnetz · erstes ZIP", inspect_zip(current_urls[0]))
    if hist_urls:
        print_schema("Historisches Tagesnetz · erstes ZIP", inspect_zip(hist_urls[0]))

    inspect_many("aktuell", current_urls, args.workers)
    inspect_many("historisch", hist_urls, args.workers)

    log("\n=== FAZIT FÜR DIE NÄCHSTE INTEGRATIONSSTUFE ===")
    log("Bitte den vollständigen GitHub-Log dieses Probe-Runs schicken.")
    log("Entscheidend ist jetzt die Zeile MESSDATEN-Header der HABP_1D-ZIPs.")
    log("Wenn dort TX/TN bzw. die Temperatur-Maximum/-Minimum-Spalten sichtbar sind, folgt direkt der produktive Ungarn-Cache + Current-Builder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
