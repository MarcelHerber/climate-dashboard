#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

PERIOD_KEYS=tuple([f"month_{m:02d}" for m in range(1,13)]+["spring","summer","autumn","winter","year"])
COLS=5
ROWS=4
VALUE_SCALE=100
MISSING=-32768
ABS_STOPS={
    "tmean":[(-25,"#313695"),(-15,"#4575b4"),(-5,"#74add1"),(0,"#abd9e9"),(5,"#e0f3f8"),(10,"#ffffbf"),(15,"#fee090"),(20,"#fdae61"),(25,"#f46d43"),(30,"#d73027"),(38,"#a50026")],
    "tmax":[(-20,"#313695"),(-10,"#4575b4"),(0,"#74add1"),(5,"#abd9e9"),(10,"#e0f3f8"),(15,"#ffffbf"),(20,"#fee090"),(25,"#fdae61"),(30,"#f46d43"),(35,"#d73027"),(45,"#a50026")],
    "tmin":[(-30,"#313695"),(-20,"#4575b4"),(-10,"#74add1"),(-5,"#abd9e9"),(0,"#e0f3f8"),(5,"#ffffbf"),(10,"#fee090"),(15,"#fdae61"),(20,"#f46d43"),(25,"#d73027"),(30,"#a50026")],
}
ANOM_LEVELS=[-6.,-5.,-4.,-3.,-2.,-1.,-.5,0.,.5,1.,2.,3.,4.,5.,6.]
ANOM_COLORS=["#6B03C6","#5E4FFC","#187DFD","#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC","#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19","#E51B75","#FC579B"]


def rgb(hex_value:str)->tuple[int,int,int]:
    value=int(hex_value.lstrip("#"),16)
    return (value>>16&255,value>>8&255,value&255)


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def load_archive(path:Path,parameter:str,year:int|None=None)->dict:
    with np.load(path,allow_pickle=False) as data:
        p=str(np.asarray(data["parameter"]).item())
        keys=tuple(str(v) for v in np.asarray(data["period_keys"]).tolist())
        values=np.asarray(data["values"],dtype=np.int16)
        resolution=int(np.asarray(data["resolution_km"]).item())
        scale=int(np.asarray(data["value_scale"]).item())
        missing=int(np.asarray(data["missing_value"]).item())
        x=np.asarray(data["x"],dtype=np.float64)
        y=np.asarray(data["y"],dtype=np.float64)
        available=np.asarray(data["available"],dtype=np.uint8) if "available" in data.files else np.ones(len(keys),dtype=np.uint8)
        stored_year=int(np.asarray(data["year"]).item()) if "year" in data.files else None
        reference=str(np.asarray(data["reference"]).item()) if "reference" in data.files else None
    if p!=parameter or keys!=PERIOD_KEYS or resolution!=1 or scale!=VALUE_SCALE or missing!=MISSING:
        raise RuntimeError(f"Ungültiges 1-km-Periodenarchiv: {path.name}")
    if year is not None and stored_year!=year:
        raise RuntimeError(f"{path.name}: Jahr {stored_year}, erwartet {year}")
    if values.shape!=(17,y.size,x.size):
        raise RuntimeError(f"{path.name}: unerwartete Rasterform {values.shape}")
    return {"values":values,"x":x,"y":y,"available":available.astype(bool),"year":stored_year,"reference":reference}


def interpolate(values:np.ndarray,stops:list[tuple[float,str]])->np.ndarray:
    points=np.asarray([v for v,_ in stops],dtype=np.float32)
    colors=np.asarray([rgb(c) for _,c in stops],dtype=np.float32)
    flat=np.asarray(values,dtype=np.float32).ravel()
    out=np.empty((flat.size,3),dtype=np.uint8)
    for channel in range(3):
        out[:,channel]=np.clip(np.rint(np.interp(flat,points,colors[:,channel])),0,255).astype(np.uint8)
    return out.reshape(values.shape+(3,))


def anomaly_colors(values:np.ndarray)->np.ndarray:
    levels=np.asarray(ANOM_LEVELS,dtype=np.float32)
    mids=(levels[:-1]+levels[1:])/2.0
    codes=np.digitize(np.asarray(values,dtype=np.float32),mids,right=False)
    palette=np.asarray([rgb(c) for c in ANOM_COLORS],dtype=np.uint8)
    return palette[np.clip(codes,0,len(palette)-1)]


def colorize(q:np.ndarray,parameter:str,mode:str,reference_q:np.ndarray|None=None)->Image.Image:
    valid=q!=MISSING
    if mode=="absolute":
        values=q.astype(np.float32)/VALUE_SCALE
        mapped=interpolate(values,ABS_STOPS[parameter])
    else:
        if reference_q is None:
            raise ValueError("Referenz fehlt")
        valid &= reference_q!=MISSING
        values=(q.astype(np.float32)-reference_q.astype(np.float32))/VALUE_SCALE
        mapped=anomaly_colors(values)
    canvas=np.full(q.shape+(3,),255,dtype=np.uint8)
    if np.any(valid):
        canvas[valid]=mapped[valid]
    return Image.fromarray(canvas,"RGB")


