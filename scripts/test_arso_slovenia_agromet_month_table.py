#!/usr/bin/env python3
"""ARSO Slowenien: direkter Test der echten Monats-Tagesdateien.

Schritt 5 – noch kein Produktionscache.

Der vorherige GitHub-Lauf hat den ARSO-JavaScript-Code eindeutig gezeigt:

    var pot = "https://meteo.arso.gov.si/uploads/probase/www/agromet/product/form/sl/data/"
    post1 = document.podform.postaja.value;
    filen = pot + post1 + "_" + let + mes + ".txt";

Wichtig:
- `post1` ist die dreistellige numerische Stations-ID, z. B. 192.
- `let` ist YYYY.
- `mes` ist MM.
- Der echte Dateiname ist damit z. B. 192_202607.txt.
- Die Stations-Slugs aus dem alten Formularteil sind hierfür NICHT korrekt.

Dieses Skript:
1. lädt die ARSO-Monatsseite;
2. liest die numerischen Stations-IDs und Stationsnamen aus;
3. testet mehrere bekannte Dateien exakt nach ID_YYYYMM.txt;
4. druckt Header und Rohdatenbeispiele;
5. erkennt Tmin/Tmax-Spalten;
6. prüft historische und aktuelle Monate;
7. ermittelt für einige Stationen den ersten/letzten verfügbaren Monats-Treffer.

Kein OCR, kein Scraping von Diagrammen, kein Produktionscache.
"""

from __future__ import annotations

import csv
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE = "https://meteo.arso.gov.si"
MONTH_URL = f"{BASE}/met/sl/agromet/data/month/"
DATA_BASE = f"{BASE}/uploads/probase/www/agromet/product/form/sl/data/"

UA = "climate-dashboard-slovenia-arso-direct-month-file-probe/1.0 (+GitHub Actions)"
TIMEOUT = 60
TRIES = 4

# IDs directly observed in the official ARSO form.
TESTS = (
    ("192", "Ljubljana Bežigrad", 2026, 7),
    ("097", "Bilje", 2026, 7),
    ("048", "Kredarica", 2026, 1),
    ("249", "Novo mesto", 2025, 7),
    ("268", "Celje Medlog", 2026, 7),
    ("355", "Murska Sobota", 2026, 7),
    ("464", "Portorož - letališče", 2026, 7),
    ("311", "Maribor - letališče", 2026, 7),
)

# Small availability checks across time.  We intentionally do not crawl every
# station/month yet.
HISTORY_TESTS = (
    ("192", "Ljubljana Bežigrad", (1961, 1), (1991, 7), (2016, 12), (2017, 1), (2025, 12)),
    ("097", "Bilje", (1962, 1), (1991, 7), (2016, 12), (2017, 1), (2025, 12)),
    ("048", "Kredarica", (1961, 1), (1991, 7), (2016, 12), (2017, 1), (2025, 12)),
    ("249", "Novo mesto", (1961, 1), (1991, 7), (2016, 12), (2017, 1), (2025, 12)),
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_bytes(
    url: str,
    *,
    attempts: int = TRIES,
) -> tuple[bytes, str, int, str]:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/plain,text/csv,text/html,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return (
                    response.read(),
                    response.geturl(),
                    getattr(response, "status", 200),
                    response.headers.get("Content-Type", ""),
                )
        except urllib.error.HTTPError as exc:
            # A missing historical monthly file should be reported immediately,
            # not retried four times.
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:
            last = exc

        if attempt < attempts:
            time.sleep(attempt * 2)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def decode_bytes(raw: bytes, content_type: str = "") -> tuple[str, str]:
    candidates = []

    charset = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, flags=re.I)
    if charset:
        candidates.append(charset.group(1))

    candidates.extend(("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"))

    seen = set()
    for encoding in candidates:
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass

    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def request_text(
    url: str,
    *,
    attempts: int = TRIES,
) -> tuple[str, str, int, str, str]:
    raw, final, status, ctype = request_bytes(url, attempts=attempts)
    text, encoding = decode_bytes(raw, ctype)
    return text, final, status, ctype, encoding


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def normalize_header(value: str) -> str:
    value = html.unescape(value).strip().lower()
    for old, new in (
        ("č", "c"),
        ("š", "s"),
        ("ž", "z"),
        ("°", ""),
    ):
        value = value.replace(old, new)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def data_url(station_id: str, year: int, month: int) -> str:
    return f"{DATA_BASE}{station_id}_{year:04d}{month:02d}.txt"


