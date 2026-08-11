#!/usr/bin/env python3
"""Probe official ARSO Slovenia daily temperature sources.

No production cache is built in this step.

Goals:
  1. Inspect ARSO current-climate pages for station IDs/slugs and direct data files.
  2. Verify current daily Tmin/Tmax text files.
  3. Enumerate the official meteorological yearbooks (2000-2016) and their
     daily station pages / station IDs.
  4. Inspect the general measurements archive and agrometeorological daily-data
     form to discover machine-readable endpoints, form parameter names and
     station options.
  5. Print enough information to decide the historical/current cache strategy.

Official ARSO climate-day convention:
  Daily Tmin/Tmax are extrema in the 24-hour interval from 21:00 of the
  previous day to 21:00 of the labelled day (solar or winter time depending
  on station type).
"""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Any

BASE = "https://meteo.arso.gov.si"

PAGES = {
    "archive_measurements": f"{BASE}/met/sl/archive/",
    "climate_current_30_en": f"{BASE}/met/en/climate/current/last-30-days/",
    "climate_timeseries_archive_en": f"{BASE}/met/en/climate/current/time-series-archive/",
    "agromet_month": f"{BASE}/met/sl/agromet/data/month/",
    "yearbook_index": f"{BASE}/met/sl/climate/tables/yearbook/?method=init",
    "stations_variables": f"{BASE}/met/sl/climate/stations-by-variables/",
    "observation_stations": f"{BASE}/met/sl/climate/observation-stations/",
}

KNOWN_CURRENT_LJUBLJANA = (
    f"{BASE}/uploads/probase/www/climate/graph/en/by_location/"
    "ljubljana/last30days_ljubljana.txt"
)

YEARBOOK_LIST_URL = (
    f"{BASE}/met/sl/climate/tables/yearbook/{{year}}/station-data/"
)

UA = "climate-dashboard-slovenia-arso-probe/1.0 (+GitHub Actions)"
TIMEOUT = 60
TRIES = 4


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fetch(url: str, attempts: int = TRIES) -> tuple[str, str, int]:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,text/plain,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                final = r.geturl()
                status = getattr(r, "status", 200)
            return raw.decode("utf-8", errors="replace"), final, status
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return " ".join(value.split())


def absolute(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(href))


def extract_links(text: str, base: str) -> list[tuple[str, str]]:
    out = []
    for match in re.finditer(
        r"<a\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        text,
        flags=re.I | re.S,
    ):
        href = absolute(base, match.group(1).strip())
        label = strip_tags(match.group(2))
        out.append((label, href))
    return out


