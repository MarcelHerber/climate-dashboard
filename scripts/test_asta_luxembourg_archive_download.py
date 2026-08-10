#!/usr/bin/env python3
"""
Deep probe for historical ASTA / AgriMeteo Luxembourg downloads.

Purpose
-------
The official INSPIRE daily WFS is excellent for current/recent data but only
retains about two years. ASTA states that all weather data can be downloaded
through its data-query interface and that historical statistics start in 1949.

This probe inspects the public AgriMeteo / Lotus Domino station pages and tries
to discover the machine-readable historical export mechanism without making
assumptions about hidden URLs.

It prints:
- station resource URLs found on data.public.lu
- HTML forms, input/select names, iframe/script URLs
- links containing download/export/statistics/data keywords
- Lotus Domino-style agent/view/form URLs
- likely CSV/XLS/TXT endpoints
- selected JavaScript snippets containing relevant endpoint strings
- optional safe GET probes for discovered links

No API key / login is required.
"""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any

DATASET_PAGE = (
    "https://data.public.lu/en/datasets/"
    "agrometeorological-measurement-network-luxemburg/"
)
UA = "climate-dashboard-asta-luxembourg-archive-probe/1.1"
TIMEOUT = 120
TRIES = 4

STATION_LIMIT_DEFAULT = 6

KEYWORDS = (
    "download",
    "export",
    "csv",
    "xls",
    "xlsx",
    "txt",
    "daten",
    "data",
    "grafik",
    "graph",
    "stat",
    "tages",
    "daily",
    "10-min",
    "10min",
    "archive",
    "archiv",
    "original",
    "query",
    "auskunft",
    "weather",
    "meteo",
)

DOMINO_MARKERS = (
    "?openagent",
    "?openview",
    "?opendocument",
    "?openform",
    "?readviewentries",
    ".nsf/",
    "webquerysaveagent",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def http_bytes(
    url: str,
    *,
    accept: str = "*/*",
) -> tuple[bytes, str, str]:
    last: Exception | None = None

    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": accept,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                raw = response.read()
                final_url = response.geturl()
                ctype = response.headers.get("Content-Type", "")
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw, final_url, ctype
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
            wait = min(20, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


class PageParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, Any]] = []
        self.forms: list[dict[str, Any]] = []
        self.scripts: list[str] = []
        self.inline_scripts: list[str] = []
        self.iframes: list[dict[str, str]] = []
        self.event_handlers: list[dict[str, str]] = []

        self._active_link: dict[str, Any] | None = None
        self._current_form: dict[str, Any] | None = None
        self._current_select: dict[str, Any] | None = None
        self._current_option: dict[str, Any] | None = None
        self._in_inline_script = False
        self._inline_script_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        ad = {str(k): ("" if v is None else str(v)) for k, v in attrs}
        low = tag.lower()

        # Capture inline JS handlers from any element.
        for key, value in ad.items():
            if key.lower().startswith("on") and value:
                self.event_handlers.append(
                    {"tag": low, "event": key, "code": value}
                )

        if low == "a" and ad.get("href"):
            self._active_link = {
                "href": ad["href"],
                "text": [],
                "attrs": ad,
            }

        elif low == "form":
            form = {
                "action": ad.get("action", ""),
                "method": ad.get("method", "GET").upper(),
                "name": ad.get("name", ""),
                "id": ad.get("id", ""),
                "enctype": ad.get("enctype", ""),
                "onsubmit": ad.get("onsubmit", ""),
                "attrs": ad,
                "inputs": [],
                "selects": [],
                "buttons": [],
            }
            self.forms.append(form)
            self._current_form = form

        elif low == "input" and self._current_form is not None:
            self._current_form["inputs"].append(
                {
                    "name": ad.get("name", ""),
                    "type": ad.get("type", ""),
                    "value": ad.get("value", ""),
                    "id": ad.get("id", ""),
                    "onclick": ad.get("onclick", ""),
                    "checked": "checked" in ad,
                    "attrs": ad,
                }
            )

        elif low == "select" and self._current_form is not None:
            select = {
                "name": ad.get("name", ""),
                "id": ad.get("id", ""),
                "multiple": "multiple" in ad,
                "onchange": ad.get("onchange", ""),
                "options": [],
                "attrs": ad,
            }
            self._current_form["selects"].append(select)
            self._current_select = select

        elif low == "option" and self._current_select is not None:
            option = {
                "value": ad.get("value", ""),
                "selected": "selected" in ad,
                "text": [],
            }
            self._current_select["options"].append(option)
            self._current_option = option

        elif low == "button" and self._current_form is not None:
            self._current_form["buttons"].append(
                {
                    "type": ad.get("type", ""),
                    "name": ad.get("name", ""),
                    "value": ad.get("value", ""),
                    "id": ad.get("id", ""),
                    "onclick": ad.get("onclick", ""),
                    "attrs": ad,
                }
            )

        elif low == "script":
            if ad.get("src"):
                self.scripts.append(ad["src"])
            else:
                self._in_inline_script = True
                self._inline_script_parts = []

        elif low == "iframe" and ad.get("src"):
            self.iframes.append(
                {
                    "src": ad["src"],
                    "name": ad.get("name", ""),
                    "id": ad.get("id", ""),
                }
            )

    def handle_data(self, data: str) -> None:
        if self._active_link is not None:
            self._active_link["text"].append(data)
        if self._current_option is not None:
            self._current_option["text"].append(data)
        if self._in_inline_script:
            self._inline_script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()

        if low == "a" and self._active_link is not None:
            item = self._active_link
            item["text"] = " ".join(
                " ".join(item["text"]).split()
            )
            self.links.append(item)
            self._active_link = None

        elif low == "option" and self._current_option is not None:
            self._current_option["text"] = " ".join(
                " ".join(self._current_option["text"]).split()
            )
            self._current_option = None

        elif low == "select":
            self._current_select = None

        elif low == "form":
            self._current_form = None
            self._current_select = None
            self._current_option = None

        elif low == "script" and self._in_inline_script:
            text = "\n".join(self._inline_script_parts).strip()
            if text:
                self.inline_scripts.append(text)
            self._in_inline_script = False
            self._inline_script_parts = []


