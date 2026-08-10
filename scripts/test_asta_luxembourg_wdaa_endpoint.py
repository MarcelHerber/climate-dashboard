#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

PARENT_URL = (
    "https://www.agrimeteo.lu/Internet/AM/NotesLUAM.nsf/luxweb/"
    "9f28782629f791e9c12577510034daa2?OpenDocument=&TableRow=3.9"
)

RELEVANT = (
    "wdaa", "cgi-bin", "sendrqst", "send_data", "load_chart",
    "format", "ajax", "$.post", "$.get", "$.ajax", "xmlhttprequest"
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def compact(value: Any, limit: int = 5000) -> str:
    return " ".join(str(value or "").split())[:limit]


async def main() -> None:
    log("=== ASTA LUXEMBOURG WDAA ENDPOINT PROBE V3 ===")
    log("Ziel: Tageswerte (outformat=30) aktivieren und Backend-Endpunkt erfassen.")
    log("Es wird KEIN Datendownload gestartet.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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

        parent = await context.new_page()
        await parent.goto(PARENT_URL, wait_until="domcontentloaded", timeout=60000)
        await parent.wait_for_timeout(1200)

        iframe_url = await parent.evaluate(
            """() => {
              const f = [...document.querySelectorAll('iframe')]
                .find(x => (x.src || '').includes('wdaa_client.pl'));
              return f ? f.src : '';
            }"""
        )
        if not iframe_url:
            raise RuntimeError("WDAA-Iframe nicht gefunden.")

        log(f"WDAA-Client: {iframe_url}")

        page = await context.new_page()

        requests: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []

        def on_request(req):
            url = req.url
            low = url.lower()
            if "aspdienste.de" in low or "/cgi-bin/" in low or "wdaa" in low:
                requests.append(
                    {
                        "method": req.method,
                        "url": url,
                        "post_data": req.post_data or "",
                        "resource_type": req.resource_type,
                    }
                )

        def on_response(resp):
            url = resp.url
            low = url.lower()
            if "aspdienste.de" in low or "/cgi-bin/" in low or "wdaa" in low:
                responses.append(
                    {
                        "status": resp.status,
                        "url": url,
                        "content_type": resp.headers.get("content-type", ""),
                    }
                )

        page.on("request", on_request)
        page.on("response", on_response)

        resp = await page.goto(
            iframe_url,
            wait_until="domcontentloaded",
            timeout=60000,
            referer=PARENT_URL,
        )
        log(f"Initial HTTP: {resp.status if resp else 'n/a'}")
        await page.wait_for_timeout(2500)

        log()
        log("=== FORMULAR VOR FORMAT-AKTUALISIERUNG ===")
        snapshot_before = await page.evaluate(
            r"""() => ({
              inputs: [...document.querySelectorAll('input')].map(x => ({
                id:x.id||'', name:x.name||'', type:x.type||'',
                value:x.value||'', min:x.min||'', max:x.max||'',
                placeholder:x.placeholder||''
              })),
              selects: [...document.querySelectorAll('select')].map(s => ({
                id:s.id||'', name:s.name||'', value:s.value||'',
                options:[...s.options].map(o => ({
                  value:o.value, text:(o.textContent||'').trim(),
                  selected:o.selected
                }))
              }))
            })"""
        )

        for inp in snapshot_before["inputs"]:
            if inp["id"] or inp["name"]:
                log(
                    f"INPUT id={inp['id']!r} name={inp['name']!r} "
                    f"type={inp['type']!r} value={inp['value']!r} "
                    f"min={inp['min']!r} max={inp['max']!r} "
                    f"placeholder={inp['placeholder']!r}"
                )

        for sel in snapshot_before["selects"]:
            log(
                f"SELECT id={sel['id']!r} name={sel['name']!r} "
                f"value={sel['value']!r}"
            )
            for opt in sel["options"][:100]:
                log(
                    f"  OPTION value={opt['value']!r} "
                    f"selected={opt['selected']} text={opt['text']!r}"
                )

        log()
        log("=== JAVASCRIPT-FUNKTIONEN ===")
        fn_info = await page.evaluate(
            r"""() => {
              const names = [
                'sendRqst','checkAll','uncheckAll','showCharts'
              ];
              const out = {};
              for (const n of names) {
                try {
                  out[n] = typeof window[n] === 'function'
                    ? String(window[n])
                    : '(nicht vorhanden)';
                } catch(e) {
                  out[n] = String(e);
                }
              }
              return out;
            }"""
        )
        for name, source in fn_info.items():
            log(f"{name}: {compact(source, 12000)}")

        log()
        log("=== WDAA.JS RELEVANTE PASSAGEN ===")
        js_text = await page.evaluate(
            r"""async () => {
              const src = [...document.scripts]
                .map(s => s.src)
                .find(x => x && x.includes('/js/wdaasc/lib/wdaa.js'));
              if (!src) return {src:'', text:''};
              const r = await fetch(src, {credentials:'include'});
              return {src, text: await r.text()};
            }"""
        )
        log(f"JS: {js_text['src']}")
        text = js_text["text"]
        low = text.lower()

        hit_positions = []
        for token in RELEVANT:
            start = 0
            while True:
                pos = low.find(token.lower(), start)
                if pos < 0:
                    break
                hit_positions.append(pos)
                start = pos + len(token)

        shown = []
        for pos in sorted(set(hit_positions)):
            a = max(0, pos - 900)
            b = min(len(text), pos + 1800)
            snippet = text[a:b]
            key = compact(snippet, 3000)
            if key not in shown:
                shown.append(key)

        for i, snippet in enumerate(shown[:30], 1):
            log(f"JS-SNIPPET {i}: {snippet}")

        # Clear initial static asset traffic so only the format update remains.
        requests.clear()
        responses.clear()

        log()
        log("=== AKTION: outformat=30 (TAGESWERTE) + sendRqst('format') ===")

        result = await page.evaluate(
            r"""() => {
              const sel = document.getElementById('outformat');
              if (!sel) return {ok:false, error:'outformat fehlt'};
              const has30 = [...sel.options].some(o => o.value === '30');
              if (!has30) return {ok:false, error:'outformat 30 fehlt'};
              sel.value = '30';
              sel.dispatchEvent(new Event('change', {bubbles:true}));
              if (typeof sendRqst !== 'function')
                return {ok:false, error:'sendRqst fehlt'};
              sendRqst('format');
              return {ok:true, value:sel.value};
            }"""
        )
        log(f"Ausführung: {result}")

        await page.wait_for_timeout(5000)

        log()
        log("=== NETZWERK NACH sendRqst('format') ===")
        for req in requests:
            log(
                f"REQUEST {req['method']} | {req['resource_type']} | "
                f"{req['url']}"
            )
            if req["post_data"]:
                log(f"  POST-DATA: {req['post_data']}")

        for response in responses:
            log(
                f"RESPONSE HTTP {response['status']} | "
                f"{response['content_type']} | {response['url']}"
            )

        log()
        log("=== FORMULAR NACH FORMAT-AKTUALISIERUNG ===")
        snapshot_after = await page.evaluate(
            r"""() => ({
              body:(document.body?.innerText||'').replace(/\s+/g,' ').trim(),
              inputs:[...document.querySelectorAll('input')].map(x => ({
                id:x.id||'', name:x.name||'', type:x.type||'',
                value:x.value||'', min:x.min||'', max:x.max||'',
                placeholder:x.placeholder||''
              })),
              selects:[...document.querySelectorAll('select')].map(s => ({
                id:s.id||'', name:s.name||'', value:s.value||'',
                options:[...s.options].map(o => ({
                  value:o.value, text:(o.textContent||'').trim(),
                  selected:o.selected
                }))
              }))
            })"""
        )
        log(f"BODY: {compact(snapshot_after['body'], 2500)}")

        for inp in snapshot_after["inputs"]:
            if inp["id"] or inp["name"]:
                log(
                    f"INPUT id={inp['id']!r} name={inp['name']!r} "
                    f"type={inp['type']!r} value={inp['value']!r} "
                    f"min={inp['min']!r} max={inp['max']!r}"
                )

        for sel in snapshot_after["selects"]:
            log(
                f"SELECT id={sel['id']!r} name={sel['name']!r} "
                f"value={sel['value']!r} options={len(sel['options'])}"
            )
            for opt in sel["options"][:100]:
                log(
                    f"  OPTION value={opt['value']!r} "
                    f"selected={opt['selected']} text={opt['text']!r}"
                )

        log()
        log("=== ASTA WDAA ENDPOINT PROBE SUMMARY ===")
        parsed = urllib.parse.urlsplit(iframe_url)
        q = urllib.parse.parse_qs(parsed.query)
        log(f"cid={q.get('cid',[''])[0]} | sid={q.get('sid',[''])[0]}")
        log("Gewähltes Ausgabeformat: 30 = Tageswerte")
        log(f"Requests durch format-Aktion: {len(requests)}")
        for req in requests:
            log(f"  {req['method']} {req['url']}")
            if req["post_data"]:
                log(f"    DATA {req['post_data']}")
        log(
            "from="
            + next(
                (x["value"] for x in snapshot_after["inputs"] if x["id"] == "from"),
                ""
            )
            + " | to="
            + next(
                (x["value"] for x in snapshot_after["inputs"] if x["id"] == "to"),
                ""
            )
        )
        log("ASTA Luxembourg WDAA endpoint probe OK.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