def parse_numeric_station_options(page: str) -> list[dict[str, str]]:
    """Extract the real numeric station dropdown from the ARSO form."""
    selects = list(
        re.finditer(
            r"<select\b([^>]*)>(.*?)</select>",
            page,
            flags=re.I | re.S,
        )
    )

    candidates = []

    for select in selects:
        attrs, body = select.group(1), select.group(2)

        options = []
        for opt in re.finditer(
            r"<option\b([^>]*)>(.*?)</option>",
            body,
            flags=re.I | re.S,
        ):
            attrs2 = opt.group(1)
            label = strip_tags(opt.group(2))
            vm = re.search(
                r"\bvalue\s*=\s*['\"]?([^'\"\s>]+)",
                attrs2,
                flags=re.I,
            )
            value = html.unescape(vm.group(1)).strip() if vm else ""
            options.append((value, label))

        numeric = [
            (value, label)
            for value, label in options
            if re.fullmatch(r"\d{3}", value)
        ]

        if len(numeric) >= 10:
            candidates.append(numeric)

    if not candidates:
        return []

    # Pick the largest numeric dropdown.
    best = max(candidates, key=len)

    return [
        {
            "id": value,
            "label": label,
        }
        for value, label in best
    ]


def detect_delimiter(lines: list[str]) -> str | None:
    sample = "\n".join(lines[:40])
    candidates = ("\t", ";", "|", ",")
    counts = {delimiter: sample.count(delimiter) for delimiter in candidates}
    best = max(counts, key=counts.get)
    if counts[best] <= 0:
        return None
    return best


def header_has_tmin(token: str) -> bool:
    token = normalize_header(token)
    return token in {
        "tmin",
        "tn",
        "min",
        "temp_min",
        "temperatura_min",
        "minimalna_temperatura",
        "t_min",
    } or "tmin" in token


def header_has_tmax(token: str) -> bool:
    token = normalize_header(token)
    return token in {
        "tmax",
        "tx",
        "max",
        "temp_max",
        "temperatura_max",
        "maksimalna_temperatura",
        "t_max",
    } or "tmax" in token


def parse_table(text: str) -> dict[str, Any]:
    """Best-effort parser for the actual ARSO monthly TXT file."""
    result: dict[str, Any] = {
        "kind": None,
        "delimiter": None,
        "headers": [],
        "rows": [],
        "has_tmin": False,
        "has_tmax": False,
    }

    # Some .txt files may actually contain HTML tables.
    for table_match in re.finditer(
        r"<table\b.*?</table>",
        text,
        flags=re.I | re.S,
    ):
        table = table_match.group(0)
        parsed_rows = []

        for row_html in re.findall(
            r"<tr\b[^>]*>(.*?)</tr>",
            table,
            flags=re.I | re.S,
        ):
            cells = [
                strip_tags(cell)
                for cell in re.findall(
                    r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
                    row_html,
                    flags=re.I | re.S,
                )
            ]
            if cells:
                parsed_rows.append(cells)

        for idx, row in enumerate(parsed_rows[:8]):
            headers = [normalize_header(x) for x in row]
            has_tmin = any(header_has_tmin(x) for x in headers)
            has_tmax = any(header_has_tmax(x) for x in headers)

            if has_tmin or has_tmax:
                result.update(
                    {
                        "kind": "html",
                        "headers": headers,
                        "rows": parsed_rows[idx + 1 :],
                        "has_tmin": has_tmin,
                        "has_tmax": has_tmax,
                    }
                )
                return result

    # Plain/delimited text.
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return result

    delimiter = detect_delimiter(lines)

    for idx, line in enumerate(lines[:80]):
        row_variants = []

        if delimiter:
            try:
                row_variants.append(
                    next(csv.reader([line], delimiter=delimiter))
                )
            except Exception:
                pass

        # ARSO may use aligned whitespace rather than a CSV separator.
        row_variants.append(re.split(r"\s{2,}", line.strip()))

        for raw_headers in row_variants:
            headers = [normalize_header(x) for x in raw_headers]
            has_tmin = any(header_has_tmin(x) for x in headers)
            has_tmax = any(header_has_tmax(x) for x in headers)

            if not (has_tmin or has_tmax):
                continue

            rows = []
            for data_line in lines[idx + 1 :]:
                try:
                    if delimiter:
                        row = next(csv.reader([data_line], delimiter=delimiter))
                    else:
                        row = re.split(r"\s{2,}", data_line.strip())
                except Exception:
                    row = [data_line]
                rows.append(row)

            result.update(
                {
                    "kind": "delimited" if delimiter else "text",
                    "delimiter": delimiter,
                    "headers": headers,
                    "rows": rows,
                    "has_tmin": has_tmin,
                    "has_tmax": has_tmax,
                }
            )
            return result

    return result


