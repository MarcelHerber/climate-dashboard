#!/usr/bin/env python3
"""Probe ARSO Slovenia climate time-series archive endpoints.

Step 2 only: no production cache.

The ARSO archive page exposes a POST form with:
  spr = tavg | tmin | tmax | tall | precip | snow | sun
  skrita_postaja = station slug, e.g. ljubljana
  meseclist = month selector
  letolist = year selector

This probe:
  1. parses the real archive HTML and inline JavaScript;
  2. extracts station slugs / numeric IDs where visible;
  3. submits controlled POST requests for Ljubljana;
  4. extracts generated historical GIF/resource URLs;
  5. tests a small set of direct raw-data companion URL patterns
     (.txt/.csv and graph->data/table variants);
  6. verifies current last30/last90 raw TXT files.

No OCR or image-value extraction is performed.
"""
from __future__ import annotations

import html
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://meteo.arso.gov.si"

ARCHIVE_URL = f"{BASE}/met/en/climate/current/time-series-archive/"
LAST30_URL = f"{BASE}/met/en/climate/current/last-30-days/"
LAST90_URL = f"{BASE}/met/en/climate/current/last-90-days/"

KNOWN_CURRENT = {
    "last30": (
        f"{BASE}/uploads/probase/www/climate/graph/en/by_location/"
        "ljubljana/last30days_ljubljana.txt"
    ),
    "last90": (
        f"{BASE}/uploads/probase/www/climate/graph/en/by_location/"
        "ljubljana/last90days_ljubljana.txt"
    ),
}

UA = "climate-dashboard-slovenia-arso-archive-probe/1.0 (+GitHub Actions)"
TIMEOUT = 60
TRIES = 4

cookiejar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cookiejar)
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def decode_bytes(raw: bytes, content_type: str = "") -> str:
    charset = "utf-8"
    m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, flags=re.I)
    if m:
        charset = m.group(1)
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def request(
    url: str,
    *,
    data: dict[str, str] | None = None,
    attempts: int = TRIES,
) -> tuple[bytes, str, int, str]:
    body = None
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }

    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            with opener.open(req, timeout=TIMEOUT) as response:
                raw = response.read()
                return (
                    raw,
                    response.geturl(),
                    getattr(response, "status", 200),
                    response.headers.get("Content-Type", ""),
                )
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def request_text(
    url: str,
    *,
    data: dict[str, str] | None = None,
) -> tuple[str, str, int, str]:
    raw, final, status, ctype = request(url, data=data)
    return decode_bytes(raw, ctype), final, status, ctype


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return " ".join(value.split())


def absolute(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value.strip()))


def extract_urls(text: str, base: str) -> list[str]:
    found = []

    for pattern in (
        r"""\b(?:src|href)\s*=\s*['"]([^'"]+)['"]""",
        r"""https?://[^\s"'<>]+""",
    ):
        for m in re.finditer(pattern, text, flags=re.I):
            value = m.group(1) if m.lastindex else m.group(0)
            url = absolute(base, value)
            if url not in found:
                found.append(url)

    return found


