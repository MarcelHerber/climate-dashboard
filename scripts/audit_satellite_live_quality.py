#!/usr/bin/env python3
"""Live audit of the *published* MTG page and a comparable EUMETSAT WMS crop.

Three requested pixel densities use the exact same UTC, layer, geographic
bounding box, and 22% central-Europe crop used by satellite_quality_comparison.js.
This documents WMS detail/latency, NOT the physical resolution of MTG-FCI.
No fake images, no interpolation used as evidence for additional source detail.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

SITE = "https://marcelherber.github.io/climate-dashboard/"
WMS = "https://view.eumetsat.int/geoserver/wms"
TARGETS = {
    "geocolour": "mtg_fd:rgb_geocolour",
    "cloudtype": "mtg_fd:rgb_cloudtype",
    "ir105": "mtg_fd:ir105_hrfi",
}
SIZES = (800, 2048, 4096)
EUROPE = (-27.0, 24.0, 49.0, 73.0, 1300, 850)
ROI_FRACTION = 0.22
OUTDIR = Path("_satellite_quality_evidence")
HEADERS = {"User-Agent": "ClimateDashboard-LiveQualityQA/1.0",
           "Origin": "https://marcelherber.github.io"}


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        obj = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return obj.astimezone(timezone.utc) if obj.tzinfo else None
    except ValueError:
        return None


def latest_common_utc(products, required=tuple(TARGETS)):
    """Latest common *advertised* UTC no later than each confirmed image UTC.

    We still require a real PNG response at that UTC for every product/size.
    """
    times = None
    for key in required:
        item = products.get(key, {})
        confirmed = utc(item.get("latest_verified_time")) if item.get("map_ok") else None
        advertised = {t for t in item.get("available_times", []) if utc(t) and
                      confirmed and utc(t) <= confirmed}
        times = advertised if times is None else times & advertised
    return max(times, key=lambda t: utc(t)) if times else None


def crop_bbox(region=EUROPE, fraction=ROI_FRACTION, position=(.5, .5)):
    west, south, east, north = region[:4]
    width, height = east - west, north - south
    cx, cy = position
    x0 = west + (cx-fraction/2)*width
    x1 = west + (cx+fraction/2)*width
    ytop = north - (cy-fraction/2)*height
    ybottom = north - (cy+fraction/2)*height
    return [x0, ybottom, x1, ytop]


def pixel_grid(full_width, region=EUROPE, fraction=ROI_FRACTION):
    _, _, _, _, width, height = region
    crop_w = max(1, round(full_width*fraction))
    crop_h = max(1, round(full_width*height/width*fraction))
    return crop_w, crop_h


def get(url, *, seconds=22, max_bytes=8_000_000):
    start = time.monotonic()
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=seconds) as response:
        payload = response.read(max_bytes+1)
        if len(payload)>max_bytes:
            raise ValueError("Response exceeds capped source size")
        return payload, {
            "http": response.status,
            "content_type": response.headers.get("Content-Type", ""),
            "cors": response.headers.get("Access-Control-Allow-Origin"),
            "elapsed_seconds": round(time.monotonic()-start, 2),
            "bytes": len(payload),
        }


def page_version(url=SITE):
    """Fetch delivered HTML/manifest/JS. Do not confuse main-branch with Pages."""
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "url": url}
    base = url.rstrip("/")+"/"
    try:
        html, stat = get(urljoin(base, "satelliten.html"), max_bytes=500_000)
        text = html.decode("utf-8")
        result["html"] = stat
        required = ("satShowLightning", "satShowRadar", "satStillQuality",
                    "satCompareGrid", "satImage", "satQualityCompareSection")
        result["html_controls"] = {key: f'id="{key}"' in text for key in required}
        assets = ("satelliten.js", "satellite_lightning.js", "satellite_radar.js",
                  "satellite_hd.js", "satellite_quality_comparison.js")
        result["asset_checks"] = {}
        for name in assets:
            match = re.search(r"""src=["']([^"']*""" + re.escape(name) + r"""(?:\?[^"']*)?)["']""", text)
            if match:
                target = urljoin(base, match.group(1))
                try:
                    source, jsstat = get(target, max_bytes=500_000)
                    result["asset_checks"][name] = {"url": target, "ok": jsstat["http"] == 200,
                                                   "bytes": len(source)}
                except Exception as error:
                    result["asset_checks"][name] = {"url": target, "ok": False, "error": str(error)[:240]}
            else:
                result["asset_checks"][name] = {"ok": False, "error": "Script missing from served HTML"}
        status_bytes, data_stat = get(urljoin(base, "data/satellite_wms_times.json"),
                                      max_bytes=1_000_000)
        data = json.loads(status_bytes)
        result["published_report"] = {
            "http": data_stat["http"], "generated_at": data.get("generated_at"),
            "capabilities_ok": data.get("capabilities_ok"),
            "monitor_status": data.get("monitor_status"),
            "products": {
                key: {"map_ok": row.get("map_ok"),
                      "verified_utc": row.get("latest_verified_time"),
                      "advertised_utc": row.get("latest_advertised_time")}
                for key, row in data.get("products", {}).items()
            }
        }
        now=datetime.now(timezone.utc)
        stamp=utc(data.get("generated_at"))
        result["published_report"]["age_minutes"] = round((now-stamp).total_seconds()/60,1) if stamp else None
        result["published_manifest"] = data
        result["html_ok"] = all(result["html_controls"].values()) and \
                            all(x.get("ok") for x in result["asset_checks"].values())
    except Exception as error:
        result["html_ok"] = False
        result["error"] = str(error)[:300]
    return result