def parse_page(raw: bytes) -> tuple[str, PageParser]:
    text = raw.decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(text)
    return text, parser


def relevant(text: str) -> bool:
    lower = text.lower()
    return (
        any(k in lower for k in KEYWORDS)
        or any(k in lower for k in DOMINO_MARKERS)
    )


def station_links_from_dataset(
    text: str,
    parser: PageParser,
) -> list[str]:
    out = []
    seen = set()

    for link in parser.links:
        href = link.get("href", "")
        absolute = urllib.parse.urljoin(DATASET_PAGE, href)
        lower = absolute.lower()

        if (
            "agrimeteo.lu" in lower
            and ".nsf/" in lower
            and "opendocument" in lower
        ):
            if absolute not in seen:
                seen.add(absolute)
                out.append(absolute)

    # Fallback regex for data.public.lu degraded HTML.
    for match in re.findall(
        r'https?://[^"\'<>\s]+agrimeteo\.lu[^"\'<>\s]+',
        text,
        flags=re.I,
    ):
        url = match.replace("&amp;", "&")
        if ".nsf/" in url.lower() and "opendocument" in url.lower():
            if url not in seen:
                seen.add(url)
                out.append(url)

    return out


def normalize_download_tab(url: str) -> str:
    """
    Existing station pages use TableRow=3.9 for 'Download / Grafik'.
    Preserve the station document id while switching only the tab.
    """
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(
        parsed.query,
        keep_blank_values=True,
    )
    query["TableRow"] = ["3.9"]

    # Domino OpenDocument can appear as bare/empty argument.
    if not any(k.lower().startswith("opendocument") for k in query):
        query["OpenDocument"] = [""]

    new_query = urllib.parse.urlencode(
        query,
        doseq=True,
    )
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            new_query,
            parsed.fragment,
        )
    )


