#!/usr/bin/env python3
"""ARSO Slowenien: gezielter Probe-Lauf für die Monats-Tagesdatentabelle.

Schritt 4:
- noch KEIN Produktionscache
- keine OCR
- keine Bildwerte
- nur offizielle, maschinenlesbare ARSO-Ressourcen

Ziel:
Die ARSO-Seite
  https://meteo.arso.gov.si/met/sl/agromet/data/month/
bietet laut ARSO tägliche Werte für:
  tmin, tmax, tpov, tmin5, rr, etp
und Stations-/Jahresauswahl ab 1961.

Der bisherige Probe-Lauf hat zwar das Formular gefunden, aber noch nicht
ermittelt, welche konkrete Datei das iframe nach der Auswahl lädt.

Dieses Skript:
1. lädt die echte Monatsseite,
2. liest Stationen/Jahre/Monate aus,
3. druckt den JavaScript-Kontext um "filen", "iframe", ".tx" und "/data/",
4. testet kontrollierte GET-Auswahlen für einige Stationen/Monate,
5. extrahiert iframe/src/href-Ressourcen,
6. testet nur eine kleine, nachvollziehbare Menge direkter Datendatei-Kandidaten,
7. erkennt tabellarische Tmin/Tmax-Daten und zeigt Beispielzeilen.

Es wird absichtlich NICHT breit geraten oder gebruteforct.
"""

from __future__ import annotations

import csv
import html
import io
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
DATA_BASE = (
    f"{BASE}/uploads/probase/www/agromet/product/form/sl/data/"
)

UA = "climate-dashboard-slovenia-arso-month-table-probe/1.0 (+GitHub Actions)"
TIMEOUT = 60
TRIES = 4

TEST_SELECTIONS = (
    ("LJUBLJANA_-_BEZIGRAD", "2026", "07"),
    ("BILJE", "2026", "07"),
    ("KREDARICA", "2026", "01"),
    ("NOVO_MESTO", "2025", "07"),
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
                "Accept": "text/html,text/plain,text/csv,*/*",
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
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def decode_bytes(raw: bytes, content_type: str = "") -> tuple[str, str]:
    candidates = []

    m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, flags=re.I)
    if m:
        candidates.append(m.group(1))

    candidates.extend(("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"))

    seen = set()
    for encoding in candidates:
        if encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass

    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def request_text(url: str, *, attempts: int = TRIES) -> tuple[str, str, int, str, str]:
    raw, final, status, ctype = request_bytes(url, attempts=attempts)
    text, encoding = decode_bytes(raw, ctype)
    return text, final, status, ctype, encoding


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value.strip()))


def extract_select_options(text: str, select_name: str) -> list[tuple[str, str]]:
    pattern = (
        r"<select\b[^>]*\bname\s*=\s*['\"]"
        + re.escape(select_name)
        + r"['\"][^>]*>(.*?)</select>"
    )
    match = re.search(pattern, text, flags=re.I | re.S)
    if not match:
        return []

    out = []
    for option in re.finditer(
        r"<option\b([^>]*)>(.*?)</option>",
        match.group(1),
        flags=re.I | re.S,
    ):
        attrs = option.group(1)
        label = strip_tags(option.group(2))
        value_match = re.search(
            r"\bvalue\s*=\s*['\"]([^'\"]*)['\"]",
            attrs,
            flags=re.I,
        )
        if value_match:
            value = html.unescape(value_match.group(1)).strip()
        else:
            value = label.strip()
        out.append((value, label))

    return out


def extract_resources(text: str, base: str) -> list[str]:
    found: list[str] = []

    patterns = (
        r"""<(?:iframe|frame|script|img)\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
        r"""<a\b[^>]*\bhref\s*=\s*['"]([^'"]+)['"]""",
        r"""['"]([^'"]+\.(?:tx|txt|csv|tsv|dat|json|xml|html)(?:\?[^'"]*)?)['"]""",
    )

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            value = match.group(1).strip()
            if not value:
                continue
            url = absolute(base, value)
            if url not in found:
                found.append(url)

    return found