def is_no_data(text: str) -> bool:
    cleaned = strip_tags(text).lower().strip()
    return cleaned in {
        "",
        "ni podatkov!",
        "ni podatkov",
        "no data!",
        "no data",
    }


def inspect_file(
    station_id: str,
    name: str,
    year: int,
    month: int,
    *,
    show_raw: bool,
) -> dict[str, Any]:
    url = data_url(station_id, year, month)

    try:
        text, final, status, ctype, encoding = request_text(url, attempts=2)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "exists": False,
                "url": url,
                "status": 404,
                "station_id": station_id,
                "station": name,
                "year": year,
                "month": month,
            }
        raise
    except Exception as exc:
        return {
            "exists": False,
            "url": url,
            "error": str(exc),
            "station_id": station_id,
            "station": name,
            "year": year,
            "month": month,
        }

    parsed = parse_table(text)

    info = {
        "exists": status == 200 and not is_no_data(text),
        "http_ok": status == 200,
        "url": final,
        "status": status,
        "content_type": ctype,
        "encoding": encoding,
        "chars": len(text),
        "station_id": station_id,
        "station": name,
        "year": year,
        "month": month,
        "no_data": is_no_data(text),
        "table_kind": parsed["kind"],
        "delimiter": parsed["delimiter"],
        "headers": parsed["headers"],
        "has_tmin": parsed["has_tmin"],
        "has_tmax": parsed["has_tmax"],
        "rows": parsed["rows"],
        "raw": text,
    }

    if show_raw:
        log(f"URL: {final}")
        log(
            f"HTTP {status} | {ctype} | encoding={encoding} | "
            f"chars={len(text):,}"
        )
        log(
            f"no_data={info['no_data']} | table={info['table_kind']} | "
            f"Tmin={info['has_tmin']} | Tmax={info['has_tmax']}"
        )

        if info["headers"]:
            log(f"HEADER: {info['headers']}")

        if info["rows"]:
            log("Geparste Beispielzeilen:")
            for row in info["rows"][:8]:
                log(f"  {row}")

        log("Erste Rohzeilen:")
        for line in text.splitlines()[:30]:
            log(f"  {line}")

    return info


def self_test() -> int:
    assert (
        data_url("192", 2026, 7)
        == DATA_BASE + "192_202607.txt"
    )
    assert (
        data_url("048", 1961, 1)
        == DATA_BASE + "048_196101.txt"
    )

    sample = """Datum  tmin  tmax  tpov
1.7.2026  15.2  30.1  22.4
2.7.2026  16.0  31.5  23.1
"""
    parsed = parse_table(sample)
    assert parsed["has_tmin"] is True
    assert parsed["has_tmax"] is True

    sample_html = """
    <select name="postaja">
      <option value="0">Izberi postajo</option>
      <option value="192">Ljubljana Bežigrad (1961- )</option>
      <option value="097">Bilje (1962- )</option>
      <option value="048">Kredarica (1961- )</option>
      <option value="249">Novo mesto (1961- )</option>
      <option value="268">Celje Medlog (1961- )</option>
      <option value="355">Murska Sobota (1961- )</option>
      <option value="464">Portorož - letališče (1974- )</option>
      <option value="311">Letališče Edvarda Rusjana Maribor (1977- )</option>
      <option value="257">Črnomelj - Dobliče (1961- )</option>
      <option value="174">Kočevje (1961- )</option>
    </select>
    """
    stations = parse_numeric_station_options(sample_html)
    assert len(stations) == 10
    assert stations[0]["id"] == "192"
    assert stations[1]["id"] == "097"

    log("ARSO Slovenia direct month-file probe self-test OK")
    return 0