def extract_resources(text: str, base: str) -> list[str]:
    found = []
    patterns = [
        r"\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
        r"\bhref\s*=\s*['\"]([^'\"]+)['\"]",
        r"""https?://[^\s"'<>]+""",
        r"""['"]([^'"]+\.(?:txt|csv|json|xml|zip|html|js)(?:\?[^'"]*)?)['"]""",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            value = m.group(1) if m.lastindex else m.group(0)
            value = html.unescape(value.strip())
            if not value:
                continue
            url = absolute(base, value)
            if url not in found:
                found.append(url)
    return found


def print_forms(text: str, base: str) -> None:
    forms = list(
        re.finditer(r"<form\b([^>]*)>(.*?)</form>", text, flags=re.I | re.S)
    )

    log(f"HTML-Formulare: {len(forms)}")
    for i, fm in enumerate(forms[:10], 1):
        attrs = fm.group(1)
        body = fm.group(2)

        action_m = re.search(
            r"\baction\s*=\s*['\"]([^'\"]*)['\"]", attrs, flags=re.I
        )
        method_m = re.search(
            r"\bmethod\s*=\s*['\"]([^'\"]*)['\"]", attrs, flags=re.I
        )

        action = absolute(base, action_m.group(1)) if action_m else base
        method = method_m.group(1).upper() if method_m else "GET"

        log(f"  FORM {i}: method={method} action={action}")

        names = []
        for inp in re.finditer(
            r"<(?:input|select|textarea)\b([^>]*)>",
            body,
            flags=re.I | re.S,
        ):
            a = inp.group(1)
            nm = re.search(
                r"\bname\s*=\s*['\"]([^'\"]+)['\"]", a, flags=re.I
            )
            typ = re.search(
                r"\btype\s*=\s*['\"]([^'\"]+)['\"]", a, flags=re.I
            )
            val = re.search(
                r"\bvalue\s*=\s*['\"]([^'\"]*)['\"]", a, flags=re.I
            )
            if nm:
                names.append(
                    (
                        nm.group(1),
                        typ.group(1) if typ else "",
                        html.unescape(val.group(1)) if val else "",
                    )
                )

        for name, typ, value in names[:40]:
            log(f"    field name={name!r} type={typ!r} value={value!r}")

        selects = list(
            re.finditer(
                r"<select\b([^>]*)>(.*?)</select>",
                body,
                flags=re.I | re.S,
            )
        )
        for sm in selects[:10]:
            attrs2, options_body = sm.group(1), sm.group(2)
            nm = re.search(
                r"\bname\s*=\s*['\"]([^'\"]+)['\"]",
                attrs2,
                flags=re.I,
            )
            name = nm.group(1) if nm else "?"
            options = []
            for om in re.finditer(
                r"<option\b([^>]*)>(.*?)</option>",
                options_body,
                flags=re.I | re.S,
            ):
                oa, label = om.group(1), strip_tags(om.group(2))
                vm = re.search(
                    r"\bvalue\s*=\s*['\"]([^'\"]*)['\"]",
                    oa,
                    flags=re.I,
                )
                options.append(
                    (html.unescape(vm.group(1)) if vm else "", label)
                )

            log(f"    SELECT {name!r}: {len(options)} options")
            for value, label in options[:30]:
                log(f"      {value!r} -> {label}")


def parse_current_txt(text: str) -> list[dict[str, Any]]:
    rows = []
    line_re = re.compile(
        r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s+"
        r"(-?\d+(?:\.\d+)?)\s+"
        r"(-?\d+(?:\.\d+)?)\s+"
        r"(-?\d+(?:\.\d+)?)\s+"
        r"(-?\d+(?:\.\d+)?)\s+"
        r"(-?\d+(?:\.\d+)?)"
    )
    for line in text.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        day, month, year = map(int, m.group(1, 2, 3))
        rows.append(
            {
                "date": f"{year:04d}-{month:02d}-{day:02d}",
                "tmean": float(m.group(4)),
                "tmean_ref": float(m.group(5)),
                "tmin": float(m.group(6)),
                "tmin_ref": float(m.group(7)),
                "tmax": float(m.group(8)),
            }
        )
    return rows


def parse_yearbook_station_links(
    text: str,
    base_url: str,
) -> list[dict[str, Any]]:
    out = []

    for label, href in extract_links(text, base_url):
        m = re.search(r"/(\d{4})_temdnev_(\d+)\.html(?:\?|$)", href)
        if not m:
            continue
        out.append(
            {
                "name": label,
                "year": int(m.group(1)),
                "arso_yearbook_id": int(m.group(2)),
                "url": href,
            }
        )

    # Sometimes the CMS wraps the links differently. Also search raw hrefs.
    if not out:
        for m in re.finditer(
            r"""href\s*=\s*['"]([^'"]*/(\d{4})_temdnev_(\d+)\.html[^'"]*)['"]""",
            text,
            flags=re.I,
        ):
            out.append(
                {
                    "name": "?",
                    "year": int(m.group(2)),
                    "arso_yearbook_id": int(m.group(3)),
                    "url": absolute(base_url, m.group(1)),
                }
            )

    unique = {}
    for x in out:
        unique[(x["year"], x["arso_yearbook_id"])] = x
    return sorted(unique.values(), key=lambda x: (x["year"], x["name"]))


def probe_yearbook_station_page(url: str) -> dict[str, Any]:
    text, final, status = fetch(url)

    title_m = re.search(
        r"(?:postajo|station)\s+([^<\n]+?)\s+(?:za leto|and year)",
        strip_tags(text),
        flags=re.I,
    )
    title = title_m.group(1).strip() if title_m else ""

    dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)

    # ARSO yearbook columns are explicitly TM (daily max) and Tm (daily min).
    has_tm_headers = bool(
        re.search(r">\s*TM\s*<", text, flags=re.I)
        and re.search(r">\s*Tm\s*<", text)
    )

    # Count daily date rows and sample text around first date.
    sample = ""
    if dates:
        idx = text.find(dates[0])
        if idx >= 0:
            sample = strip_tags(text[idx : idx + 1000])[:500]

    return {
        "url": final,
        "status": status,
        "title": title,
        "date_rows": len(set(dates)),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "tm_headers": has_tm_headers,
        "sample": sample,
    }


