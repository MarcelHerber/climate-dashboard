#!/usr/bin/env python3
"""External browser check of *deployed* MTG satellite UI and temporal overlays.

Unlike scripts/test_satellite_ui_browser.py this does not run a local server,
mock WMS capabilities or replace source images. Provider failures are captured.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright

URL = "https://marcelherber.github.io/climate-dashboard/satelliten.html"
ROOT = Path("_satellite_quality_evidence")
ROOT.mkdir(exist_ok=True)
UTC = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC")
PRODUCTS = ("geocolour", "ir105", "cloudtype")


def selected_picture(page, choice):
    page.locator("#satProduct").select_option(choice)
    code = {"geocolour":"mtg_fd:rgb_geocolour",
            "ir105":"mtg_fd:ir105_hrfi",
            "cloudtype":"mtg_fd:rgb_cloudtype"}[choice]
    try:
        page.wait_for_function("""(layer)=>{
          const img=document.querySelector('#satImage');
          if(!img?.src?.startsWith('https://view.eumetsat.int/geoserver/wms'))return false;
          const url=new URL(img.src);
          return url.searchParams.get('layers')===layer&&img.complete&&img.naturalWidth>0;
        }""",arg=code,timeout=28000)
        img=page.locator("#satImage").evaluate("""(image)=>{
          const u=new URL(image.src);
          return {width:image.naturalWidth,height:image.naturalHeight,
            layer:u.searchParams.get('layers'),time:u.searchParams.get('time'),
            bbox:u.searchParams.get('bbox'),image_complete:image.complete};
        }""")
        return {"ok":True,**img,
                "image_info":page.locator("#satImageInfo").inner_text(),
                "status":page.locator("#satStatus").inner_text()[:250]}
    except Exception as exc:
        return {"ok":False,"error":str(exc)[:260],
                "status":page.locator("#satStatus").inner_text()[:260],
                "valid_label":page.locator("#satValid").inner_text()[:120]}


def finished_overlay(page, name, timeout=20000):
    if name=="radar":
        toggle="#satShowRadar";text="#satRadarStatus";layer="#satRadarOverlay"
    else:
        toggle="#satShowLightning";text="#satLightningStatus";layer="#satLightningOverlay"
    page.locator(toggle).check()
    try:
        page.wait_for_function("""(selector)=>{
          const msg=document.querySelector(selector)?.textContent||'';
          return !/Prüfe|Wird geladen|Lade /i.test(msg)&&msg.length>8;
        }""",text,timeout=timeout)
    except Exception:
        pass
    message=page.locator(text).inner_text()
    visible=not page.locator(layer).is_hidden()
    return {"displayed":visible, "status":message[:350],
            "status_has_utc":bool(UTC.search(message))}


def temporal_assertion(kind, info, satellite_utc):
    """A displayed radar or LI overlay must not claim a future timestamp."""
    stamp=datetime.fromisoformat(satellite_utc.replace("Z","+00:00"))
    dates=[datetime.strptime(value,"%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
           for value in UTC.findall(info.get("status",""))]
    if not info.get("displayed"):
        return "not displayed; source/UTC compatibility explicitly reported"
    if not dates:
        return "ERROR: visible source with no UTC in overlay status"
    if kind=="radar":
        delay=(stamp-dates[0]).total_seconds()/60
        return "OK" if 0<=delay<=20 else f"ERROR: radar time difference {delay:.1f} min"
    if len(dates)<2:
        return "ERROR: LI interval start and end missing"
    gap=(stamp-dates[-1]).total_seconds()/60
    duration=(dates[-1]-dates[0]).total_seconds()/60
    return "OK" if 0<=gap<=10 and duration in (5,15,30) else \
           f"ERROR: LI end-time lag {gap:.1f} min or invalid accumulation length {duration:.1f}"


def snapshot(page, viewport):
    result={"viewport":viewport, "at":datetime.now(timezone.utc).isoformat()}
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:250]))
    page.goto(URL,wait_until="domcontentloaded",timeout=35000)
    try:
        page.wait_for_function("""()=>{
          return document.querySelector('#satTime')?.options.length>1 ||
            (document.querySelector('#satStatus')?.dataset.kind==='error');
        }""",timeout=35000)
    except Exception as err:
        result["time_list_error"]=str(err)[:220]
    result["controls_present"]=all(page.locator("#"+i).count()==1 for i in (
       "satSource","satProduct","satRegion","satTime","satImage",
       "satShowLightning","satShowRadar","satCompareGrid"))
    if not result["controls_present"]:
        raise AssertionError("Published MTG controls are missing.")
    result["timeline_count"]=page.locator("#satTime option").count()
    result["time_label"]=page.locator("#satValid").inner_text()
    result["sat_status"]=page.locator("#satStatus").inner_text()[:300]
    result["manifest"]=page.evaluate("""async()=> {
       try {
          const response=await fetch('./data/satellite_wms_times.json',{cache:'no-store'});
          if(!response.ok)return {error:'HTTP '+response.status};
          const data=await response.json();
          return {generated_at:data.generated_at,capabilities_ok:data.capabilities_ok,
            products:Object.fromEntries(Object.entries(data.products||{}).map(([k,v])=>
             [k,{map_ok:v.map_ok,latest_verified_time:v.latest_verified_time}]))};
       } catch(e){return {error:String(e)}}
    }""")
    result["images"]={}
    for product in PRODUCTS:
        picked=selected_picture(page,product)
        latest=result["manifest"].get("products",{}).get(product,{}).get("latest_verified_time")
        picked["matches_published_verified_utc"]=bool(picked.get("ok") and
             picked.get("time")==latest)
        result["images"][product]=picked
    # Source-specific overlays should be temporally coherent with the
    # chosen actual satellite image, not with a default/guessed time.
    page.locator("#satProduct").select_option("geocolour")
    sample=selected_picture(page,"geocolour")
    result["overlay_reference"]=sample
    result["overlay_checks"]={}
    if sample.get("ok"):
        result["overlay_checks"]["li"]=finished_overlay(page,"li",timeout=18000)
        result["overlay_checks"]["radar"]=finished_overlay(page,"radar",timeout=23000)
        for key,check in result["overlay_checks"].items():
            if check["displayed"] and not check["status_has_utc"]:
                check["warning"]="Layer is visible, but status lacks a verifiable UTC stamp."
            check["temporal_consistency"]=temporal_assertion(key,check,sample["time"])
    else:
        result["overlay_checks"]["warning"]="No confirmed GeoColour image: overlays not asserted."
    result["compare_opt_in"]=page.locator("#satCompareRun").count()==1
    result["mobile_overflow"]=page.evaluate("document.documentElement.scrollWidth>innerWidth+4")
    result["javascript_errors"]=errors
    page.screenshot(path=str(ROOT/(viewport+"-published-mtg.png")),full_page=True,
                    timeout=12000)
    return result


def main():
    results={"checked_at":datetime.now(timezone.utc).isoformat(),
             "url":URL, "tests":{}}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        for key,window in [("desktop",{"width":1440,"height":900}),
                           ("mobile",{"width":390,"height":844})]:
            context=browser.new_context(viewport=window,
                                        device_scale_factor=1,
                                        is_mobile=(key=="mobile"),
                                        has_touch=(key=="mobile"))
            page=context.new_page()
            try:
                results["tests"][key]=snapshot(page,key)
                print(key, "product status",
                      {k:v.get("ok") for k,v in results["tests"][key].get("images",{}).items()},flush=True)
            except Exception as error:
                results["tests"][key]={"error":str(error)[:400]}
                try:
                    page.screenshot(path=str(ROOT/(key+"-published-error.png")),
                                    full_page=True,timeout=8000)
                except Exception:
                    pass
                print(key,"ERROR",str(error)[:300],flush=True)
            finally:
                context.close()
        browser.close()
    (ROOT/"live_browser_delivery.json").write_text(
        json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print("Deployed browser evidence:",json.dumps({
        name:{"error":item.get("error"),"timeline_count":item.get("timeline_count"),
              "image_ok":{k:v.get("ok") for k,v in item.get("images",{}).items()},
              "overlay":item.get("overlay_checks")}
        for name,item in results["tests"].items()
    },ensure_ascii=False,indent=2),flush=True)
    return 1 if any("error" in item for item in results["tests"].values()) else 0


if __name__=="__main__":
    sys.exit(main())
