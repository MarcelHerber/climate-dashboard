#!/usr/bin/env python3
"""Live desktop/mobile QA for NAO/AO forecasts and vector/bitmap exports.

Uses the deployed GitHub Pages URL and the actual NOAA/CPC data published there.
Requires playwright + Chromium on the GitHub Actions runner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

DEFAULT_URL = "https://marcelherber.github.io/climate-dashboard/zirkulation.html"


def run(page, output: Path, label: str) -> None:
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    response = page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=90000)
    assert response and response.status == 200, f"Page HTTP {response.status if response else 'none'}"
    expect(page.locator("#naoAoForecast")).to_be_visible()
    expect(page.locator("#teleChart")).to_be_visible()

    # A real live CPC dataset must have arrived and created a Chart.js chart.
    page.wait_for_function("""() => {
      const chart=window.Chart?.getChart(document.getElementById('teleChart'));
      return chart?.data.datasets.length >= 33 && !document.querySelector('#telePNG').disabled;
    }""", timeout=45000)
    assert "Prognose nicht verfügbar" not in page.locator("#teleStatus").inner_text()
    canvas = page.locator("#teleChart")
    assert canvas.bounding_box()["width"] >= (225 if page.viewport_size["width"] <= 360 else 275)

    def chart_state():
        return page.evaluate("""() => {
          const c=Chart.getChart(document.getElementById('teleChart'));
          return {n:c?.data.datasets.length, labels:c?.data.labels.length,
            title:document.getElementById('teleStatus').textContent};
        }""")

    state=chart_state()
    assert state["n"] >= 33, state
    assert state["labels"] >= 15, state

    page.locator("#teleIndex").select_option("ao")
    assert "AO ·" in page.locator("#teleStatus").inner_text()
    page.locator("#teleView").select_option("probability")
    assert chart_state()["n"] == 4
    page.locator("#teleDays").select_option("7")
    assert chart_state()["labels"] == 8
    page.locator("#teleView").select_option("models")
    assert chart_state()["n"] >= 2
    page.locator("#teleView").select_option("runs")
    assert chart_state()["n"] >= 5
    page.locator("#teleView").select_option("ensemble")
    page.locator("#teleDays").select_option("15")
    page.locator("#teleMembers").uncheck()
    assert chart_state()["n"] < 10
    page.locator("#teleMembers").check()
    assert chart_state()["n"] >= 33

    # Inspect all three downloads: they should be generated and contain real content.
    for btn, suffix, header in (
        ("#teleCSV", ".csv", b"Datum;"), ("#telePDF", ".pdf", b"%PDF-"), ("#telePNG", ".png", b"\\x89PNG"),
    ):
        with page.expect_download(timeout=30000) as info:
            page.locator(btn).click()
        item=info.value
        assert item.suggested_filename.endswith(suffix), item.suggested_filename
        path=output / f"{label}_{suffix[1:]}"
        item.save_as(path)
        data=path.read_bytes()
        if suffix==".csv":
            assert b"GEFS-Mitglied" in data and len(data)>2000, (item.suggested_filename,len(data))
        elif suffix==".pdf":
            assert data.startswith(header) and len(data)>2000, len(data)
            # PDF should contain path commands rather than only one raster screenshot.
            assert b" m " in data or b" l " in data or b"\nm\n" in data or len(data)>7000
        else:
            assert data.startswith(bytes.fromhex("89504e470d0a1a0a")) and len(data)>4000, len(data)

    # Verify spatial fields originate from the deployed, verified ECMWF manifest.
    page.wait_for_function("""() => {
      const im=document.querySelector('#teleMapImage');
      const status=document.querySelector('#teleMapStatus').textContent;
      return !im.hidden && im.complete && im.naturalWidth >= 900 &&
             status.includes("ECMWF IFS-ENS");
    }""", timeout=45000)
    for level in ("500","1000"):
        page.locator("#teleMapLevel").select_option(level)
        for lead in ("72","144","240"):
            page.locator("#teleMapLead").select_option(lead)
            page.wait_for_function("""() => {
              const im=document.querySelector('#teleMapImage');
              return !im.hidden && im.complete && im.naturalWidth>=900;
            }""",timeout=30000)
            source=page.locator("#teleMapImage").get_attribute("src")
            assert f"{level}hpa_f{int(lead):03d}.png" in source, source
    assert "Keine Anomalie, kein CPC-NAO/AO-Index" in page.locator("#teleMapInfo").inner_text()
    with page.expect_download(timeout=30000) as map_download:
        page.locator("#teleMapDownload").click()
    map_file=output/f"{label}_ecmwf_map.png"
    map_download.value.save_as(map_file)
    assert map_file.read_bytes().startswith(bytes.fromhex("89504e470d0a1a0a"))
    assert map_file.stat().st_size>50000

    page.screenshot(path=str(output/f"{label}.png"),full_page=True,animations="disabled")
    metrics=page.evaluate("""() => ({
      screen:window.innerWidth, body:document.documentElement.scrollWidth,
      panel:document.querySelector('#naoAoForecast').getBoundingClientRect().width,
      plot:document.querySelector('#teleChart').getBoundingClientRect().width
    })""")
    # Verify chart does not cause horizontal mobile overflow.
    assert metrics["plot"] <= metrics["panel"]+1, metrics
    if metrics["body"] > metrics["screen"]+4:
        offenders=page.evaluate("""() => [...document.querySelectorAll("body *")].map(el=>({
          node:el.tagName, id:el.id, className:String(el.className).slice(0,80),
          text:(el.textContent||"").slice(0,60),
          left:Math.round(el.getBoundingClientRect().left),right:Math.round(el.getBoundingClientRect().right),
          width:Math.round(el.getBoundingClientRect().width)
        })).filter(x=>x.right>window.innerWidth+3 || x.left< -3).sort((a,b)=>b.right-a.right).slice(0,25)""")
        print("MOBILE_OVERFLOW",json.dumps(offenders,ensure_ascii=False),flush=True)
    assert metrics["body"] <= metrics["screen"]+4, metrics
    assert not errors, errors[:5]
    print(json.dumps({"viewport":label,"chart":state,"metrics":metrics,"downloads":True}))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("/tmp/nao_ao_qa"))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        try:
            for label,size in (
                ("desktop",{"width":1440,"height":900}),
                ("mobile320",{"width":320,"height":740}),
                ("mobile360",{"width":360,"height":780}),
                ("mobile390",{"width":390,"height":844}),
                ("mobile430",{"width":430,"height":932}),
            ):
                page=browser.new_page(viewport=size,accept_downloads=True,device_scale_factor=1)
                try:run(page,args.output,label)
                finally:page.close()
        finally:browser.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