def main() -> int:
    log("=== ARSO SLOWENIEN PROBE ===")
    log("Nur Quellenerkundung – noch kein Cache.")
    log()

    # ------------------------------------------------------------------
    # 1. Current official climate TXT
    # ------------------------------------------------------------------
    log("=" * 84)
    log("1. AKTUELLE ARSO-TAGESDATEN")
    log("=" * 84)

    current_text, current_final, current_status = fetch(KNOWN_CURRENT_LJUBLJANA)
    current_rows = parse_current_txt(current_text)

    log(f"URL: {current_final}")
    log(f"HTTP: {current_status}")
    log(f"Geparste Tageszeilen: {len(current_rows)}")
    if current_rows:
        log(f"Erste Zeile: {current_rows[0]}")
        log(f"Letzte Zeile: {current_rows[-1]}")
        log(
            "TMAX Bereich Sample: "
            f"{min(x['tmax'] for x in current_rows):.1f} bis "
            f"{max(x['tmax'] for x in current_rows):.1f} °C"
        )
        log(
            "TMIN Bereich Sample: "
            f"{min(x['tmin'] for x in current_rows):.1f} bis "
            f"{max(x['tmin'] for x in current_rows):.1f} °C"
        )

    # ------------------------------------------------------------------
    # 2. Discover current page station slugs / resources.
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("2. CURRENT-CLIMATE HTML / STATIONS- UND DATEI-ENTDECKUNG")
    log("=" * 84)

    cur_page, cur_url, _ = fetch(PAGES["climate_current_30_en"])
    resources = extract_resources(cur_page, cur_url)

    interesting = [
        u for u in resources
        if any(
            token in u.lower()
            for token in (
                "climate",
                "last30",
                "last90",
                "by_location",
                ".txt",
                ".js",
                ".xml",
                ".json",
            )
        )
    ]
    log(f"Entdeckte Ressourcen gesamt: {len(resources)}")
    log(f"Davon interessant: {len(interesting)}")
    for url in interesting[:100]:
        log(f"  {url}")

    print_forms(cur_page, cur_url)

    # ------------------------------------------------------------------
    # 3. Meteorological yearbooks
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("3. METEOROLOGISCHE JAHRBÜCHER 2000–2016")
    log("=" * 84)

    total_links = 0
    all_station_ids = Counter()
    yearly_counts = {}
    sample_pages = []

    for year in range(2000, 2017):
        url = YEARBOOK_LIST_URL.format(year=year)
        try:
            text, final, status = fetch(url)
        except Exception as exc:
            log(f"{year}: FEHLER {exc}")
            continue

        links = parse_yearbook_station_links(text, final)
        yearly_counts[year] = len(links)
        total_links += len(links)

        for row in links:
            all_station_ids[row["arso_yearbook_id"]] += 1

        names = [x["name"] for x in links]
        log(
            f"{year}: {len(links)} tägliche Stationsseiten | "
            f"{', '.join(names[:15])}"
        )

        if year in {2000, 2016}:
            sample_pages.extend(links[:3])

    log(f"Jahrbuch-Stationsseiten gesamt: {total_links}")
    log(f"Eindeutige Jahrbuch-IDs: {len(all_station_ids)}")
    log(
        "IDs über die Jahre: "
        + ", ".join(
            f"{sid}({count}J)"
            for sid, count in all_station_ids.most_common()
        )
    )

    log()
    log("Jahrbuch-Dateiproben:")
    seen = set()
    for row in sample_pages:
        key = row["url"]
        if key in seen:
            continue
        seen.add(key)
        try:
            info = probe_yearbook_station_page(row["url"])
            log(
                f"  {row['year']} | {row['name']} | "
                f"ID={row['arso_yearbook_id']} | "
                f"rows={info['date_rows']} | "
                f"{info['first_date']}..{info['last_date']} | "
                f"TM/Tm={info['tm_headers']}"
            )
            log(f"    SAMPLE: {info['sample']}")
        except Exception as exc:
            log(f"  FEHLER {row['url']}: {exc}")

    # ------------------------------------------------------------------
    # 4. General measurements archive
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("4. ALLGEMEINER ARSO-MESSARCHIV")
    log("=" * 84)

    archive_html, archive_url, archive_status = fetch(
        PAGES["archive_measurements"]
    )
    log(f"URL: {archive_url} | HTTP {archive_status}")
    log(f"HTML bytes/chars: {len(archive_html):,}")
    print_forms(archive_html, archive_url)

    archive_resources = extract_resources(archive_html, archive_url)
    archive_interesting = [
        u for u in archive_resources
        if any(
            token in u.lower()
            for token in (
                "archive",
                "data",
                "ajax",
                "json",
                "xml",
                "csv",
                "js",
                "download",
            )
        )
    ]
    log(f"Interessante Archive-Ressourcen: {len(archive_interesting)}")
    for url in archive_interesting[:120]:
        log(f"  {url}")

    # Search useful literal strings in source.
    keywords = (
        "station",
        "postaj",
        "parameter",
        "daily",
        "dnev",
        "ajax",
        "download",
        "csv",
        "json",
    )
    log("Quelltext-Treffer:")
    source_lines = archive_html.splitlines()
    printed = 0
    for lineno, line in enumerate(source_lines, 1):
        low = line.lower()
        if any(k in low for k in keywords):
            cleaned = strip_tags(line)
            if cleaned:
                log(f"  L{lineno}: {cleaned[:500]}")
                printed += 1
                if printed >= 80:
                    break

    # ------------------------------------------------------------------
    # 5. Agrometeorological daily monthly form
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("5. ARSO AGROMET-TAGESDATENFORMULAR")
    log("=" * 84)

    agro_html, agro_url, agro_status = fetch(PAGES["agromet_month"])
    log(f"URL: {agro_url} | HTTP {agro_status}")
    log(f"HTML bytes/chars: {len(agro_html):,}")
    print_forms(agro_html, agro_url)

    agro_resources = extract_resources(agro_html, agro_url)
    agro_interesting = [
        u for u in agro_resources
        if any(
            token in u.lower()
            for token in (
                "agromet",
                "data",
                "form",
                ".txt",
                ".csv",
                ".json",
                ".js",
            )
        )
    ]
    log(f"Interessante Agromet-Ressourcen: {len(agro_interesting)}")
    for url in agro_interesting[:120]:
        log(f"  {url}")

    # ------------------------------------------------------------------
    # 6. Time-series archive page
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("6. KLIMA-ZEITREIHENARCHIV HTML")
    log("=" * 84)

    ts_html, ts_url, ts_status = fetch(
        PAGES["climate_timeseries_archive_en"]
    )
    log(f"URL: {ts_url} | HTTP {ts_status}")
    log(f"HTML bytes/chars: {len(ts_html):,}")
    print_forms(ts_html, ts_url)

    ts_resources = extract_resources(ts_html, ts_url)
    ts_interesting = [
        u for u in ts_resources
        if any(
            token in u.lower()
            for token in (
                "climate",
                "archive",
                "graph",
                "by_location",
                ".txt",
                ".csv",
                ".js",
                ".json",
            )
        )
    ]
    log(f"Interessante Zeitreihen-Ressourcen: {len(ts_interesting)}")
    for url in ts_interesting[:150]:
        log(f"  {url}")

    # ------------------------------------------------------------------
    # 7. Summary
    # ------------------------------------------------------------------
    log()
    log("=" * 84)
    log("7. FAZIT")
    log("=" * 84)
    log(
        "ARSO aktuelle Tmin/Tmax-Datei Ljubljana: "
        + ("OK" if current_rows else "NICHT PARSBAR")
    )
    log(
        "ARSO Jahrbücher 2000–2016: "
        f"{total_links} Stationsjahres-Seiten / "
        f"{len(all_station_ids)} eindeutige IDs"
    )
    log(
        "Nächste Entscheidung anhand des Logs: "
        "ob allgemeines Messarchiv / Klima-Zeitreihenarchiv direkt "
        "automatisierbare vollständige historische Tagesdaten liefert."
    )
    log()
    log("Bitte den vollständigen GitHub-Log schicken, insbesondere:")
    log("1. AKTUELLE ARSO-TAGESDATEN")
    log("2. CURRENT-CLIMATE HTML / STATIONS- UND DATEI-ENTDECKUNG")
    log("3. METEOROLOGISCHE JAHRBÜCHER 2000–2016")
    log("4. ALLGEMEINER ARSO-MESSARCHIV")
    log("5. ARSO AGROMET-TAGESDATENFORMULAR")
    log("6. KLIMA-ZEITREIHENARCHIV HTML")

    return 0


def self_test() -> None:
    sample = """Climate data for the last 30 days for the station of Ljubljana
       Date     Tmean  Tmean_ref  Tmin  Tmin_ref   Tmax   Tmax_ref
      3.8.2026   30.4     22.2    19.9    16.5     38.6     28.5
    """
    rows = parse_current_txt(sample)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-03"
    assert rows[0]["tmax"] == 38.6
    assert rows[0]["tmin"] == 19.9

    sample_html = """
    <a href="/uploads/probase/www/climate/table/sl/yearbook/2016/2016_temdnev_192.html">
      Ljubljana
    </a>
    """
    links = parse_yearbook_station_links(
        sample_html,
        "https://meteo.arso.gov.si/x/",
    )
    assert len(links) == 1
    assert links[0]["arso_yearbook_id"] == 192
    assert links[0]["name"] == "Ljubljana"

    print("ARSO Slovenia probe self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