def overlay_boundary(image:Image.Image,boundary:Image.Image|None)->Image.Image:
    if boundary is None:
        return image
    if boundary.size!=image.size:
        raise RuntimeError(f"Grenzoverlay {boundary.size} passt nicht zum Raster {image.size}")
    base=image.convert("RGBA")
    base.alpha_composite(boundary)
    return base.convert("RGB")


def mean_c(q:np.ndarray)->float|None:
    valid=q!=MISSING
    if not np.any(valid):
        return None
    return float(np.mean(q[valid].astype(np.float64))/VALUE_SCALE)


def anomaly_mean_c(q:np.ndarray,ref:np.ndarray)->float|None:
    valid=(q!=MISSING)&(ref!=MISSING)
    if not np.any(valid):
        return None
    return float(np.mean(q[valid].astype(np.float64)-ref[valid].astype(np.float64))/VALUE_SCALE)


def build_sprite(current:dict,reference:dict|None,parameter:str,mode:str,boundary:Image.Image|None)->Image.Image:
    h,w=current["values"].shape[1:]
    sprite=Image.new("RGB",(w*COLS,h*ROWS),(255,255,255))
    for i,key in enumerate(PERIOD_KEYS):
        q=np.flipud(current["values"][i])
        if not current["available"][i]:
            cell=Image.new("RGB",(w,h),(232,235,238))
        else:
            ref=np.flipud(reference["values"][i]) if reference is not None else None
            cell=colorize(q,parameter,mode,ref)
            cell=overlay_boundary(cell,boundary)
        sprite.paste(cell,((i%COLS)*w,(i//COLS)*h))
    return sprite


def save_sprite(sprite:Image.Image,path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    palette=sprite.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
    palette.save(path,format="PNG",optimize=True,compress_level=9)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--parameter",choices=("tmean","tmax","tmin"),required=True)
    ap.add_argument("--year",type=int,required=True)
    ap.add_argument("--archive",required=True)
    ap.add_argument("--reference-1961",required=True)
    ap.add_argument("--reference-1991",required=True)
    ap.add_argument("--boundary")
    ap.add_argument("--output-dir",required=True)
    ap.add_argument("--repository",default="")
    args=ap.parse_args()

    parameter=args.parameter
    year=args.year
    current=load_archive(Path(args.archive),parameter,year)
    ref61=load_archive(Path(args.reference_1961),parameter)
    ref91=load_archive(Path(args.reference_1991),parameter)
    for ref,name in ((ref61,"1961-1990"),(ref91,"1991-2020")):
        if ref["reference"]!=name:
            raise RuntimeError(f"Falsche Referenzdatei: {ref['reference']} statt {name}")
        if ref["x"].shape!=current["x"].shape or ref["y"].shape!=current["y"].shape or not np.allclose(ref["x"],current["x"]) or not np.allclose(ref["y"],current["y"]):
            raise RuntimeError(f"Referenz {name} besitzt anderes Raster")

    boundary=Image.open(args.boundary).convert("RGBA") if args.boundary else None
    out=Path(args.output_dir)
    modes=[
        ("absolute",None),
        ("anomaly_1961-1990",ref61),
        ("anomaly_1991-2020",ref91),
    ]
    sprites={}
    for mode,reference in modes:
        render_mode="absolute" if mode=="absolute" else "anomaly"
        name=f"hyras-historical-{parameter}-{year}-{mode}-1km.png"
        target=out/name
        sprite=build_sprite(current,reference,parameter,render_mode,boundary)
        save_sprite(sprite,target)
        sprites[mode]={
            "file":name,
            "bytes":target.stat().st_size,
            "sha256":sha256(target),
            "url":f"https://github.com/{args.repository}/releases/download/hyras-historical-maps-1km/{name}" if args.repository else None,
        }
        print(f"Sprite fertig: {name} · {target.stat().st_size/1024/1024:.1f} MB",flush=True)

    stats={}
    for i,key in enumerate(PERIOD_KEYS):
        q=current["values"][i]
        stats[key]={
            "available":bool(current["available"][i]),
            "current_mean_c":mean_c(q),
            "references":{
                "1961-1990":{
                    "mean_c":mean_c(ref61["values"][i]),
                    "anomaly_mean_k":anomaly_mean_c(q,ref61["values"][i]),
                },
                "1991-2020":{
                    "mean_c":mean_c(ref91["values"][i]),
                    "anomaly_mean_k":anomaly_mean_c(q,ref91["values"][i]),
                },
            },
        }

    meta={
        "schema_version":1,
        "parameter":parameter,
        "year":year,
        "resolution_km":1,
        "width":int(current["x"].size),
        "height":int(current["y"].size),
        "sprite_layout":{"columns":COLS,"rows":ROWS,"period_keys":list(PERIOD_KEYS)},
        "sprites":sprites,
        "stats":stats,
    }
    (out/f"hyras-historical-{parameter}-{year}-1km.json").write_text(
        json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    return 0


if __name__=="__main__":
    raise SystemExit(main())
