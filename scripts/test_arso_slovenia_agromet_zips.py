#!/usr/bin/env python3
"""Probe official ARSO agrometeorological station ZIP archives.

Step 3 only: no production cache.

The official ARSO agromet archive page lists per-station ZIP files, mostly
covering 2017-current. The surrounding ARSO documentation says the daily
agrometeorological table contains tmin, tmax, tpov, precipitation and ETo.

This probe:
  * enumerates every station ZIP from the official ARSO page;
  * prints station names, ZIP URLs and advertised periods;
  * downloads a representative sample;
  * lists ZIP members;
  * detects text encoding, delimiter, headers and date format;
  * checks explicitly whether Tmin/Tmax columns exist;
  * reports first/last daily rows and first/last 2026 rows;
  * performs no production-cache writes.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from typing import Any

INDEX_URL = (
    "https://meteo.arso.gov.si/uploads/probase/www/agromet/"
    "product/form/sl/etp_17xx.html"
)
BASE = "https://meteo.arso.gov.si"

UA = "climate-dashboard-slovenia-arso-agromet-zip-probe/1.0 (+GitHub Actions)"
TIMEOUT = 90
TRIES = 4

PREFERRED_SAMPLES = (
    "LJUBLJANA BEŽIGRAD",
    "BILJE",
    "KREDARICA",
    "PORTOROŽ - LETALIŠČE",
    "MURSKA SOBOTA",
    "NOVO MESTO",
    "CELJE MEDLOG",
    "MARIBOR - LETALIŠČE",
    "RATEČE",
    "ČRNOMELJ - DOBLIČE",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_bytes(url: str, attempts: int = TRIES) -> tuple[bytes, str, str]:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
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
                return (
                    response.read(),
                    response.geturl(),
                    response.headers.get("Content-Type", ""),
                )
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def decode_text(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"

    for enc in ("utf-8", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def strip_tags(value: str) -> str:
    import html
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def parse_index(html_text: str, base_url: str) -> list[dict[str, str]]:
    """Parse station rows with ZIP href and advertised period."""
    out = []

    # Work row-by-row; ARSO page uses an ordinary HTML table.
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    for row in rows:
        cells = re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.I | re.S,
        )
        if len(cells) < 2:
            continue

        row_text = [strip_tags(c) for c in cells]
        link_m = re.search(
            r"""<a\b[^>]*href\s*=\s*['"]([^'"]+\.zip)['"][^>]*>(.*?)</a>""",
            row,
            flags=re.I | re.S,
        )
        if not link_m:
            continue

        href = urllib.parse.urljoin(base_url, link_m.group(1))
        zip_label = strip_tags(link_m.group(2))

        # Page columns are station | data | period, but tolerate variants.
        station = row_text[0].strip()
        period = ""
        for cell in row_text[1:]:
            if re.search(r"\b(?:19|20)\d{2}\b", cell):
                period = cell
                break

        out.append(
            {
                "station": station,
                "zip_label": zip_label,
                "zip_url": href,
                "period": period,
            }
        )

    # Fallback if crawler HTML differs.
    if not out:
        for m in re.finditer(
            r"""href\s*=\s*['"]([^'"]*/zip_etp/[^'"]+\.zip)['"]""",
            html_text,
            flags=re.I,
        ):
            href = urllib.parse.urljoin(base_url, m.group(1))
            out.append(
                {
                    "station": "?",
                    "zip_label": href.rsplit("/", 1)[-1],
                    "zip_url": href,
                    "period": "",
                }
            )

    unique = {}
    for item in out:
        unique[item["zip_url"]] = item
    return list(unique.values())


def choose_samples(items: list[dict[str, str]], limit: int = 10) -> list[dict[str, str]]:
    selected = []
    used = set()

    for wanted in PREFERRED_SAMPLES:
        for item in items:
            name = item["station"].upper()
            if item["zip_url"] in used:
                continue
            if wanted in name:
                selected.append(item)
                used.add(item["zip_url"])
                break
        if len(selected) >= limit:
            return selected

    for item in items:
        if item["zip_url"] in used:
            continue
        selected.append(item)
        used.add(item["zip_url"])
        if len(selected) >= limit:
            break

    return selected