def extract_strings(
    text: str,
) -> list[str]:
    """
    Find URL-ish and endpoint-ish strings in inline HTML/JavaScript.
    """
    patterns = [
        r'https?://[^"\'<>\s]+',
        r'["\']([^"\']*(?:\.nsf/|\?OpenAgent|\?OpenView|\?OpenForm|'
        r'ReadViewEntries|WebQuerySaveAgent|download|export|csv|xls)'
        r'[^"\']*)["\']',
    ]

    out = []
    seen = set()

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            value = value.replace("\\/", "/").replace("&amp;", "&")
            if value and relevant(value) and value not in seen:
                seen.add(value)
                out.append(value)

    return out


def inspect_url(
    url: str,
    *,
    label: str,
    print_html_strings: bool = True,
) -> dict[str, Any]:
    raw, final_url, ctype = http_bytes(
        url,
        accept="text/html,application/xhtml+xml,*/*",
    )
    text, parser = parse_page(raw)

    log()
    log(f"--- {label} ---")
    log(f"URL: {url}")
    if final_url != url:
        log(f"Final URL: {final_url}")
    log(f"Content-Type: {ctype}")
    log(f"Bytes: {len(raw):,}")
    log(
        f"HTML-Struktur: {len(parser.links)} Links | "
        f"{len(parser.forms)} Forms | "
        f"{len(parser.scripts)} externe Scripts | "
        f"{len(parser.iframes)} Iframes"
    )

    if parser.forms:
        log("FORMULARE:")
        for i, form in enumerate(parser.forms, 1):
            log(
                f"  Form {i}: method={form['method']} "
                f"action={form['action']!r} "
                f"name={form['name']!r} id={form['id']!r} "
                f"enctype={form['enctype']!r} "
                f"onsubmit={form['onsubmit']!r}"
            )
            for inp in form["inputs"][:120]:
                log(
                    f"    input name={inp['name']!r} "
                    f"type={inp['type']!r} value={inp['value']!r} "
                    f"id={inp['id']!r} onclick={inp['onclick']!r}"
                )
            for sel in form["selects"][:80]:
                log(
                    f"    select name={sel['name']!r} "
                    f"id={sel['id']!r} onchange={sel['onchange']!r} "
                    f"options={len(sel['options'])}"
                )
                for opt in sel["options"][:60]:
                    log(
                        f"      option value={opt['value']!r} "
                        f"selected={opt['selected']} "
                        f"text={opt['text']!r}"
                    )
            for btn in form["buttons"][:50]:
                log(
                    f"    button type={btn['type']!r} "
                    f"name={btn['name']!r} value={btn['value']!r} "
                    f"id={btn['id']!r} onclick={btn['onclick']!r}"
                )

    rel_links = []
    for item in parser.links:
        href = item.get("href", "")
        text_label = str(item.get("text", ""))
        absolute = urllib.parse.urljoin(final_url, href)
        if relevant(absolute + " " + text_label):
            rel_links.append((absolute, text_label))

    if rel_links:
        log("RELEVANTE LINKS:")
        for href, link_text in rel_links[:100]:
            log(f"  {link_text or '(ohne Text)'} -> {href}")

    if parser.iframes:
        log("IFRAMES:")
        for item in parser.iframes[:50]:
            absolute = urllib.parse.urljoin(final_url, item["src"])
            log(
                f"  src={absolute} | name={item['name']!r} "
                f"id={item['id']!r}"
            )

    if parser.scripts:
        log("EXTERNE SCRIPTS:")
        for src in parser.scripts[:50]:
            log(f"  {urllib.parse.urljoin(final_url, src)}")

    if parser.event_handlers:
        log("INLINE EVENT-HANDLER:")
        for item in parser.event_handlers[:100]:
            if relevant(item["code"]) or any(
                token in item["code"].lower()
                for token in ("submit", "location", "window", "form")
            ):
                log(
                    f"  <{item['tag']}> {item['event']}="
                    f"{item['code']!r}"
                )

    if parser.inline_scripts:
        log("RELEVANTE INLINE-SCRIPTS:")
        for js in parser.inline_scripts[:30]:
            snippets = extract_strings(js)
            if snippets or relevant(js):
                compact = " ".join(js.split())
                log(f"  {compact[:1800]}")

    strings = extract_strings(text) if print_html_strings else []
    if strings:
        log("RELEVANTE INLINE-STRINGS:")
        for value in strings[:120]:
            log(f"  {value}")

    return {
        "raw": raw,
        "text": text,
        "parser": parser,
        "final_url": final_url,
        "content_type": ctype,
        "relevant_links": rel_links,
        "strings": strings,
    }


