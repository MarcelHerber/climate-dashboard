#!/usr/bin/env python3
"""Live DWD MOSMIX-L: download every station chart as PNG/PDF/SVG (phone + desktop).

This is a genuine browser acceptance test against the published GitHub Pages site.
No mocked/blocked/replayed network responses and no synthetic Chart.js datasets.
Each context makes at most nine downloads to avoid Chromium auto-download throttling.
"""
from __future__ import annotations

import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE = "https://marcelherber.github.io/climate-dashboard/"
OUT = Path("mosmix_live_dwd_export_audit")
OUT.mkdir(exist_ok=True)
CHARTS = ("temp", "rain", "wind", "pressure", "sun", "sunDaily")
FORMATS = ("png", "pdf", "svg")
SIZES = (390, 1200)
RESULTS = []


def check_file(path: Path, kind: str) -> dict:
    blob = path.read_bytes()
    assert len(blob) > 1500, f"Empty {kind.upper()} export: {path}"
    if kind == "png":
        assert blob[:8] == b"\x89PNG\r\n\x1a\n", "PNG signature missing"
        w, h = struct.unpack(">II", blob[16:24])
        assert w >= 1500 and h >= 200, f"PNG is not high-resolution: {w}x{h}"
        return {"bytes": len(blob), "width": w, "height": h}
    if kind == "pdf":
        assert blob.startswith(b"%PDF"), "PDF signature missing"
        pdf = PdfReader(path)
        assert len(pdf.pages) == 1, "Expected a single-chart PDF page"
        page = pdf.pages[0]
        resources = page.get("/Resources")
        xobjects = resources.get_object().get("/XObject") if resources else None
        if xobjects:
            assert not any(item.get_object().get("/Subtype") == "/Image"
                           for item in xobjects.get_object().values()), "Raster bitmap found in vector PDF"
        stream = page.get_contents().get_data()
        assert b" m" in stream and b" l" in stream, "No editable PDF vector paths"
        return {"bytes": len(blob), "pages": 1, "raster_images": False}
    assert kind == "svg"
    root = ET.fromstring(blob)
    ns = "{http://www.w3.org/2000/svg}"
    ink = "{http://www.inkscape.org/namespaces/inkscape}"
    layers = [n.attrib.get(ink + "label", "") for n in root.iter(ns + "g")
              if n.attrib.get(ink + "groupmode") == "layer"]
    assert layers, "Missing named SVG series groups"
    assert not list(root.iter(ns + "image")), "Raster image found in SVG"
    elements = sum(1 for n in root.iter()
                   if n.tag in {ns + "path", ns + "rect", ns + "polygon", ns + "circle"})
    assert elements >= 3, "No editable series objects"
    return {"bytes": len(blob), "layers": len(layers), "objects": elements}


def check_issued(detail: dict) -> tuple[str, float]:
    issue = detail.get("issue_time")
    assert isinstance(issue, str), "DWD station response has no MOSMIX run timestamp"
    stamp = datetime.fromisoformat(issue.replace("Z", "+00:00"))
    hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    assert -3 <= hours <= 72, f"MOSMIX station run is stale or future-dated: {issue} ({hours:.1f}h)"
    assert detail.get("parameters", {}).get("TTT"), "Missing original DWD temperature series"
    return issue, round(hours, 1)


def chart_values(page) -> dict:
    return page.evaluate("""() => {
      const ids = ['mosmixTempChart','mosmixRainChart','mosmixWindChart',
                   'mosmixPressureChart','mosmixSunChart','mosmixSunDailyChart'];
      return Object.fromEntries(ids.map(id=>{
        const chart=window.Chart?.getChart?.(document.getElementById(id));
        const data=chart?.data?.datasets||[];
        const good=data.reduce((sum,ds,i)=>sum+
          (chart.isDatasetVisible(i)?(ds.data||[]).filter(v=>
            typeof v==='number'&&Number.isFinite(v)||
            v&&typeof v==='object'&&Number.isFinite(v.y)).length:0),0);
        return [id,{datasets:data.length,finite_values:good,
          labels:chart?.data?.labels?.length||0,
          x_min:chart?.scales?.x?.min,x_max:chart?.scales?.x?.max}];
      }));
    }""")


