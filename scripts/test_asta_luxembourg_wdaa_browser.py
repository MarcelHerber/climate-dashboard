#!/usr/bin/env python3
"""
ASTA Luxembourg WDAA browser probe.

The ASTA station page embeds the real historical Download/Grafik client as:
  https://dlr-web-daten1.aspdienste.de/cgi-bin/wdaasc/wdaa_client.pl?cid=92&sid=...

Plain urllib GETs currently return an empty body on GitHub Actions.
This probe uses Chromium/Playwright to inspect the actual rendered WDAA app.

It does NOT submit any data request. It only reads:
- iframe URL / cid / sid
- response status
- rendered HTML size/title
- forms and their actions/methods
- inputs (id/name/type/value)
- selects and option values/text
- buttons / onclick
- links
- script URLs
- inline JS snippets mentioning download/export/cgi/date/from/to
- network URLs requested while the WDAA UI loads

No login, API key or secret is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import urllib.parse
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_PARENT = (
    "https://www.agrimeteo.lu/Internet/AM/NotesLUAM.nsf/luxweb/"
    "9f28782629f791e9c12577510034daa2?OpenDocument=&TableRow=3.9"
)

WDAA_RE = re.compile(
    r"https?://[^\"'<>\s]+/cgi-bin/wdaasc/wdaa_client\.pl\?[^\"'<>\s]+",
    flags=re.I,
)

RELEVANT_JS = (
    "download", "export", "csv", "xls", "txt", "cgi-bin",
    "wdaa", "from", "to", "date", "datum", "zeitraum",
    "submit", "sid", "tid"
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def compact(text: Any, limit: int = 1600) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def extract_wdaa_url(html: str) -> str | None:
    match = WDAA_RE.search(html)
    if not match:
        return None
    return match.group(0).replace("&amp;", "&")


async def js_snapshot(page) -> dict[str, Any]:
    return await page.evaluate(
        r"""
        () => {
          const forms = [...document.forms].map((f, fi) => ({
            index: fi,
            id: f.id || "",
            name: f.name || "",
            method: (f.method || "GET").toUpperCase(),
            action: f.action || "",
            enctype: f.enctype || "",
            onsubmit: f.getAttribute("onsubmit") || "",
            inputs: [...f.querySelectorAll("input")].map(x => ({
              id: x.id || "",
              name: x.name || "",
              type: x.type || "",
              value: x.value || "",
              checked: !!x.checked,
              onclick: x.getAttribute("onclick") || "",
              onchange: x.getAttribute("onchange") || ""
            })),
            selects: [...f.querySelectorAll("select")].map(s => ({
              id: s.id || "",
              name: s.name || "",
              value: s.value || "",
              multiple: !!s.multiple,
              onchange: s.getAttribute("onchange") || "",
              options: [...s.options].map(o => ({
                value: o.value,
                text: (o.textContent || "").trim(),
                selected: !!o.selected
              }))
            })),
            buttons: [...f.querySelectorAll("button,input[type=submit],input[type=button]")].map(b => ({
              tag: b.tagName,
              id: b.id || "",
              name: b.name || "",
              type: b.type || "",
              value: b.value || (b.textContent || "").trim(),
              onclick: b.getAttribute("onclick") || ""
            }))
          }));

          const links = [...document.querySelectorAll("a[href]")].map(a => ({
            text: (a.textContent || "").trim().replace(/\s+/g, " "),
            href: a.href,
            onclick: a.getAttribute("onclick") || ""
          }));

          const scripts = [...document.scripts].map(s => ({
            src: s.src || "",
            text: s.src ? "" : (s.textContent || "")
          }));

          return {
            title: document.title,
            href: location.href,
            htmlLength: document.documentElement.outerHTML.length,
            bodyText: (document.body?.innerText || "").replace(/\s+/g, " ").trim(),
            forms,
            links,
            scripts
          };
        }
        """
    )


def print_snapshot(snapshot: dict[str, Any]) -> None:
    log(f"Titel: {snapshot.get('title')!r}")
    log(f"URL: {snapshot.get('href')}")
    log(f"Gerendertes HTML: {snapshot.get('htmlLength', 0):,} Zeichen")
    log(f"Body-Anfang: {compact(snapshot.get('bodyText'), 1200)}")

    forms = snapshot.get("forms") or []
    log()
    log(f"FORMULARE IM WDAA-CLIENT: {len(forms)}")
    for form in forms:
        log(
            f"FORM {form['index']}: {form['method']} | "
            f"action={form['action']} | id={form['id']!r} "
            f"name={form['name']!r} onsubmit={form['onsubmit']!r}"
        )
        for inp in form.get("inputs", []):
            log(
                f"  INPUT id={inp['id']!r} name={inp['name']!r} "
                f"type={inp['type']!r} value={inp['value']!r} "
                f"onclick={inp['onclick']!r} onchange={inp['onchange']!r}"
            )
        for sel in form.get("selects", []):
            log(
                f"  SELECT id={sel['id']!r} name={sel['name']!r} "
                f"value={sel['value']!r} onchange={sel['onchange']!r} "
                f"options={len(sel.get('options', []))}"
            )
            for opt in sel.get("options", [])[:80]:
                log(
                    f"    OPTION value={opt['value']!r} "
                    f"selected={opt['selected']} text={opt['text']!r}"
                )
        for button in form.get("buttons", []):
            log(
                f"  BUTTON tag={button['tag']} id={button['id']!r} "
                f"name={button['name']!r} type={button['type']!r} "
                f"value={button['value']!r} onclick={button['onclick']!r}"
            )

    links = snapshot.get("links") or []
    rel_links = [
        x for x in links
        if any(
            token in (str(x.get("href", "")) + " " + str(x.get("text", ""))).lower()
            for token in ("download", "export", "csv", "xls", "txt", "cgi-bin", "wdaa")
        )
    ]
    log()
    log(f"RELEVANTE LINKS: {len(rel_links)}")
    for item in rel_links[:100]:
        log(f"  {item['text']!r} -> {item['href']} | onclick={item['onclick']!r}")

    scripts = snapshot.get("scripts") or []
    log()
    log(f"SCRIPTS: {len(scripts)}")
    for item in scripts:
        if item.get("src"):
            log(f"  SRC {item['src']}")
        else:
            text = str(item.get("text", ""))
            low = text.lower()
            if any(token in low for token in RELEVANT_JS):
                log(f"  INLINE {compact(text, 2500)}")


async def run(parent_url: str, wait_seconds: float) -> None:
    log("=== ASTA LUXEMBOURG WDAA BROWSER PROBE ===")
    log(f"Parent: {parent_url}")
    log("Chromium wird nur lesend verwendet; kein Formular wird abgeschickt.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Luxembourg",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            },
        )
        page = await context.new_page()

        network_urls: list[str] = []
        response_rows: list[tuple[int, str, str]] = []

        def on_request(req):
            url = req.url
            if (
                "aspdienste.de" in url
                or "/cgi-bin/" in url
                or "wdaa" in url.lower()
            ):
                network_urls.append(url)

        def on_response(resp):
            url = resp.url
            if (
                "aspdienste.de" in url
                or "/cgi-bin/" in url
                or "wdaa" in url.lower()
            ):
                ctype = resp.headers.get("content-type", "")
                response_rows.append((resp.status, ctype, url))

        page.on("request", on_request)
        page.on("response", on_response)

        log()
        log("1) Lade ASTA-Parentseite …")
        try:
            parent_resp = await page.goto(
                parent_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except PlaywrightTimeoutError:
            parent_resp = None
            log("WARNUNG: Parentseite Timeout, DOM wird trotzdem untersucht.")

        if parent_resp:
            log(f"Parent HTTP: {parent_resp.status}")

        await page.wait_for_timeout(1500)
        parent_html = await page.content()

        wdaa_url = extract_wdaa_url(parent_html)
        if not wdaa_url:
            frames = page.frames
            for frame in frames:
                if "wdaa_client.pl" in frame.url:
                    wdaa_url = frame.url
                    break

        if not wdaa_url:
            raise RuntimeError(
                "Kein wdaa_client.pl-Iframe auf der ASTA-Downloadseite gefunden."
            )

        log(f"WDAA-Iframe erkannt: {wdaa_url}")

        log()
        log("2) Lade WDAA-Client direkt im selben Browser-Kontext …")
        direct = await context.new_page()
        direct.on("request", on_request)
        direct.on("response", on_response)

        try:
            resp = await direct.goto(
                wdaa_url,
                wait_until="domcontentloaded",
                timeout=60000,
                referer=parent_url,
            )
            log(f"WDAA HTTP: {resp.status if resp else 'kein Response-Objekt'}")
            if resp:
                log(f"WDAA Content-Type: {resp.headers.get('content-type', '')}")
        except PlaywrightTimeoutError:
            log("WARNUNG: WDAA Navigation Timeout; prüfe vorhandenen DOM.")

        await direct.wait_for_timeout(int(wait_seconds * 1000))
        snapshot = await js_snapshot(direct)
        print_snapshot(snapshot)

        log()
        log("=== WDAA NETWORK ===")
        seen = set()
        for status, ctype, url in response_rows:
            key = (status, url)
            if key in seen:
                continue
            seen.add(key)
            log(f"HTTP {status} | {ctype} | {url}")

        log()
        log("=== WDAA REQUEST URLS ===")
        for url in list(dict.fromkeys(network_urls))[:200]:
            log(f"  {url}")

        log()
        log("=== ASTA WDAA PROBE SUMMARY ===")
        parsed = urllib.parse.urlsplit(wdaa_url)
        q = urllib.parse.parse_qs(parsed.query)
        log(f"Client: {parsed.scheme}://{parsed.netloc}{parsed.path}")
        log(f"cid={q.get('cid', [''])[0]} | sid={q.get('sid', [''])[0]}")
        log(f"Gerendertes HTML: {snapshot.get('htmlLength', 0):,}")
        log(f"Formulare: {len(snapshot.get('forms') or [])}")
        log(
            "Input-IDs: "
            + ", ".join(
                sorted(
                    {
                        str(inp.get("id") or inp.get("name") or "")
                        for form in snapshot.get("forms") or []
                        for inp in form.get("inputs") or []
                        if (inp.get("id") or inp.get("name"))
                    }
                )
            )
        )
        log(
            "Select-IDs: "
            + ", ".join(
                sorted(
                    {
                        str(sel.get("id") or sel.get("name") or "")
                        for form in snapshot.get("forms") or []
                        for sel in form.get("selects") or []
                        if (sel.get("id") or sel.get("name"))
                    }
                )
            )
        )
        log(f"Relevante Netzwerkantworten: {len(seen)}")

        if int(snapshot.get("htmlLength") or 0) < 300:
            raise RuntimeError(
                "WDAA liefert auch in Chromium praktisch keinen DOM. "
                "Dann müssen wir den Backend-Endpunkt aus Netzwerk/JS ableiten."
            )

        log("ASTA Luxembourg WDAA browser probe OK.")
        await browser.close()


def self_test() -> None:
    sample = (
        '<iframe src="https://dlr-web-daten1.aspdienste.de/'
        'cgi-bin/wdaasc/wdaa_client.pl?cid=92&amp;sid=22"></iframe>'
    )
    url = extract_wdaa_url(sample)
    assert url is not None
    assert "cid=92&sid=22" in url
    print("ASTA Luxembourg WDAA browser probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--parent-url", default=DEFAULT_PARENT)
    parser.add_argument("--wait-seconds", type=float, default=6.0)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    asyncio.run(run(args.parent_url, args.wait_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