def normalize_header(value: str) -> str:
    value = value.strip().lower()
    value = (
        value.replace("č", "c")
        .replace("š", "s")
        .replace("ž", "z")
    )
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def detect_delimiter(lines: list[str]) -> str | None:
    sample = "\n".join(lines[:50])
    candidates = [";", "\t", ",", "|"]

    counts = {d: sample.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return None
    return best


def find_header_and_rows(text: str) -> dict[str, Any]:
    lines = [line.rstrip("\r") for line in text.splitlines()]
    nonempty = [line for line in lines if line.strip()]

    delimiter = detect_delimiter(nonempty)
    header_index = None
    header = []

    header_tokens = (
        "datum",
        "date",
        "tmin",
        "tmax",
        "tpov",
        "etp",
        "eto",
        "padav",
        "rr",
    )

    for i, line in enumerate(lines[:100]):
        low = normalize_header(line)
        if sum(token in low for token in header_tokens) >= 2:
            header_index = i
            if delimiter:
                header = [
                    normalize_header(x)
                    for x in next(csv.reader([line], delimiter=delimiter))
                ]
            else:
                header = [
                    normalize_header(x)
                    for x in re.split(r"\s{2,}|\t+", line.strip())
                ]
            break

    date_re = re.compile(
        r"\b("
        r"\d{1,2}\.\d{1,2}\.\d{4}"
        r"|\d{4}-\d{1,2}-\d{1,2}"
        r"|\d{1,2}/\d{1,2}/\d{4}"
        r")\b"
    )

    dated_lines = []
    for line in lines:
        m = date_re.search(line)
        if m:
            dated_lines.append((m.group(1), line))

    return {
        "line_count": len(lines),
        "delimiter": delimiter,
        "header_index": header_index,
        "header": header,
        "dated_lines": dated_lines,
        "first_lines": nonempty[:15],
    }


def date_key(text: str) -> tuple[int, int, int] | None:
    text = text.strip()

    for pattern, order in (
        (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", "dmy"),
        (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", "ymd"),
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", "dmy"),
    ):
        m = re.match(pattern, text)
        if not m:
            continue
        a, b, c = map(int, m.groups())
        if order == "dmy":
            return c, b, a
        return a, b, c

    return None


def inspect_member(raw: bytes, name: str) -> dict[str, Any]:
    text, encoding = decode_text(raw)
    parsed = find_header_and_rows(text)

    dates = []
    for dtext, line in parsed["dated_lines"]:
        key = date_key(dtext)
        if key:
            dates.append((key, dtext, line))

    dates.sort(key=lambda x: x[0])

    header_norm = parsed["header"]
    all_header_text = " ".join(header_norm)

    has_tmin = any(
        token in all_header_text
        for token in ("tmin", "temp_min", "minimalna_temperatura")
    )
    has_tmax = any(
        token in all_header_text
        for token in ("tmax", "temp_max", "maksimalna_temperatura")
    )

    rows_2026 = [x for x in dates if x[0][0] == 2026]

    return {
        "member": name,
        "encoding": encoding,
        "line_count": parsed["line_count"],
        "delimiter": parsed["delimiter"],
        "header_index": parsed["header_index"],
        "header": header_norm,
        "has_tmin": has_tmin,
        "has_tmax": has_tmax,
        "date_rows": len(dates),
        "first_date": dates[0][1] if dates else None,
        "last_date": dates[-1][1] if dates else None,
        "first_row": dates[0][2] if dates else None,
        "last_row": dates[-1][2] if dates else None,
        "rows_2026": len(rows_2026),
        "first_2026": rows_2026[0][2] if rows_2026 else None,
        "last_2026": rows_2026[-1][2] if rows_2026 else None,
        "first_lines": parsed["first_lines"],
    }


def inspect_zip(item: dict[str, str]) -> dict[str, Any]:
    raw, final, ctype = request_bytes(item["zip_url"])

    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RuntimeError(
            f"Kein gültiges ZIP: {final} | {ctype} | {len(raw)} bytes"
        )

    result = {
        "station": item["station"],
        "period": item["period"],
        "url": final,
        "size": len(raw),
        "content_type": ctype,
        "members": [],
    }

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        for name in names:
            member_raw = zf.read(name)

            # Inspect likely text/tabular members. Binary members still get listed.
            lower = name.lower()
            if lower.endswith(
                (".txt", ".csv", ".dat", ".tsv", ".asc")
            ) or b"\x00" not in member_raw[:1000]:
                try:
                    result["members"].append(inspect_member(member_raw, name))
                except Exception as exc:
                    result["members"].append(
                        {
                            "member": name,
                            "error": str(exc),
                            "size": len(member_raw),
                        }
                    )
            else:
                result["members"].append(
                    {
                        "member": name,
                        "binary": True,
                        "size": len(member_raw),
                    }
                )

    return result


def main() -> int:
    log("=== ARSO SLOWENIEN · AGROMET ZIP PROBE ===")
    log("Schritt 3 – noch kein Produktionscache.")
    log()

    raw, final, ctype = request_bytes(INDEX_URL)
    index_text, encoding = decode_text(raw)
    items = parse_index(index_text, final)

    log("=" * 88)
    log("1. ARSO AGROMET ZIP-INVENTAR")
    log("=" * 88)
    log(f"Index: {final}")
    log(f"Content-Type: {ctype} | Encoding: {encoding}")
    log(f"Stations-ZIPs gefunden: {len(items):,}")

    period_counts = Counter(item["period"] for item in items)
    log(f"Perioden-Verteilung: {dict(period_counts.most_common())}")

    for item in items:
        log(
            f"{item['station']} | {item['period']} | "
            f"{item['zip_label']} | {item['zip_url']}"
        )

    samples = choose_samples(items)

    log()
    log("=" * 88)
    log("2. ZIP-INHALTSPROBEN")
    log("=" * 88)
    log(f"Ausgewählte Stichproben: {len(samples)}")

    successes = []
    failures = {}

    for item in samples:
        log()
        log("-" * 88)
        log(f"STATION: {item['station']} | beworben: {item['period']}")
        try:
            info = inspect_zip(item)
            successes.append(info)
        except Exception as exc:
            failures[item["station"]] = str(exc)
            log(f"FEHLER: {exc}")
            continue

        log(
            f"ZIP: {info['size']:,} bytes | "
            f"{info['content_type']} | {info['url']}"
        )
        log(f"Dateien im ZIP: {len(info['members'])}")

        for member in info["members"]:
            log(f"  MEMBER: {member['member']}")
            if member.get("binary"):
                log(f"    binär | {member['size']} bytes")
                continue
            if "error" in member:
                log(f"    FEHLER: {member['error']}")
                continue

            log(
                f"    encoding={member['encoding']} | "
                f"delimiter={member['delimiter']!r} | "
                f"lines={member['line_count']}"
            )
            log(f"    HEADER: {member['header']}")
            log(
                f"    Tmin erkannt={member['has_tmin']} | "
                f"Tmax erkannt={member['has_tmax']}"
            )
            log(
                f"    Datumszeilen={member['date_rows']} | "
                f"{member['first_date']} .. {member['last_date']}"
            )
            log(f"    Erste Datenzeile: {member['first_row']}")
            log(f"    Letzte Datenzeile: {member['last_row']}")
            log(
                f"    2026-Zeilen={member['rows_2026']} | "
                f"erste={member['first_2026']} | "
                f"letzte={member['last_2026']}"
            )
            log("    Erste Textzeilen:")
            for line in member["first_lines"][:12]:
                log(f"      {line}")

    log()
    log("=" * 88)
    log("3. FAZIT")
    log("=" * 88)

    tabular = []
    with_both = []
    reaches_2026 = []

    for info in successes:
        for member in info["members"]:
            if member.get("date_rows", 0):
                tabular.append((info, member))
                if member.get("has_tmin") and member.get("has_tmax"):
                    with_both.append((info, member))
                if member.get("rows_2026", 0):
                    reaches_2026.append((info, member))

    log(f"ZIP-Stichproben erfolgreich: {len(successes)}/{len(samples)}")
    log(f"Fehler: {len(failures)}")
    log(f"Tabellarische Mitglieder mit Datumszeilen: {len(tabular)}")
    log(f"Mit erkannten Tmin+Tmax-Spalten: {len(with_both)}")
    log(f"Mit echten 2026-Zeilen: {len(reaches_2026)}")

    if failures:
        for station, error in failures.items():
            log(f"  FEHLER {station}: {error}")

    if with_both:
        log(
            "ERGEBNIS: ARSO-Agromet-ZIPs sind ein Kandidat für "
            "den nationalen 2017–2026-Temperaturbestand."
        )
    else:
        log(
            "ERGEBNIS: In der Probe wurden noch keine eindeutig "
            "tabellarischen Tmin+Tmax-Rohdaten bestätigt."
        )

    log()
    log("Bitte den vollständigen GitHub-Log schicken, besonders:")
    log("1. ARSO AGROMET ZIP-INVENTAR")
    log("2. ZIP-INHALTSPROBEN")
    log("3. FAZIT")
    return 0


def self_test() -> None:
    sample_html = """
    <table>
      <tr>
        <td>LJUBLJANA BEŽIGRAD</td>
        <td><a href="zip_etp/Novo/Ljubljana_Bezigrad.zip">
          Ljubljana_Bezigrad.zip
        </a></td>
        <td>2021-2026</td>
      </tr>
    </table>
    """
    items = parse_index(sample_html, INDEX_URL)
    assert len(items) == 1
    assert items[0]["station"] == "LJUBLJANA BEŽIGRAD"
    assert items[0]["period"] == "2021-2026"
    assert items[0]["zip_url"].endswith(
        "/zip_etp/Novo/Ljubljana_Bezigrad.zip"
    )

    sample_text = (
        "datum;tmin;tmax;tpov;rr;etp\n"
        "01.01.2026;-2.1;4.3;1.0;0.0;0.2\n"
        "02.01.2026;-1.8;5.2;1.7;0.0;0.3\n"
    )
    info = inspect_member(sample_text.encode("utf-8"), "sample.csv")
    assert info["has_tmin"] is True
    assert info["has_tmax"] is True
    assert info["rows_2026"] == 2
    assert info["first_date"] == "01.01.2026"

    print("ARSO Slovenia agromet ZIP probe self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