def align_li(products, sat_utc):
    """LI-AFA is accumulated during [start,start+5m]; never after satellite UTC."""
    from datetime import timedelta
    li = products.get("lightning", {})
    value = utc(sat_utc)
    if not value or not li.get("map_ok") or not utc(li.get("latest_verified_time")):
        return {"aligned": False, "reason": "unverified LI or satellite time"}
    times = [utc(t) for t in li.get("available_times", []) if utc(t)]
    candidates = sorted([t for t in times if t+timedelta(minutes=5) <= value])
    if not candidates:
        return {"aligned": False, "reason": "no fully ended LI interval"}
    best=candidates[-1];gap=(value-best-timedelta(minutes=5)).total_seconds()/60
    return {"aligned": gap<=10, "li_start":best.isoformat(), "li_end":(best+timedelta(minutes=5)).isoformat(),
            "delay_minutes": round(gap, 1),
            "reason": "AFA is an optical flash-area accumulation, not an individual lightning point"}


def metadata_source():
    try:
        data, stat = get("https://api.rainviewer.com/public/weather-maps.json",
                         seconds=12, max_bytes=150_000)
        j=json.loads(data)
        frames=j.get("radar",{}).get("past",[])
        valid=[x for x in frames if isinstance(x.get("time"),int) and
               re.fullmatch(r"/v2/radar/(?:[0-9]{10}|[0-9a-fA-F]{12,16})", str(x.get("path","")))]
        return {"available":bool(valid),"frames":len(valid),
                "latest_utc": datetime.fromtimestamp(max(x["time"] for x in valid),timezone.utc).isoformat() if valid else None,
                "source":"RainViewer; composite timing not individual radars",
                "http":stat["http"]}
    except Exception as error:
        return {"available":False,"error":str(error)[:240]}


def verify_png_bytes(blob, width, height):
    """Validate real image pixels. A WMS XML error/blank PNG is not a valid source."""
    from PIL import Image, ImageStat
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("WMS returned non-PNG payload")
    image=Image.open(BytesIO(blob))
    image.load()
    if image.size != (width, height):
        raise ValueError(f"WMS returned wrong image size {image.size}")
    rgb=image.convert("RGB")
    variance = ImageStat.Stat(rgb.resize((min(width, 128), min(height, 128)))).stddev
    if max(variance)<.8:
        raise ValueError("WMS returned an almost uniform image; no demonstrated cloud detail")
    return rgb


def source_png(product, layer, observed_utc, resolution):
    w,h=pixel_grid(resolution)
    bbox=crop_bbox()
    params = urlencode({
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": layer, "styles": "", "format": "image/png",
        "transparent": "false", "srs":"EPSG:4326", "bbox": ",".join(map(str,bbox)),
        "width":str(w),"height":str(h),"time":observed_utc,"bgcolor":"0x000000"
    })
    url=WMS+"?"+params
    tries=[]
    for attempt in range(2):
        try:
            payload,stat=get(url,seconds=22,max_bytes=8_000_000)
            img=verify_png_bytes(payload,w,h)
            outpath=OUTDIR/f"{product}_{resolution}p.png"
            img.save(outpath, "PNG")
            return (img, {"ok":True,"url":url,"size":[w,h],**stat})
        except Exception as error:
            tries.append(str(error)[:170])
            if attempt==0:
                time.sleep(.45)
    return (None, {"ok":False,"size":[w,h],"error":" | ".join(tries),"url":url})


def measure_difference(reference, finer):
    from PIL import Image, ImageChops, ImageStat
    match=reference.resize(finer.size,Image.Resampling.BICUBIC)
    diff=ImageChops.difference(finer,match)
    numbers=ImageStat.Stat(diff)
    avg=sum(numbers.mean)/len(numbers.mean)
    # Numerical difference = resampling, processing, and/or additional detail.
    # It cannot by itself establish the physical native sensor resolution.
    return {"mean_absolute_rgb_difference_0to255":round(avg,3),
            "note":"Pixel-level WMS difference, NOT validated native FCI spatial resolution"}


