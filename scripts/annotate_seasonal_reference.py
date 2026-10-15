#!/usr/bin/env python3
"""Label already published ECMWF-SEAS5 anomaly PNGs with the honest reference.

Avoid unnecessary full recomputation or API queries. Open-Meteo publishes monthly
anomaly relative to long-term model hindcasts but does not specify the precise
hindcast reference years in the Seasonal API documentation. ECMWF's own SEAS5
chart climatology is 1993-2016; do NOT attribute these years to Open-Meteo's
API values without verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


def font(size: int, bold=False):
    paths = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


REFERENCE = {
    "type": "model_hindcast_climatology",
    "source": "Open-Meteo Seasonal API",
    "api_reference_years": None,
    "ecmwf_original_product_reference": "1993–2016",
    "reference_years_verified_for_api": False,
}
NOTE = ("SEAS5 monthly anomalies are computed against the forecasting system's model "
        "hindcast climatology. ECMWF original SEAS5 chart reference period is "
        "1993–2016; Open-Meteo does not document precise reference years for "
        "its Seasonal API anomaly fields. Not observed 1991–2020 anomalies.")


def annotation(image_file: Path, model_month: str, original_retrieval: str):
    with Image.open(image_file) as source:
        im = source.convert("RGB")
    w,h = im.size
    if w < 1000 or h < 700:
        raise RuntimeError(f"Bildauflösung unerwartet: {image_file}: {w}x{h}")
    draw=ImageDraw.Draw(im)
    background=(247,250,252)
    x=round(w*.045)
    # Clear the four existing bottom-margin texts only. The colorbar,
    # level numbers and map are above this area and remain untouched.
    draw.rectangle((0,round(h*.895),w,h),fill=background)
    lines = [
        ("BEZUGSBASIS: SEAS5-Modellklimatologie (modellinterne Hindcasts)",
         round(h*.898),font(17,bold=True),(36,65,88)),
        ("ECMWF-Originalkarten: 1993–2016  |  Open-Meteo-API: genaue Bezugsjahre nicht ausgewiesen",
         round(h*.925),font(14),(53,77,98)),
        (f"Quelle: ECMWF SEAS5 via Open-Meteo  |  Modell-Ausgabe: {model_month}  |  keine amtliche Warnung",
         round(h*.949),font(14),(75,99,119)),
        (f"Originaldaten abgerufen: {original_retrieval[:16].replace('T',' ')} UTC",
         round(h*.972),font(13),(77,99,118)),
    ]
    for text,y,typ,color in lines:
        if draw.textbbox((x,y),text,font=typ)[2] > w-round(w*.035):
            raise RuntimeError(f"Referenzzeile zu lang für {w}px: {text}")
        draw.text((x,y),text,font=typ,fill=color)
    meta=PngInfo()
    meta.add_text("Model", "ECMWF SEAS5 via Open-Meteo Seasonal API")
    meta.add_text("ReferenceClimatology", "SEAS5 model hindcast climatology; exact years not documented by Open-Meteo")
    meta.add_text("ECMWFOriginalReferencePeriod","1993-2016 (not confirmed for Open-Meteo anomaly values)")
    im.save(image_file,format="PNG",pnginfo=meta,optimize=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args()
    manifest_file=args.root/"index.json"
    manifest=json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("model")!="ecmwf_seas5_ensemble_mean":
        raise RuntimeError("Kein ECMWF-SEAS5-Index; Abbruch")
    if manifest.get("sample_resolution_deg")!=1.0:
        raise RuntimeError("Alte 2°-Karten nicht nachträglich als 1° markieren")
    dates=manifest.get("periods") or []
    if len(dates)<4:
        raise RuntimeError("Saisonale Prognosemonate fehlen")
    if manifest.get("reference_annotation_revision")=="2026-10-baseline-v1":
        print("Referenztexte bereits enthalten; keine Änderung.")
        return
    count=0
    for period in dates:
        for item in period.get("fields",{}).values():
            relative=item.get("image")
            if not relative or ".." in Path(relative).parts:
                raise RuntimeError("Unsichere Bildreferenz")
            png=args.root/relative
            if not png.is_file() or png.stat().st_size<10000:
                raise RuntimeError(f"Kartenbild fehlt: {png}")
            annotation(png,manifest["base_model_month"],manifest["retrieved_utc"])
            count+=1
    if count<12:
        raise RuntimeError("Zu wenige Karte erfolgreich beschriftet")
    manifest["reference_note"]=NOTE
    manifest["anomaly_reference"]=REFERENCE
    manifest["reference_annotation_revision"]="2026-10-baseline-v1"
    manifest["render_revision"]=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
    manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("Fertig: Referenzbasis auf",count,"SEAS5-PNGs vermerkt; Originaldaten unverändert.")


if __name__=="__main__":
    main()