def extract_image_urls(text: str, base: str) -> list[str]:
    urls = []
    for m in re.finditer(
        r"""<img\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
        text,
        flags=re.I | re.S,
    ):
        url = absolute(base, m.group(1))
        if url not in urls:
            urls.append(url)
    return urls


def extract_select_options(
    text: str,
    select_name: str,
) -> list[tuple[str, str]]:
    pattern = (
        r"<select\b[^>]*\bname\s*=\s*['\"]"
        + re.escape(select_name)
        + r"['\"][^>]*>(.*?)</select>"
    )
    m = re.search(pattern, text, flags=re.I | re.S)
    if not m:
        return []

    out = []
    for om in re.finditer(
        r"<option\b([^>]*)>(.*?)</option>",
        m.group(1),
        flags=re.I | re.S,
    ):
        attrs = om.group(1)
        label = strip_tags(om.group(2))
        vm = re.search(
            r"\bvalue\s*=\s*['\"]([^'\"]*)['\"]",
            attrs,
            flags=re.I,
        )
        value = html.unescape(vm.group(1)) if vm else ""
        out.append((value, label))
    return out


def extract_station_clues(text: str) -> list[dict[str, str]]:
    """Collect station slug/name clues from HTML and JS."""
    clues: list[dict[str, str]] = []
    seen = set()

    # Common JS patterns which assign the hidden station slug.
    patterns = [
        r"""skrita_postaja[^;\n]{0,100}?value\s*=\s*['"]([^'"]+)['"]""",
        r"""skrita_postaja[^;\n]{0,100}?=\s*['"]([^'"]+)['"]""",
        r"""['"]skrita_postaja['"][^;\n]{0,100}?['"]([a-z0-9_-]+)['"]""",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            slug = m.group(1).strip()
            key = ("slug", slug)
            if slug and key not in seen:
                seen.add(key)
                clues.append({"type": "slug", "value": slug})

    # Paths reveal by_location slugs.
    for m in re.finditer(
        r"/by_location/([a-z0-9_-]+)/",
        text,
        flags=re.I,
    ):
        slug = m.group(1)
        key = ("path_slug", slug)
        if key not in seen:
            seen.add(key)
            clues.append({"type": "path_slug", "value": slug})

    # Archive image names reveal numeric station IDs.
    for m in re.finditer(
        r"/(?:archive/\d{4}/)?"
        r"(?:tavg|tmin|tmax|tall|precip|snow|sun)_([0-9]+)_",
        text,
        flags=re.I,
    ):
        sid = m.group(1)
        key = ("numeric_id", sid)
        if key not in seen:
            seen.add(key)
            clues.append({"type": "numeric_id", "value": sid})

    return clues


def print_script_clues(text: str) -> None:
    log("Inline-JavaScript-Treffer zu Monat/Jahr/Station:")
    printed = 0

    for lineno, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if any(
            token in low
            for token in (
                "meseclist",
                "letolist",
                "skrita_postaja",
                "months",
                "years",
                "tmax",
                "tmin",
                "archive",
            )
        ):
            cleaned = " ".join(html.unescape(line).split())
            if cleaned:
                log(f"  L{lineno}: {cleaned[:700]}")
                printed += 1
                if printed >= 120:
                    break


def interesting_archive_resources(text: str, base: str) -> list[str]:
    out = []
    for url in extract_urls(text, base):
        low = url.lower()
        if any(
            token in low
            for token in (
                "/archive/",
                "/by_location/",
                "tmax",
                "tmin",
                "tall",
                "tavg",
                ".txt",
                ".csv",
            )
        ):
            out.append(url)
    return out


def companion_candidates(image_url: str) -> list[str]:
    """Generate a deliberately small set of plausible raw-data companions."""
    candidates = []

    def add(url: str) -> None:
        if url not in candidates:
            candidates.append(url)

    parsed = urllib.parse.urlsplit(image_url)
    path = parsed.path

    if path.lower().endswith(".gif"):
        stem = path[:-4]
        for ext in (".txt", ".csv", ".dat"):
            add(urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, stem + ext, parsed.query, "")
            ))

    replacements = [
        ("/climate/graph/", "/climate/data/"),
        ("/climate/graph/", "/climate/table/"),
    ]

    for old, new in replacements:
        if old in path:
            replaced = path.replace(old, new)
            add(urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, replaced, parsed.query, "")
            ))

            if replaced.lower().endswith(".gif"):
                stem = replaced[:-4]
                for ext in (".txt", ".csv"):
                    add(urllib.parse.urlunsplit(
                        (parsed.scheme, parsed.netloc, stem + ext, parsed.query, "")
                    ))

    return candidates[:12]