def contact_sheet(data, time_utc):
    from PIL import Image, ImageDraw
    size=(540,350);margin=14;header=58
    result=Image.new("RGB",(3*(size[0]+margin)+margin,3*(size[1]+header+margin)+margin),(14,27,42))
    draw=ImageDraw.Draw(result)
    for ri,key in enumerate(TARGETS):
        row=data.get(key,{})
        for ci,res in enumerate(SIZES):
            x=margin+ci*(size[0]+margin);y=margin+ri*(size[1]+header+margin)
            item=row.get(str(res),{})
            draw.text((x,y),f"{key}  {res} px view  •  UTC {time_utc}",fill="white")
            img=item.get("image")
            if img is not None:
                result.paste(img.resize(size,Image.Resampling.BICUBIC),(x,y+header))
            else:
                draw.text((x+20,y+header+50),"NOT AVAILABLE: WMS request failed",fill="#ffad9b")
    out=OUTDIR/"standard_hd_4k_europe_comparison.png"
    result.save(out)
    return str(out)


def source_jobs(observed_utc, targets=TARGETS, resolutions=SIZES):
    """Each job carries the exact same verified UTC explicitly."""
    return [(key, layer, observed_utc, size)
            for key, layer in targets.items() for size in resolutions]


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--site",default=SITE)
    parser.add_argument("--skip-images",action="store_true")
    args=parser.parse_args(argv)
    OUTDIR.mkdir(parents=True,exist_ok=True)
    remote=page_version(args.site)
    source_data=json.loads(Path("data/satellite_wms_times.json").read_text(encoding="utf-8"))
    products=source_data.get("products",{})
    remote_data=remote.pop("published_manifest",None)
    observed=latest_common_utc(products)
    report={
        "checked_at":datetime.now(timezone.utc).isoformat(),
        "source_report_generated_at":source_data.get("generated_at"),
        "published_page":remote,
        "site_vs_repo_report": {
            "same_generated_at":bool(remote_data) and
                 remote_data.get("generated_at")==source_data.get("generated_at"),
            "source_generated_at":source_data.get("generated_at"),
            "published_generated_at":remote_data.get("generated_at") if remote_data else None,
        },
        "utc_common":observed,
        "li_alignment":align_li(products, observed),
        "radar":metadata_source(),
        "roi_bbox":crop_bbox(),
        "roi_fraction":ROI_FRACTION,
        "samples": {},
        "explanation":"Observed pixels and resampling differences; WMS pixel count is not proof of native FCI resolution."
    }
    pixels={}
    if observed and not args.skip_images:
        jobs=source_jobs(observed)
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks={pool.submit(source_png,*item):item for item in jobs}
            for finished in as_completed(tasks):
                key,layer,observed_sample,res=tasks[finished]
                try:
                    img,stat=finished.result()
                except Exception as error:
                    img=None;stat={"ok":False,"error":str(error)[:250]}
                pixels.setdefault(key,{})[str(res)]={"image":img,**stat}
                report["samples"].setdefault(key,{})[str(res)]={k:v for k,v in stat.items() if k!="url"}
                print(f"WMS sample {key} {res} px: {'OK' if stat.get('ok') else 'UNAVAILABLE'}",flush=True)
        from PIL import Image
        for key in TARGETS:
            item=pixels.get(key,{})
            if item.get("800",{}).get("image") is not None and item.get("2048",{}).get("image") is not None:
                report["samples"][key]["800_to_2048"] = measure_difference(item["800"]["image"],item["2048"]["image"])
            if item.get("2048",{}).get("image") is not None and item.get("4096",{}).get("image") is not None:
                report["samples"][key]["2048_to_4096"] = measure_difference(item["2048"]["image"],item["4096"]["image"])
        report["contact_sheet"]=contact_sheet(pixels,observed)
    elif not observed:
        report["warning"]="No common advertised UTC not later than all verified latest PNG times"
    path=OUTDIR/"live_image_quality_report.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "site_accessible":remote.get("html_ok"),
        "source_utc":observed,
        "site_manifest_age_minutes":remote.get("published_report",{}).get("age_minutes"),
        "lightning_aligned":report["li_alignment"].get("aligned"),
        "radar_latest_utc":report["radar"].get("latest_utc"),
        "samples":report["samples"]
    },ensure_ascii=False,indent=2))
    # External WMS/Pages outages are evidence, not an excuse to claim success.
    # The CI's structural tests catch implementation bugs separately.
    return 0


if __name__=="__main__":
    sys.exit(main())