def inspect_external_scripts(
    base_url: str,
    script_srcs: list[str],
) -> list[str]:
    hits = []
    seen = set()

    for src in script_srcs[:20]:
        url = urllib.parse.urljoin(base_url, src)
        if url in seen:
            continue
        seen.add(url)

        try:
            raw, final_url, ctype = http_bytes(
                url,
                accept="application/javascript,text/javascript,text/plain,*/*",
            )
        except Exception as exc:
            log(f"Script konnte nicht geladen werden: {url} -> {exc}")
            continue

        text = raw.decode("utf-8", errors="replace")
        found = extract_strings(text)

        if found:
            log()
            log(f"JAVASCRIPT-TREFFER: {final_url} ({len(raw):,} Bytes)")
            for value in found[:120]:
                log(f"  {value}")
                hits.append(
                    urllib.parse.urljoin(final_url, value)
                )

    return hits


def inspect_iframe_tree(
    parent: dict[str, Any],
    *,
    label_prefix: str,
    max_iframes: int = 4,
) -> list[dict[str, Any]]:
    results = []
    for idx, item in enumerate(parent["parser"].iframes[:max_iframes], 1):
        url = urllib.parse.urljoin(
            parent["final_url"],
            item["src"],
        )
        try:
            child = inspect_url(
                url,
                label=f"{label_prefix} IFRAME {idx}",
            )
        except Exception as exc:
            log(f"Iframe konnte nicht geladen werden: {url} -> {exc}")
            continue
        results.append(child)
    return results


def form_endpoint_score(
    form: dict[str, Any],
    base_url: str,
) -> tuple[int, str]:
    action = urllib.parse.urljoin(base_url, form.get("action", ""))
    hay = (
        action + " " +
        str(form.get("name", "")) + " " +
        str(form.get("id", "")) + " " +
        str(form.get("onsubmit", ""))
    ).lower()

    for inp in form.get("inputs", []):
        hay += " " + " ".join(
            str(inp.get(k, "")) for k in ("name", "value", "onclick")
        ).lower()

    for sel in form.get("selects", []):
        hay += " " + str(sel.get("name", "")).lower()
        for opt in sel.get("options", []):
            hay += " " + str(opt.get("value", "")).lower()

    score = 0
    for token in (
        "download", "export", "csv", "xls", "txt",
        "openagent", "webquerysaveagent", "query", "grafik",
        "station", "date", "datum", "from", "to", "von", "bis",
    ):
        if token in hay:
            score += 5
    if form.get("method", "GET").upper() == "POST":
        score += 2
    if form.get("action"):
        score += 2
    return score, action