def probe_candidate(url: str) -> dict[str, Any]:
    try:
        raw, final, status, ctype = request(url, attempts=2)
    except Exception as exc:
        return {
            "url": url,
            "ok": False,
            "error": str(exc),
        }

    preview = ""
    if (
        "text" in ctype.lower()
        or "csv" in ctype.lower()
        or "json" in ctype.lower()
        or url.lower().endswith((".txt", ".csv", ".dat"))
    ):
        preview = decode_bytes(raw[:4000], ctype)
        preview = "\n".join(preview.splitlines()[:8])

    return {
        "url": final,
        "ok": status == 200,
        "status": status,
        "content_type": ctype,
        "size": len(raw),
        "preview": preview,
    }


def inspect_current_raw() -> None:
    log()
    log("=" * 88)
    log("1. CURRENT-ROHDATEN")
    log("=" * 88)

    for label, url in KNOWN_CURRENT.items():
        try:
            text, final, status, ctype = request_text(url)
        except Exception as exc:
            log(f"{label}: FEHLER {exc}")
            continue

        lines = text.splitlines()
        log(
            f"{label}: HTTP {status} | {ctype} | "
            f"{len(lines)} Zeilen | {final}"
        )
        for line in lines[:5]:
            log(f"  {line}")


def inspect_archive_page() -> str:
    log()
    log("=" * 88)
    log("2. ARCHIV-SEITE / JAVASCRIPT")
    log("=" * 88)

    text, final, status, ctype = request_text(ARCHIVE_URL)
    log(f"URL: {final}")
    log(f"HTTP: {status} | {ctype}")
    log(f"HTML chars: {len(text):,}")

    months = extract_select_options(text, "meseclist")
    years = extract_select_options(text, "letolist")
    log(f"Serverseitige meseclist options: {months}")
    log(f"Serverseitige letolist options: {years}")

    clues = extract_station_clues(text)
    log(f"Stations-/ID-Clues: {len(clues)}")
    for clue in clues[:100]:
        log(f"  {clue['type']}: {clue['value']}")

    print_script_clues(text)

    return text


def post_archive_variants() -> None:
    log()
    log("=" * 88)
    log("3. ECHTE POST-ANFRAGEN AN DAS ZEITREIHENARCHIV")
    log("=" * 88)

    # Try a conservative matrix around the observed archive filename
    # tavg_192_002024.gif. We deliberately do not brute force.
    variants = []

    for spr in ("tmax", "tmin", "tall"):
        for month in ("0", "00", "7", "07"):
            variants.append(
                {
                    "spr": spr,
                    "skrita_postaja": "ljubljana",
                    "meseclist": month,
                    "letolist": "2024",
                }
            )

    unique_images = []
    successful_responses = 0

    for data in variants:
        try:
            text, final, status, ctype = request_text(
                ARCHIVE_URL,
                data=data,
            )
        except Exception as exc:
            log(f"POST {data}: FEHLER {exc}")
            continue

        successful_responses += 1
        images = [
            u for u in extract_image_urls(text, final)
            if any(
                token in u.lower()
                for token in (
                    "/archive/",
                    "tmax_",
                    "tmin_",
                    "tall_",
                )
            )
        ]
        resources = interesting_archive_resources(text, final)

        log()
        log(f"POST {data}")
        log(f"  HTTP {status} | {ctype} | response chars={len(text):,}")
        log(f"  relevante IMG: {len(images)}")
        for u in images[:20]:
            log(f"    IMG {u}")
            if u not in unique_images:
                unique_images.append(u)

        log(f"  relevante Ressourcen: {len(resources)}")
        for u in resources[:30]:
            log(f"    RES {u}")

        clues = extract_station_clues(text)
        if clues:
            log(
                "  IDs/Slugs: "
                + ", ".join(
                    f"{x['type']}={x['value']}" for x in clues[:30]
                )
            )

    log()
    log(f"Erfolgreiche POST-Responses: {successful_responses}/{len(variants)}")
    log(f"Eindeutige historische Daten-/Bildpfade: {len(unique_images)}")

    log()
    log("=" * 88)
    log("4. ROHDATEN-BEGLEITDATEIEN ZU DEN GEFUNDENEN GIFs")
    log("=" * 88)

    if not unique_images:
        log("Keine historischen GIF-Pfade aus POST-Responses extrahiert.")
        return

    tested = set()
    found_raw = []

    for image_url in unique_images[:8]:
        log(f"GIF-Basis: {image_url}")

        for candidate in companion_candidates(image_url):
            if candidate in tested:
                continue
            tested.add(candidate)

            result = probe_candidate(candidate)

            if result.get("ok"):
                log(
                    f"  TREFFER: {result['status']} "
                    f"{result.get('content_type')} "
                    f"{result.get('size')} bytes | {result['url']}"
                )
                if result.get("preview"):
                    log("  PREVIEW:")
                    for line in result["preview"].splitlines():
                        log(f"    {line}")
                found_raw.append(result)
            else:
                err = result.get("error", "")
                if "404" not in err:
                    log(f"  kein Treffer: {candidate} | {err[:160]}")

    log()
    log(f"Getestete Begleitpfade: {len(tested)}")
    log(f"Direkte Rohdaten-Treffer: {len(found_raw)}")


