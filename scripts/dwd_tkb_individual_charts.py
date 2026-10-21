#!/usr/bin/env python3
"""Five original DWD TKBoden surface-pressure and frontal FORECAST SINGLE maps.

Not the unrelated ico_hptfg_na mosaic sheets! No guessed UTC validity or model
initialisation: the DWD original chart footer supplies the exact validity.
Only use files downloaded from the official DWD publisher, never a mirror.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

PRODUCTS=(36,48,60,84,108)
BASE="https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/"
FILENAME="ico_tkboden_na_{:03d}.png"

def source_url(lead):
    if lead not in PRODUCTS: raise ValueError("Unknown DWD TKB product")
    return BASE+FILENAME.format(lead)

def publish(output, now, fetch, image_webp):
    output=Path(output)
    directory=output/"images"
    directory.mkdir(parents=True,exist_ok=True)
    records=[]
    for lead in PRODUCTS:
        image_name=f"dwd_tkb_{lead:03d}.webp"
        destination=directory/image_name
        url=source_url(lead)
        try:
            raw=fetch(url,timeout=32,limit=9_000_000)
            # image_webp rejects non-images, small images and invalid encoding.
            image_webp(raw,destination)
            if destination.stat().st_size<18000: raise ValueError("tiny chart")
            records.append({
                "source_id":"dwd_tkb_original",
                "publisher_id":"dwd",
                "lead_hours":lead,
                "source_url":url,
                "image":"images/"+image_name,
                "size_bytes":destination.stat().st_size,
                "credit":"Quelle: Deutscher Wetterdienst (DWD)",
                "map_type":"single_surface_pressure_and_fronts",
            })
        except Exception as exc:
            # Ensure old file cannot masquerade as fresh.
            destination.unlink(missing_ok=True)
            print(f"DWD TKB Einzelkarte +{lead} h nicht abrufbar: {exc}",flush=True)
    manifest={
        "schema_version":1,
        "generated_utc":now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "source_id":"dwd_tkb_original",
        "description":"Fünf einzelne DWD Bodenprognosekarten, Isobaren und Fronten",
        "source_page":"https://www.dwd.de/",
        "reference_page":"https://www.wetter3.de/fax_dt.html",
        "terms_note":"DWD: Quelle bei jeder Karte nennen; nur offizielle unveränderte Kartenbilder.",
        "single_map_per_lead":True,
        "validity_note":"UTC-Gültigkeit und Modelllauf im jeweiligen Originalkartenfuß ablesen, nicht aus Abrufzeit errechnen.",
        "products":list(PRODUCTS),
        "maps":records,
        "map_count":len(records),
    }
    target=output/"dwd_tkb.json"
    tmp=output/"dwd_tkb.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(target)
    return manifest
