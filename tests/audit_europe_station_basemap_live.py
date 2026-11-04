#!/usr/bin/env python3
"""Live map smoke test: original station records + offline background fallback.

Chromium simulated viewport only, not a physical iPhone/Android. All other
meteorological data and application JS are loaded unchanged from GitHub Pages.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright

URL="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("europe_station_map_audit")
OUT.mkdir(parents=True,exist_ok=True)
results=[]

def run_case(browser,width,block_tiles):
    context=browser.new_context(
        viewport={"width":width,"height":812},is_mobile=width<500,
        has_touch=width<500,device_scale_factor=1,
        reduced_motion="reduce")
    page=context.new_page()
    failed=[]
    carto_requests=[]
    page.on("pageerror",lambda e:failed.append(str(e)[:280]))
    page.on("request",lambda req:carto_requests.append(req.url) if "cartocdn.com" in req.url else None)
    if block_tiles:
        page.route(re.compile(r"^https://(?:[abcd]\.)?basemaps\.cartocdn\.com/|^https://tile\.openstreetmap\.org/"),
                   lambda route:route.abort())
    record={"width":width,"block_external_tiles":block_tiles}
    try:
        page.goto(URL+"index.html",wait_until="domcontentloaded",timeout=60000)
        page.wait_for_function("""() =>
           typeof window.attachEuropeStationBasemap==="function" &&
           typeof window.ensureEuropeStationLeaflet==="function" """,timeout=30000)
        page.evaluate("() => switchTab('europeStations')")
        page.wait_for_function("""() => {
          const m=document.getElementById('europeStationMap');
          return m?.classList.contains('leaflet-container') &&
            typeof europeStationMap!=='undefined' && europeStationMap?.__europeStationGetBasemapState?.();
        }""",timeout=45000)
        page.wait_for_function("""() =>
          typeof europeStationMap!=='undefined' &&
          europeStationMap?.__europeStationGetBasemapState?.().geographyLoaded === true
        """,timeout=22000)
        page.wait_for_timeout(1200)
        state=page.evaluate("""() => {
          const map=document.getElementById('europeStationMap'),
                m=europeStationMap,
                vector=m?.__europeStationGeographyLayer,
                s=m?.__europeStationGetBasemapState?.();
          return {
            state:s,
            leafletVisible:!!map && map.getBoundingClientRect().width>100,
            vectorSvgPaths:m.getPane('europeStationGeographyPane')?.querySelectorAll('svg path').length||0,
            vectorSvgCount:m.getPane('europeStationGeographyPane')?.querySelectorAll('svg').length||0,
            vectorCanvasCount:m.getPane('europeStationGeographyPane')?.querySelectorAll('canvas').length||0,
            vectorCountryCount:vector?.getLayers?.().length||0,
            actualGeographyPaneClass:m.getPane('europeStationGeographyPane')?.className,
            vectorPaneZIndex:Number(m.getPane('europeStationGeographyPane')?.style.zIndex||0),
            vectorFillOpacity:vector?.getLayers?.()[0]?.options?.fillOpacity,
            stationMarkers:europeStationMarkerById.size,
            shownLabel:document.getElementById('europeStationShown')?.textContent,
            tileImages:map?.querySelectorAll('img.leaflet-tile')?.length||0,
            loadedTiles:map?.querySelectorAll('img.leaflet-tile-loaded')?.length||0,
            status:document.getElementById('europeStationBasemapStatus')?.textContent,
            mapWidth:map?.getBoundingClientRect().width
          };
        }""")
        record.update(state)
        assert state["leafletVisible"],"Leaflet map has zero dimensions"
        assert state["vectorSvgPaths"]>=10,"Natural Earth fallback outlines missing"
        assert 200<state["vectorPaneZIndex"]<400,"Local borders hidden behind raster image tilePane"
        assert not carto_requests,"CARTO API-key-required raster images were still requested"
        assert state["stationMarkers"]>0,"Original station record markers missing"
        if block_tiles:
            assert state["loadedTiles"]==0,"External tiles unexpectedly loaded during offline test"
        name=f"europa_stations_{width}px_"+("offline" if block_tiles else "online")+".png"
        page.locator("#europeStationMap").screenshot(path=str(OUT/name),
            timeout=15000,animations="disabled")
        record["screenshot"]=name
        record["ok"]=True
    except Exception as e:
        record["ok"]=False
        record["error"]=str(e)[:650]
        try:
            page.screenshot(path=str(OUT/f"FAILED_europa_stations_{width}_{int(block_tiles)}.png"),
                           full_page=False,timeout=12000)
        except Exception:pass
    record["carto_requests"]=carto_requests[:8]
    record["js_errors"]=failed[-8:]
    results.append(record)
    page.close()
    context.close()

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    try:
        for width in (390,1200):
            run_case(browser,width,False)
            run_case(browser,width,True)
    finally:
        browser.close()

data={"tested":"actual public GitHub Pages station records and local countries asset",
      "cases":results,"passed":sum(x["ok"] for x in results),"total":len(results)}
(OUT/"report.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
lines=["# Europa-Stationsrekorde: Hintergrundkarte","",
       "Der Browser lädt die echte Website und Stationsdaten. Im Offline-Fall werden nur externe Rasterkarten gekappt;",
       "die lokal veröffentlichte Natural-Earth-Geometrie und alle Stationsmarker müssen weiter sichtbar sein.","",
       "| Ansicht | Ergebnis | Stationen | Länder-Umrisspfade | Geladene Kacheln |",
       "|---|---|---:|---:|---:|"]
for r in results:
    lines.append(f"| {r['width']}px, {'ohne Kachelserver' if r['block_external_tiles'] else 'normal'} | "
                 f"{'OK' if r['ok'] else 'FEHLER'} | {r.get('stationMarkers','–')} | "
                 f"{r.get('vectorSvgPaths','–')} | {r.get('loadedTiles','–')} |")
lines+=["",f"**{data['passed']}/{data['total']} bestanden.**",
        "Screenshots und vollständige Browsermesswerte liegen im Artefakt."]
(OUT/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
print((OUT/"README.md").read_text(encoding="utf-8"),flush=True)
for r in results:
    if not r["ok"]:print("DIAGNOSTIK:",json.dumps(r,ensure_ascii=False)[:1300],flush=True)
sys.exit(0 if data["passed"]==data["total"] else 1)