def inspect_current_pages_for_station_map() -> None:
    log()
    log("=" * 88)
    log("5. CURRENT-SEITEN: STATIONS-SLUGS")
    log("=" * 88)

    for url in (LAST30_URL, LAST90_URL):
        try:
            text, final, status, _ = request_text(url)
        except Exception as exc:
            log(f"{url}: FEHLER {exc}")
            continue

        clues = extract_station_clues(text)
        resources = [
            u for u in extract_urls(text, final)
            if "last30days_" in u.lower() or "last90days_" in u.lower()
        ]

        log(f"{final} | HTTP {status}")
        log(f"  Clues: {len(clues)}")
        for clue in clues[:100]:
            log(f"    {clue['type']}: {clue['value']}")
        log(f"  direkte TXT-Links: {len(resources)}")
        for u in resources[:100]:
            log(f"    {u}")


def main() -> int:
    log("=== ARSO SLOWENIEN · ARCHIVE ENDPOINT PROBE ===")
    log("Schritt 2 – noch kein Produktionscache.")
    log("Kein OCR; historische Werte werden nur aus echten Rohdaten übernommen.")
    log()

    inspect_current_raw()
    inspect_archive_page()
    post_archive_variants()
    inspect_current_pages_for_station_map()

    log()
    log("=" * 88)
    log("6. WAS ICH AUS DEM LOG BRAUCHE")
    log("=" * 88)
    log("Bitte den vollständigen Log schicken, besonders:")
    log("2. ARCHIV-SEITE / JAVASCRIPT")
    log("3. ECHTE POST-ANFRAGEN AN DAS ZEITREIHENARCHIV")
    log("4. ROHDATEN-BEGLEITDATEIEN ZU DEN GEFUNDENEN GIFs")
    log("5. CURRENT-SEITEN: STATIONS-SLUGS")
    return 0


def self_test() -> None:
    html_sample = """
      <input type="hidden" name="skrita_postaja" value="ljubljana">
      <img src="/uploads/probase/www/climate/graph/en/by_location/ljubljana/
      archive/2024/tmax_192_002024.gif">
      <select name="meseclist"><option value="0">year</option></select>
      <select name="letolist"><option value="2024">2024</option></select>
    """

    clues = extract_station_clues(html_sample)
    assert any(
        x["type"] == "slug" and x["value"] == "ljubljana"
        for x in clues
    )
    assert any(
        x["type"] == "numeric_id" and x["value"] == "192"
        for x in clues
    )

    months = extract_select_options(html_sample, "meseclist")
    years = extract_select_options(html_sample, "letolist")
    assert months == [("0", "year")]
    assert years == [("2024", "2024")]

    gif = (
        "https://meteo.arso.gov.si/uploads/probase/www/climate/graph/en/"
        "by_location/ljubljana/archive/2024/tmax_192_002024.gif"
    )
    candidates = companion_candidates(gif)
    assert any(x.endswith(".txt") for x in candidates)
    assert any("/climate/data/" in x for x in candidates)

    print("ARSO Slovenia archive endpoint probe self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