def extract_iframes(text: str, base: str) -> list[str]:
    out = []
    for match in re.finditer(
        r"""<iframe\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
        text,
        flags=re.I | re.S,
    ):
        url = absolute(base, match.group(1))
        if url not in out:
            out.append(url)
    return out


def interesting_source_context(text: str) -> list[tuple[int, str]]:
    """Return compact source context around the JS that constructs the data filename."""
    lines = text.splitlines()
    hit_indices: set[int] = set()

    tokens = (
        "filen",
        "iframe",
        ".tx",
        "/data/",
        "postaja",
        "mesec",
        "leto",
        "src=",
        ".src",
    )

    for idx, line in enumerate(lines):
        low = line.lower()
        if any(token in low for token in tokens):
            # "postaja/leto/mesec" occur often; focus them if JS-ish.
            if any(
                strong in low
                for strong in ("filen", "iframe", ".tx", "/data/", ".src", "function")
            ):
                start = max(0, idx - 6)
                end = min(len(lines), idx + 7)
                hit_indices.update(range(start, end))

    return [
        (idx + 1, " ".join(html.unescape(lines[idx]).split())[:1200])
        for idx in sorted(hit_indices)
        if lines[idx].strip()
    ]


def discover_filename_assignments(text: str) -> list[str]:
    """Print raw JS assignments/uses involving filen; do not pretend to execute JS."""
    out = []
    for match in re.finditer(
        r"[^;\n]{0,250}\bfilen\b[^;\n]{0,500};?",
        text,
        flags=re.I,
    ):
        value = " ".join(html.unescape(match.group(0)).split())
        if value and value not in out:
            out.append(value[:1200])
    return out


def normalize_header(value: str) -> str:
    value = html.unescape(value).strip().lower()
    for old, new in (
        ("č", "c"),
        ("š", "s"),
        ("ž", "z"),
        ("°", ""),
    ):
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def detect_delimiter(lines: list[str]) -> str | None:
    sample = "\n".join(lines[:50])
    candidates = ("\t", ";", ",", "|")
    counts = {d: sample.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


def parse_possible_table(text: str) -> dict[str, Any]:
    """Inspect either delimited text or an HTML table for Tmin/Tmax columns."""
    result: dict[str, Any] = {
        "kind": None,
        "headers": [],
        "rows": [],
        "has_tmin": False,
        "has_tmax": False,
    }

    # 1) HTML tables
    table_matches = list(re.finditer(r"<table\b.*?</table>", text, flags=re.I | re.S))
    for table_match in table_matches:
        table = table_match.group(0)
        rows_html = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, flags=re.I | re.S)
        parsed_rows = []
        for row_html in rows_html:
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

        if not parsed_rows:
            continue

        for header_idx in range(min(5, len(parsed_rows))):
            headers = [normalize_header(x) for x in parsed_rows[header_idx]]
            joined = " ".join(headers)
            has_tmin = any(x in joined for x in ("tmin", "min_temp", "minimalna"))
            has_tmax = any(x in joined for x in ("tmax", "max_temp", "maksimalna"))
            if has_tmin or has_tmax:
                result.update(
                    {
                        "kind": "html",
                        "headers": headers,
                        "rows": parsed_rows[header_idx + 1 :],
                        "has_tmin": has_tmin,
                        "has_tmax": has_tmax,
                    }
                )
                return result

    # 2) Delimited text
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return result

    delimiter = detect_delimiter(lines)

    for idx, line in enumerate(lines[:80]):
        if delimiter:
            try:
                raw_headers = next(csv.reader([line], delimiter=delimiter))
            except Exception:
                continue
        else:
            raw_headers = re.split(r"\s{2,}", line.strip())

        headers = [normalize_header(x) for x in raw_headers]
        joined = " ".join(headers)
        has_tmin = any(x in joined for x in ("tmin", "min_temp", "minimalna"))
        has_tmax = any(x in joined for x in ("tmax", "max_temp", "maksimalna"))

        if not (has_tmin or has_tmax):
            continue

        parsed_rows = []
        for data_line in lines[idx + 1 : idx + 45]:
            if delimiter:
                try:
                    parsed_rows.append(next(csv.reader([data_line], delimiter=delimiter)))
                except Exception:
                    parsed_rows.append([data_line])
            else:
                parsed_rows.append(re.split(r"\s{2,}", data_line.strip()))

        result.update(
            {
                "kind": "delimited" if delimiter else "text",
                "delimiter": delimiter,
                "headers": headers,
                "rows": parsed_rows,
                "has_tmin": has_tmin,
                "has_tmax": has_tmax,
            }
        )
        return result

    return result


def looks_like_real_data(text: str) -> bool:
    low = strip_tags(text).lower()
    if not low:
        return False
    if low.strip() in ("ni podatkov!", "ni podatkov", "no data!", "no data"):
        return False

    parsed = parse_possible_table(text)
    return bool(parsed["has_tmin"] or parsed["has_tmax"])


def direct_candidates(station: str, year: str, month: str) -> list[str]:
    """Small explicit candidate set only; this is not brute force."""
    station_id = {
        "LJUBLJANA_-_BEZIGRAD": "192",
        "BILJE": "97",
        "KREDARICA": "48",
        "NOVO_MESTO": "249",
    }.get(station)

    names = [
        f"{station}_{year}_{month}.tx",
        f"{station}_{month}_{year}.tx",
        f"{station}_{month}{year}.tx",
        f"{station}_{year}{month}.tx",
    ]

    if station_id:
        names.extend(
            [
                f"{station_id}_{year}_{month}.tx",
                f"{station_id}_{month}_{year}.tx",
                f"{station_id}_{month}{year}.tx",
                f"{station_id}_{year}{month}.tx",
            ]
        )

    out = []
    for name in names:
        url = urllib.parse.urljoin(DATA_BASE, urllib.parse.quote(name, safe="._-()"))
        if url not in out:
            out.append(url)
    return out


def probe_resource(url: str) -> dict[str, Any]:
    try:
        text, final, status, ctype, encoding = request_text(url, attempts=2)
    except Exception as exc:
        return {"url": url, "ok": False, "error": str(exc)}

    parsed = parse_possible_table(text)
    preview = "\n".join(text.splitlines()[:12])

    return {
        "url": final,
        "ok": status == 200,
        "status": status,
        "content_type": ctype,
        "encoding": encoding,
        "chars": len(text),
        "preview": preview[:4000],
        "table_kind": parsed.get("kind"),
        "headers": parsed.get("headers", []),
        "has_tmin": parsed.get("has_tmin", False),
        "has_tmax": parsed.get("has_tmax", False),
        "sample_rows": parsed.get("rows", [])[:8],
        "real_data": looks_like_real_data(text),
    }


def selection_url(station: str, year: str, month: str) -> str:
    query = urllib.parse.urlencode(
        {
            "leto": year,
            "mesec": month,
            "postaja": station,
        }
    )
    return MONTH_URL + "?" + query


def self_test() -> int:
    sample_html = """
    <select name="leto"><option value="2026">2026</option></select>
    <select name="mesec"><option value="07">julij</option></select>
    <select name="postaja">
      <option value="LJUBLJANA_-_BEZIGRAD">LJUBLJANA - BEŽIGRAD (1961- )</option>
    </select>
    <script>
      function prikaz() {
        var filen = "LJUBLJANA_-_BEZIGRAD_2026_07.tx";
        document.getElementById("podatki").src =
          "/uploads/probase/www/agromet/product/form/sl/data/"+filen;
      }
    </script>
    <iframe id="podatki"
      src="/uploads/probase/www/agromet/product/form/sl/data/blank.tx"></iframe>
    """

    assert extract_select_options(sample_html, "leto") == [("2026", "2026")]
    assert extract_select_options(sample_html, "mesec") == [("07", "julij")]
    stations = extract_select_options(sample_html, "postaja")
    assert stations and stations[0][0] == "LJUBLJANA_-_BEZIGRAD"
    assert any("blank.tx" in x for x in extract_iframes(sample_html, MONTH_URL))
    assert discover_filename_assignments(sample_html)

    sample_table = """datum\ttmin\ttmax\ttpov
2026-07-01\t15.2\t30.1\t22.4
2026-07-02\t16.0\t31.5\t23.1
"""
    parsed = parse_possible_table(sample_table)
    assert parsed["has_tmin"] is True
    assert parsed["has_tmax"] is True

    log("ARSO Slovenia month-table probe self-test OK")
    return 0


def main() -> int:
    log("=== ARSO SLOWENIEN · AGROMET MONATSTABELLE / ENDPOINT PROBE ===")
    log("Schritt 4 – noch kein Produktionscache.")
    log("Nur offizielle maschinenlesbare ARSO-Daten; kein OCR.")
    log()

    # ------------------------------------------------------------------
    # 1. Base page
    # ------------------------------------------------------------------
    log("=" * 96)
    log("1. FORMULAR / INVENTAR")
    log("=" * 96)

    page, final, status, ctype, encoding = request_text(MONTH_URL)
    log(f"URL: {final}")
    log(f"HTTP: {status} | {ctype} | Encoding: {encoding}")
    log(f"HTML chars: {len(page):,}")

    years = extract_select_options(page, "leto")
    months = extract_select_options(page, "mesec")
    stations = extract_select_options(page, "postaja")

    log(f"Jahresoptionen: {len(years):,}")
    log(f"Monatsoptionen: {len(months):,}")
    log(f"Stationsoptionen: {len(stations):,}")

    valid_years = [v for v, _ in years if re.fullmatch(r"\d{4}", v)]
    log(
        "Jahresbereich: "
        + (
            f"{min(valid_years)} .. {max(valid_years)}"
            if valid_years
            else "nicht erkannt"
        )
    )

    wanted = {
        "LJUBLJANA_-_BEZIGRAD",
        "BILJE",
        "KREDARICA",
        "NOVO_MESTO",
        "CELJE_-_MEDLOG",
        "MARIBOR_-_LETALISCE",
        "MURSKA_SOBOTA_-_RAKICAN",
        "PORTOROZ_-_LETALISCE",
    }
    log("Relevante Stationsoptionen:")
    for value, label in stations:
        if value in wanted or any(
            token in label.upper()
            for token in (
                "LJUBLJANA",
                "BILJE",
                "KREDARICA",
                "NOVO MESTO",
                "CELJE",
                "MARIBOR",
                "MURSKA SOBOTA",
                "PORTORO",
            )
        ):
            log(f"  {value!r} -> {label}")

    # ------------------------------------------------------------------
    # 2. JS source context
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("2. JAVASCRIPT-KONTEXT ZUR DATENDATEI")
    log("=" * 96)

    assignments = discover_filename_assignments(page)
    log(f"'filen'-Treffer: {len(assignments)}")
    for item in assignments:
        log(f"  {item}")

    context = interesting_source_context(page)
    log(f"Kontextzeilen: {len(context)}")
    for lineno, line in context:
        log(f"L{lineno}: {line}")

    base_iframes = extract_iframes(page, final)
    log(f"iframe-src auf Basisseite: {len(base_iframes)}")
    for url in base_iframes:
        log(f"  {url}")

    # ------------------------------------------------------------------
    # 3. Controlled selection requests
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("3. KONTROLLIERTE AUSWAHL-REQUESTS")
    log("=" * 96)

    discovered_resources: list[str] = []

    for station, year, month in TEST_SELECTIONS:
        url = selection_url(station, year, month)
        log()
        log("-" * 96)
        log(f"AUSWAHL: station={station} | {year}-{month}")
        log(f"GET: {url}")

        try:
            text, selected_final, selected_status, selected_ctype, selected_enc = (
                request_text(url)
            )
        except Exception as exc:
            log(f"FEHLER: {exc}")
            continue

        log(
            f"HTTP {selected_status} | {selected_ctype} | "
            f"Encoding {selected_enc} | chars={len(text):,}"
        )

        iframes = extract_iframes(text, selected_final)
        resources = [
            u
            for u in extract_resources(text, selected_final)
            if (
                "/agromet/product/form/sl/data/" in u
                or u.lower().endswith((".tx", ".txt", ".csv", ".tsv", ".dat"))
            )
        ]

        log(f"iframe-src: {len(iframes)}")
        for item in iframes:
            log(f"  IFRAME {item}")

        log(f"interessante Data-Ressourcen: {len(resources)}")
        for item in resources:
            log(f"  DATA {item}")

        for item in iframes + resources:
            if item not in discovered_resources:
                discovered_resources.append(item)

    # ------------------------------------------------------------------
    # 4. Probe exact discovered resources
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("4. ENTDECKTE RESSOURCEN DIREKT PRÜFEN")
    log("=" * 96)

    real_hits: list[dict[str, Any]] = []
    tested = set()

    for url in discovered_resources:
        if url in tested:
            continue
        tested.add(url)

        log()
        log(f"RESOURCE: {url}")
        info = probe_resource(url)

        if not info.get("ok"):
            log(f"  FEHLER: {info.get('error')}")
            continue

        log(
            f"  HTTP {info['status']} | {info['content_type']} | "
            f"encoding={info['encoding']} | chars={info['chars']:,}"
        )
        log(
            f"  Tabelle={info['table_kind']} | "
            f"Tmin={info['has_tmin']} | Tmax={info['has_tmax']} | "
            f"echte Daten={info['real_data']}"
        )
        if info["headers"]:
            log(f"  HEADER: {info['headers']}")
        for row in info["sample_rows"][:5]:
            log(f"  ROW: {row}")
        if not info["sample_rows"]:
            log("  PREVIEW:")
            for line in info["preview"].splitlines()[:8]:
                log(f"    {line}")

        if info["real_data"]:
            real_hits.append(info)

    # ------------------------------------------------------------------
    # 5. Small direct candidate set
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("5. KLEINE DIREKTE DATEINAMEN-PROBE")
    log("=" * 96)
    log(
        "Nur 8 nachvollziehbare Kandidaten pro Auswahl; "
        "kein Brute-Force und keine große URL-Matrix."
    )

    for station, year, month in TEST_SELECTIONS:
        log()
        log(f"--- {station} {year}-{month} ---")
        for url in direct_candidates(station, year, month):
            if url in tested:
                continue
            tested.add(url)

            info = probe_resource(url)
            if not info.get("ok"):
                err = str(info.get("error", ""))
                # Keep the log compact.
                if "HTTP Error 404" not in err:
                    log(f"  MISS {url} | {err}")
                continue

            # HTTP 200 is important even if it says "Ni podatkov!".
            log(
                f"  HTTP200 {info['url']} | chars={info['chars']:,} | "
                f"Tmin={info['has_tmin']} Tmax={info['has_tmax']} "
                f"real={info['real_data']}"
            )
            for line in info["preview"].splitlines()[:6]:
                log(f"    {line}")

            if info["real_data"]:
                real_hits.append(info)

    # ------------------------------------------------------------------
    # 6. Summary
    # ------------------------------------------------------------------
    log()
    log("=" * 96)
    log("6. FAZIT")
    log("=" * 96)

    unique_real = {}
    for item in real_hits:
        unique_real[item["url"]] = item

    log(f"Direkt getestete Ressourcen: {len(tested):,}")
    log(f"Echte Tmin/Tmax-Rohdaten-Treffer: {len(unique_real):,}")

    for url, item in unique_real.items():
        log(f"  TREFFER: {url}")
        log(f"    HEADER: {item['headers']}")
        for row in item["sample_rows"][:5]:
            log(f"    ROW: {row}")

    if unique_real:
        log()
        log(
            "ERGEBNIS: Maschinenlesbare ARSO-Tages-Temperaturdaten wurden "
            "gefunden. Im nächsten Schritt kann daraus der historische "
            "Slowenien-Cache gebaut werden."
        )
    else:
        log()
        log(
            "ERGEBNIS: Noch kein direkter Tmin/Tmax-Dateitreffer. "
            "Entscheidend sind jetzt die ausgegebenen JS-Zeilen um 'filen' "
            "und der iframe/src-Kontext; daraus lässt sich der exakte "
            "Dateiname im nächsten Schritt ableiten."
        )

    log()
    log("Bitte anschließend den GitHub-Log schicken, insbesondere:")
    log("2. JAVASCRIPT-KONTEXT ZUR DATENDATEI")
    log("3. KONTROLLIERTE AUSWAHL-REQUESTS")
    log("4. ENTDECKTE RESSOURCEN DIREKT PRÜFEN")
    log("5. KLEINE DIREKTE DATEINAMEN-PROBE")
    log("6. FAZIT")

    # Probe should not fail merely because the endpoint name is still unknown.
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