def audit_batch(browser, width: int, keys: tuple[str, ...], batch_no: int) -> dict:
    ctx = browser.new_context(viewport={"width":width, "height":860 if width < 600 else 900},
                              is_mobile=width < 600, has_touch=width < 600,
                              accept_downloads=True, device_scale_factor=1,
                              ignore_https_errors=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)[:300]))
    page.on("dialog", lambda dialog: (errors.append("dialog: " + dialog.message), dialog.dismiss()))
    entry = {"width": width, "batch": batch_no, "keys": list(keys),
             "source": "published DWD MOSMIX-L, no mocks", "ok": False, "downloads": []}
    try:
        page.goto(BASE + "mosmix.html?dwd-vector-audit=" + str(time.time()),
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("""() => document.querySelector('#mosmixMap.leaflet-container') ||
          /konnte nicht gestartet|Fehler:/i.test(document.querySelector('#mosmixSectionStatus')?.textContent||'')""",
          timeout=110000)
        assert page.locator("#mosmixMap.leaflet-container").count(), "Published DWD MOSMIX map not loaded"
        page.locator("#mosmixStationSearch").fill("Frankfurt")
        with page.expect_response(lambda response:
                "/mosmix/stations/" in response.url and response.url.endswith(".json") or
                "/mosmix/stations/" in response.url and ".json?v=" in response.url,
                timeout=70000) as response_info:
            page.locator("#mosmixStationButton").click()
        response = response_info.value
        assert response.status == 200, f"Original DWD station file HTTP {response.status}"
        station_data = response.json()
        issue, lag = check_issued(station_data)
        entry["original_station_url"] = response.url.split("?", 1)[0]
        entry["dwd_issue_utc"] = issue
        entry["data_age_hours"] = lag
        page.wait_for_function("""() => {
          const b=document.querySelector('#mosmixDiagramPdf');
          const status=document.querySelector('#mosmixMeteogramStatus')?.textContent||'';
          return !b?.disabled || /konnte nicht geladen|Keine passende|verschiedenen MOSMIX/i.test(status);
        }""", timeout=110000)
        station_status = page.locator("#mosmixMeteogramStatus").inner_text().strip()
        assert "MOSMIX-ID" in station_status, "Station render failed: " + station_status
        entry["station"] = station_status
        chart_info = chart_values(page)
        assert len(chart_info) == 6
        for key, info in zip(CHARTS, chart_info.values()):
            assert info["datasets"] >= 1 and info["labels"] >= 3, f"Missing {key} original chart: {info}"
            assert info["finite_values"] >= 1, f"No actual DWD forecast values for {key}: {info}"
        entry["actual_chart_samples"] = chart_info
        geometry = page.evaluate("""() => ({
          viewport:document.documentElement.clientWidth,
          scroll:document.documentElement.scrollWidth,
          buttonOverflow:[...document.querySelectorAll('[data-mosmix-export-chart]')].filter(el=>{
            const r=el.getBoundingClientRect();return r.left<-2||r.right>innerWidth+2;
          }).length
        })""")
        assert geometry["scroll"] <= geometry["viewport"] + 2, f"Horizontal scroll: {geometry}"
        assert geometry["buttonOverflow"] == 0, f"Clipped chart export controls: {geometry}"
        entry["layout"] = geometry

        for key in keys:
            for fmt in FORMATS:
                selector = f'[data-mosmix-export-chart="{key}"][data-mosmix-export-format="{fmt}"]'
                button = page.locator(selector)
                assert button.count() == 1, f"Missing single-chart button {selector}"
                assert button.is_enabled(), f"Chart button disabled: {selector}"
                before = chart_values(page)
                with page.expect_download(timeout=65000) as downloaded:
                    button.click(timeout=25000)
                file = OUT / f"{width}_{batch_no}_{key}.{fmt}"
                downloaded.value.save_as(str(file))
                assert downloaded.value.suggested_filename.endswith("_" + key + "." + fmt)
                entry["downloads"].append({"chart": key, "format": fmt, **check_file(file, fmt)})
                after = chart_values(page)
                assert before == after, f"{key} {fmt} altered live DWD forecast data"
                export_status = page.locator("#mosmixExportStatus").inner_text()
                assert "Download fehlgeschlagen" not in export_status, export_status
                print("MOSMIX REAL DWD EXPORT", width, key, fmt, file.stat().st_size, flush=True)
        assert not [msg for msg in errors if msg.startswith("dialog:")], errors
        page.screenshot(path=str(OUT / f"{width}_{batch_no}.png"), full_page=False,
                        timeout=20000)
        entry["ok"] = True
    except Exception as exc:
        entry["error"] = str(exc)[:1400]
        try:
            entry["last_status"] = {
              "forecast": page.locator("#mosmixSectionStatus").inner_text(timeout=2500),
              "station": page.locator("#mosmixMeteogramStatus").inner_text(timeout=2500),
              "export": page.locator("#mosmixExportStatus").inner_text(timeout=2500)
            }
        except Exception: pass
        try: page.screenshot(path=str(OUT / f"FAILED_{width}_{batch_no}.png"), timeout=15000)
        except Exception: pass
    entry["page_errors"] = errors[-8:]
    print("MOSMIX REAL DWD RESULT", json.dumps(entry, ensure_ascii=False), flush=True)
    ctx.close()
    return entry


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            for width in SIZES:
                for batch_no, keys in enumerate((CHARTS[:3], CHARTS[3:]), 1):
                    RESULTS.append(audit_batch(browser, width, keys, batch_no))
        finally:
            browser.close()
    (OUT / "report.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(r["ok"] for r in RESULTS), "At least one genuine DWD MOSMIX-L mobile/desktop export failed"
    assert sum(len(r["downloads"]) for r in RESULTS) == 36, "Not all 36 files were verified"


if __name__ == "__main__":
    main()