def main() -> int:
    log("=== ARSO SLOWENIEN · ECHTE MONATS-TAGESDATEIEN ===")
    log("Schritt 5 – noch kein Produktionscache.")
    log()
    log("Vom ARSO-JavaScript bestätigtes Muster:")
    log("  <Stations-ID>_<YYYY><MM>.txt")
    log("Beispiel:")
    log(f"  {data_url('192', 2026, 7)}")
    log()

    # ------------------------------------------------------------------
    # 1. Station inventory
    # ------------------------------------------------------------------
    log("=" * 96)
    log("1. NUMERISCHES ARSO-STATIONSINVENTAR")
    log("=" * 96)

    page, final, status, ctype, encoding = request_text(MONTH_URL)
    stations = parse_numeric_station_options(page)

    log(f"Formular: {final} | HTTP {status} | {ctype} | {encoding}")
    log(f"Numerische Stationsoptionen erkannt: {len(stations):,}")

    for station in stations:
        log(f"  {station['id']} | {station['label']}")

    # ------------------------------------------------------------------
    # 2. Exact known file tests
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("2. EXAKTE ID_YYYYMM.TXT-DATEIEN")
    log("=" * 96)

    direct_results = []

    for station_id, name, year, month in TESTS:
        log()
        log("-" * 96)
        log(f"{station_id} | {name} | {year:04d}-{month:02d}")

        info = inspect_file(
            station_id,
            name,
            year,
            month,
            show_raw=True,
        )
        direct_results.append(info)

        if not info.get("http_ok"):
            if info.get("status") == 404:
                log(f"404: {info['url']}")
            else:
                log(f"FEHLER: {info.get('error')}")

    # ------------------------------------------------------------------
    # 3. Historical availability
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("3. HISTORISCHE VERFÜGBARKEIT – KLEINE STICHPROBE")
    log("=" * 96)

    history_results = []

    for station_id, name, *dates in HISTORY_TESTS:
        log()
        log(f"{station_id} | {name}")

        for year, month in dates:
            info = inspect_file(
                station_id,
                name,
                year,
                month,
                show_raw=False,
            )
            history_results.append(info)

            if info.get("http_ok"):
                log(
                    f"  {year:04d}-{month:02d}: HTTP200 | "
                    f"no_data={info.get('no_data')} | "
                    f"Tmin={info.get('has_tmin')} | "
                    f"Tmax={info.get('has_tmax')} | "
                    f"chars={info.get('chars', 0):,}"
                )
            elif info.get("status") == 404:
                log(f"  {year:04d}-{month:02d}: 404")
            else:
                log(
                    f"  {year:04d}-{month:02d}: FEHLER "
                    f"{info.get('error')}"
                )

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("4. FAZIT")
    log("=" * 96)

    existing_direct = [x for x in direct_results if x.get("exists")]
    temp_direct = [
        x
        for x in direct_results
        if x.get("has_tmin") and x.get("has_tmax")
    ]

    history_existing = [x for x in history_results if x.get("exists")]
    history_temp = [
        x
        for x in history_results
        if x.get("has_tmin") and x.get("has_tmax")
    ]

    log(
        f"Aktuelle/gezielte Testdateien mit Daten: "
        f"{len(existing_direct)}/{len(direct_results)}"
    )
    log(
        f"Davon mit erkanntem Tmin+Tmax: "
        f"{len(temp_direct)}/{len(direct_results)}"
    )
    log(
        f"Historische Stichproben mit Daten: "
        f"{len(history_existing)}/{len(history_results)}"
    )
    log(
        f"Davon mit erkanntem Tmin+Tmax: "
        f"{len(history_temp)}/{len(history_results)}"
    )

    if temp_direct:
        log()
        log("BESTÄTIGTE TMIN+TMAX-DATEIEN:")
        for info in temp_direct:
            log(f"  {info['url']}")

    if temp_direct and history_temp:
        log()
        log(
            "ERGEBNIS: Der echte maschinenlesbare ARSO-Tagesdatensatz ist "
            "bestätigt und funktioniert auch historisch. Im nächsten Schritt "
            "kann daraus der Slowenien-Baseline-Cache bis 2025 gebaut werden."
        )
    elif temp_direct:
        log()
        log(
            "ERGEBNIS: Aktuelle Tmin/Tmax-Rohdaten sind bestätigt. "
            "Die historische Verfügbarkeit muss anhand der obigen "
            "Stichproben eingegrenzt werden."
        )
    else:
        log()
        log(
            "ERGEBNIS: Das Dateinamenschema ist jetzt korrekt, aber der "
            "Inhalt/Parser muss anhand der ausgegebenen Rohzeilen angepasst "
            "werden."
        )

    log()
    log("Bitte anschließend den GitHub-Log ab")
    log("2. EXAKTE ID_YYYYMM.TXT-DATEIEN")
    log("bis einschließlich")
    log("4. FAZIT")
    log("schicken.")

    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