def print_compact_form_candidates(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for page in pages:
        for form in page["parser"].forms:
            score, action = form_endpoint_score(
                form,
                page["final_url"],
            )
            candidates.append(
                {
                    "score": score,
                    "page": page["final_url"],
                    "action": action,
                    "method": form.get("method"),
                    "name": form.get("name"),
                    "id": form.get("id"),
                    "inputs": form.get("inputs", []),
                    "selects": form.get("selects", []),
                    "buttons": form.get("buttons", []),
                    "onsubmit": form.get("onsubmit", ""),
                }
            )

    candidates.sort(key=lambda x: (-x["score"], x["action"]))
    log()
    log("=== KOMPAKTE FORM-/EXPORT-KANDIDATEN ===")
    for cand in candidates[:30]:
        log(
            f"Score {cand['score']:>3} | {cand['method']} | "
            f"action={cand['action']}"
        )
        log(
            f"  page={cand['page']} | name={cand['name']!r} "
            f"id={cand['id']!r} onsubmit={cand['onsubmit']!r}"
        )
        for inp in cand["inputs"][:40]:
            log(
                f"  INPUT {inp['name']} type={inp['type']} "
                f"value={inp['value']!r} onclick={inp['onclick']!r}"
            )
        for sel in cand["selects"][:30]:
            opts = [
                f"{o['value']}:{o['text']}"
                for o in sel.get("options", [])[:30]
            ]
            log(
                f"  SELECT {sel['name']} -> "
                + " | ".join(opts)
            )
        for btn in cand["buttons"][:20]:
            log(
                f"  BUTTON {btn['name']} value={btn['value']!r} "
                f"onclick={btn['onclick']!r}"
            )
    return candidates


def safe_probe_candidate(
    url: str,
) -> dict[str, Any]:
    """
    Only GET already discovered public URLs. No form submission, no guessed
    mutation endpoint, no credentials.
    """
    try:
        raw, final_url, ctype = http_bytes(url)
    except Exception as exc:
        return {
            "url": url,
            "ok": False,
            "error": str(exc),
        }

    prefix = raw[:300].decode("utf-8", errors="replace")
    return {
        "url": url,
        "ok": True,
        "final_url": final_url,
        "content_type": ctype,
        "bytes": len(raw),
        "prefix": " ".join(prefix.split())[:250],
    }


def self_test() -> None:
    sample = """
    <html>
      <form method="post" action="/db/export?OpenAgent">
        <input name="station" value="AGM_001">
        <select name="format"><option value="csv">CSV</option><option value="xls">Excel</option></select>
      </form>
      <a href="/data/export.csv">Download CSV</a>
      <script src="/js/station.js"></script>
      <iframe src="/chart?OpenForm"></iframe>
      <script>
        var x = "/Internet/AM/test.nsf/export?OpenAgent";
      </script>
    </html>
    """
    parser = PageParser()
    parser.feed(sample)

    assert len(parser.forms) == 1
    assert parser.forms[0]["action"] == "/db/export?OpenAgent"
    assert parser.forms[0]["inputs"][0]["name"] == "station"
    assert len(parser.links) == 1
    assert len(parser.scripts) == 1
    assert len(parser.iframes) == 1
    assert parser.iframes[0]["src"] == "/chart?OpenForm"
    assert parser.forms[0]["selects"][0]["options"][0]["value"] == "csv"

    strings = extract_strings(sample)
    assert any("OpenAgent" in x for x in strings)

    test_url = (
        "https://www.agrimeteo.lu/Internet/AM/NotesLUAM.nsf/"
        "luxweb/abc?OpenDocument"
    )
    tab = normalize_download_tab(test_url)
    assert "TableRow=3.9" in tab

    print("ASTA Luxembourg archive probe self-test OK")


def probe(station_limit: int) -> None:
    log("=== ASTA LUXEMBOURG HISTORICAL ARCHIVE / DOWNLOAD PROBE ===")
    log("Keine Anmeldung, keine Secrets; nur öffentliche GET-Abfragen.")

    dataset = inspect_url(
        DATASET_PAGE,
        label="data.public.lu ASTA station inventory",
        print_html_strings=False,
    )
    station_urls = station_links_from_dataset(
        dataset["text"],
        dataset["parser"],
    )

    log()
    log(f"Gefundene AgriMeteo-Stationsseiten: {len(station_urls)}")
    for url in station_urls[:50]:
        log(f"  {url}")

    if not station_urls:
        raise RuntimeError(
            "Keine AgriMeteo-Stationsseiten auf data.public.lu gefunden."
        )

    all_candidates: list[str] = []
    form_pages: list[dict[str, Any]] = []
    form_count = 0
    script_hit_count = 0
    iframe_count = 0

    selected = station_urls[:max(1, station_limit)]

    for index, station_url in enumerate(selected, 1):
        log()
        log("=" * 72)
        log(f"STATION {index}/{len(selected)}")
        log("=" * 72)

        base = inspect_url(
            station_url,
            label="Stations-Hauptseite",
        )

        download_url = normalize_download_tab(station_url)
        download = inspect_url(
            download_url,
            label="Download / Grafik Tab",
        )

        form_pages.append(download)
        form_count += len(download["parser"].forms)
        iframe_count += len(download["parser"].iframes)

        iframe_pages = inspect_iframe_tree(
            download,
            label_prefix=f"STATION {index} DOWNLOAD",
        )
        form_pages.extend(iframe_pages)
        form_count += sum(
            len(page["parser"].forms) for page in iframe_pages
        )

        for href, _ in download["relevant_links"]:
            if href not in all_candidates:
                all_candidates.append(href)

        for value in download["strings"]:
            absolute = urllib.parse.urljoin(
                download["final_url"],
                value,
            )
            if relevant(absolute) and absolute not in all_candidates:
                all_candidates.append(absolute)

        script_hits = inspect_external_scripts(
            download["final_url"],
            download["parser"].scripts,
        )
        script_hit_count += len(script_hits)

        for url in script_hits:
            if relevant(url) and url not in all_candidates:
                all_candidates.append(url)

        for iframe in download["parser"].iframes:
            absolute = urllib.parse.urljoin(
                download["final_url"],
                iframe["src"],
            )
            if absolute not in all_candidates:
                all_candidates.append(absolute)

        for page in iframe_pages:
            for href, _ in page["relevant_links"]:
                if href not in all_candidates:
                    all_candidates.append(href)
            for value in page["strings"]:
                absolute = urllib.parse.urljoin(
                    page["final_url"], value
                )
                if relevant(absolute) and absolute not in all_candidates:
                    all_candidates.append(absolute)

    compact_forms = print_compact_form_candidates(form_pages)

    log()
    log("=" * 72)
    log("=== ENTDECKTE DOWNLOAD-/EXPORT-KANDIDATEN ===")
    log("=" * 72)

    ranked = []
    for url in all_candidates:
        score = 0
        lower = url.lower()
        for word in (
            "download", "export", "csv", "xls", "txt",
            "openagent", "readviewentries", "webquerysaveagent"
        ):
            if word in lower:
                score += 10
        if ".nsf/" in lower:
            score += 3
        ranked.append((score, url))

    ranked.sort(key=lambda x: (-x[0], x[1]))

    for score, url in ranked[:120]:
        log(f"Score {score:>3}: {url}")

    log()
    log("=== SICHERE GET-PROBES DER BESTEN KANDIDATEN ===")
    probe_results = []

    for score, url in ranked[:12]:
        # Do not GET obvious JavaScript files twice and avoid mail/javascript.
        if url.lower().startswith(("javascript:", "mailto:")):
            continue
        result = safe_probe_candidate(url)
        probe_results.append(result)

        if result["ok"]:
            log(
                f"OK | {result['bytes']:,} Bytes | "
                f"{result['content_type']} | {result['final_url']}"
            )
            log(f"  Anfang: {result['prefix']}")
        else:
            log(f"FEHLER | {url} | {result['error']}")

    log()
    log("=" * 72)
    log("=== ASTA LUXEMBOURG ARCHIVE PROBE SUMMARY ===")
    log("=" * 72)
    log(f"Stationsseiten im Open-Data-Inventar: {len(station_urls)}")
    log(f"Untersuchte Stationen: {len(selected)}")
    log(f"Formulare inkl. Iframe-Seiten: {form_count}")
    log(f"Iframes auf Download-Tabs: {iframe_count}")
    log(f"Kompakte Form-/Export-Kandidaten: {len(compact_forms)}")
    log(f"Relevante JavaScript-Endpunkttreffer: {script_hit_count}")
    log(f"Download-/Export-Kandidaten: {len(ranked)}")
    log(f"Sichere GET-Probes: {len(probe_results)}")
    log()
    log(
        "Bitte insbesondere FORMULARE, JAVASCRIPT-TREFFER, "
        "ENTDECKTE DOWNLOAD-/EXPORT-KANDIDATEN und diesen Summary-Block "
        "zurückschicken."
    )
    log("ASTA Luxembourg archive probe OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--station-limit",
        type=int,
        default=STATION_LIMIT_DEFAULT,
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        probe(max(1, args.station_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
