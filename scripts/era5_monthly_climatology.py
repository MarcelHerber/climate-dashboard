#!/usr/bin/env python3
"""Scientifically targeted ERA5 climate-month atlas (six groups, eight products).

Products: 1000–500 hPa thickness, total-column vapour, 850 hPa specific humidity,
the magnitude of the mean 250 hPa wind vector (NOT mean wind speed), low/mid/high
cloud cover and boundary-layer height. Reference is always 1991–2020, rankings
are compared to the 1940–2025 same-calendar-month historical population.

Only complete, validated releases are inserted into the public index.
No weather-event frequency or daily extremes are inferred from monthly means.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import xarray as xr

from build_era5_atmos_history import render_triptych
from update_era5_europe import (
    HISTORY_START, REFERENCE_START, REFERENCE_END, MONTH_NAMES,
    cds_client, request_pressure, request_single,
    normalize_dataarray, years_from_times, rank_field,
    area_weighted_mean, area_weighted_fraction,
)

REPO = "MarcelHerber/climate-dashboard"
BASELINE_END = 2025
YEARS = np.arange(HISTORY_START, BASELINE_END + 1)
REFERENCE_TAG = "era5-climate-reference-1940-2025-v1"
RELEASE_PREFIX = "era5-climate"
VIEWS = ("absolute", "anomaly", "rank")
PARAMS = {
    "thickness": dict(label="Schichtdicke 1000–500 hPa", short_label="ΔZ1000–500",
        unit="gpm", anomaly_unit="gpm", kind="thickness", rank_label="1 = größte Schichtdicke",
        absolute_cmap="Spectral_r", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-120,-90,-60,-40,-25,-15,-8,0,8,15,25,40,60,90,120]),
    "tcwv": dict(label="Gesamtsäulenwasserdampf", short_label="TCWV",
        unit="kg/m²", anomaly_unit="kg/m²", kind="single",
        variable="total_column_water_vapour", aliases=("tcwv", "total_column_water_vapour"),
        rank_label="1 = feuchtester Monat", absolute_cmap="YlGnBu",
        anomaly_cmap="BrBG", anomaly_bounds=[-20,-15,-10,-7,-5,-3,-1.5,0,1.5,3,5,7,10,15,20]),
    "q850": dict(label="Spezifische Feuchte 850 hPa", short_label="q850",
        unit="g/kg", anomaly_unit="g/kg", kind="pressure",
        variable="specific_humidity", level="850", aliases=("q","specific_humidity"),
        factor=1000., rank_label="1 = höchste spezifische Feuchte",
        absolute_cmap="YlGnBu", anomaly_cmap="BrBG",
        anomaly_bounds=[-4,-3,-2,-1.5,-1,-0.6,-0.3,0,0.3,0.6,1,1.5,2,3,4]),
    "wind250": dict(label="Betrag des mittleren Windvektors 250 hPa", short_label="Wind250",
        unit="m/s", anomaly_unit="m/s", kind="wind",
        level="250", rank_label="1 = stärkster mittlerer Windvektor",
        absolute_cmap="plasma", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-20,-15,-10,-7,-5,-3,-1,0,1,3,5,7,10,15,20]),
    "lcc": dict(label="Tiefe Wolkenbedeckung", short_label="Tiefe Wolken",
        unit="%", anomaly_unit="Prozentpunkte", kind="single",
        variable="low_cloud_cover", aliases=("lcc","low_cloud_cover"),
        factor=100., rank_label="1 = meiste tiefe Bewölkung",
        absolute_cmap="Blues", anomaly_cmap="BrBG",
        anomaly_bounds=[-40,-30,-20,-15,-10,-5,-2,0,2,5,10,15,20,30,40]),
    "mcc": dict(label="Mittlere Wolkenbedeckung", short_label="Mittlere Wolken",
        unit="%", anomaly_unit="Prozentpunkte", kind="single",
        variable="medium_cloud_cover", aliases=("mcc","medium_cloud_cover"),
        factor=100., rank_label="1 = meiste mittlere Bewölkung",
        absolute_cmap="Blues", anomaly_cmap="BrBG",
        anomaly_bounds=[-40,-30,-20,-15,-10,-5,-2,0,2,5,10,15,20,30,40]),
    "hcc": dict(label="Hohe Wolkenbedeckung", short_label="Hohe Wolken",
        unit="%", anomaly_unit="Prozentpunkte", kind="single",
        variable="high_cloud_cover", aliases=("hcc","high_cloud_cover"),
        factor=100., rank_label="1 = meiste hohe Bewölkung",
        absolute_cmap="Blues", anomaly_cmap="BrBG",
        anomaly_bounds=[-40,-30,-20,-15,-10,-5,-2,0,2,5,10,15,20,30,40]),
    "blh": dict(label="Grenzschichthöhe", short_label="BLH",
        unit="m", anomaly_unit="m", kind="single",
        variable="boundary_layer_height", aliases=("blh","boundary_layer_height"),
        rank_label="1 = höchste Grenzschicht",
        absolute_cmap="viridis", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-700,-500,-350,-250,-150,-75,-25,0,25,75,150,250,350,500,700]),
}


def parse_period(period: str) -> tuple[int, int]:
    try:
        year, month = map(int, period.split("-"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid calendar period: {period}") from exc
    if year < HISTORY_START or not 1 <= month <= 12 or period != f"{year:04d}-{month:02d}":
        raise ValueError(f"Invalid calendar period: {period}")
    return year, month


def release_tag(year: int) -> str:
    return f"{RELEASE_PREFIX}-{year}-v1"


def validate_reference(filename: Path, key: str, month: int) -> None:
    with np.load(filename, allow_pickle=False) as pack:
        if set(pack.files) != {"year", "month", "lat", "lon", "values"}:
            raise ValueError(f"Invalid pack structure: {key}/{month}")
        year = np.asarray(pack["year"], dtype=int)
        lat, lon = pack["lat"], pack["lon"]
        values = pack["values"]
        if int(pack["month"]) != month or not np.array_equal(year, YEARS):
            raise ValueError(f"Wrong year population in reference {key}/{month}")
        if values.shape != (len(YEARS), len(lat), len(lon)):
            raise ValueError(f"Wrong shape for {key}/{month}: {values.shape}")
        if len(lat) < 100 or len(lon) < 100 or np.isfinite(values).mean() < .95:
            raise ValueError(f"Incomplete gridded data in {key}/{month}")


def retrieve(client, key: str, years: list[int], month: int, folder: Path):
    meta = PARAMS[key]
    folder.mkdir(parents=True, exist_ok=True)

    def read(variable: str, aliases: tuple[str,...], level: str | None, suffix: str):
        dest = folder / f"{key}-{suffix}.nc"
        for attempt in range(1, 4):
            try:
                if level is not None:
                    request_pressure(client, variable=[variable], level=level, years=years, month=month, target=dest)
                else:
                    request_single(client, variable=variable, years=years, month=month, target=dest)
                if not dest.is_file() or dest.stat().st_size < 1024:
                    raise RuntimeError(f"Empty ERA5 request {variable}/{level}")
                with xr.open_dataset(dest) as ds:
                    result = normalize_dataarray(ds, aliases)
                return result
            except Exception:
                if attempt == 3:
                    raise
                print(f"CDS retry {attempt}/3: {key}/{suffix}", flush=True)
                time.sleep(10 * attempt)
            finally:
                dest.unlink(missing_ok=True)

    if meta["kind"] == "thickness":
        lat, lon, ts, z500 = read("geopotential", ("z","geopotential"), "500", "z500")
        lat2, lon2, ts2, z1000 = read("geopotential", ("z","geopotential"), "1000", "z1000")
        if not (np.array_equal(ts,ts2) and np.allclose(lat,lat2) and np.allclose(lon,lon2)):
            raise RuntimeError("Thickness levels disagree in grid/time")
        vals = (z500 - z1000) / np.float32(9.80665)
    elif meta["kind"] == "wind":
        lat, lon, ts, u = read("u_component_of_wind", ("u","u_component_of_wind"), "250", "u250")
        lat2, lon2, ts2, v = read("v_component_of_wind", ("v","v_component_of_wind"), "250", "v250")
        if not (np.array_equal(ts,ts2) and np.allclose(lat,lat2) and np.allclose(lon,lon2)):
            raise RuntimeError("250hPa U/V mismatch")
        # Magnitude of mean vector. NOT time-mean of instantaneous wind speed.
        vals = np.hypot(u, v)
    else:
        lat, lon, ts, vals = read(meta["variable"], tuple(meta["aliases"]),
                                  meta.get("level"), "field")
        vals = vals * np.float32(meta.get("factor", 1.))
    observed = years_from_times(ts)
    if not np.array_equal(observed, np.asarray(years)):
        raise RuntimeError(f"Invalid ERA5 time coordinate: {observed}, expected {years}")
    if np.isfinite(vals).mean() < .95:
        raise RuntimeError("Missing >5% of the ERA5 gridded values")
    if key in ("lcc","mcc","hcc") and not (np.nanmin(vals)>-2 and np.nanmax(vals)<102):
        raise ValueError("Cloud fractions outside plausible range 0–100%")
    return lat.astype("float32"), lon.astype("float32"), np.asarray(vals,dtype="float32")


def reference(month: int, key: str, output: Path):
    if key not in PARAMS or not 1 <= month <= 12:
        raise ValueError((key,month))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        validate_reference(output,key,month)
        return
    lat,lon,values=retrieve(cds_client(),key,YEARS.tolist(),month,output.parent)
    tmp=output.with_name(output.name+".partial.npz")
    np.savez_compressed(tmp,year=YEARS.astype("int16"),month=np.int16(month),
                        lat=lat,lon=lon,values=values)
    validate_reference(tmp,key,month)
    tmp.replace(output)
    print(f"Valid reference: {month:02d}/{key}",flush=True)


def manifest_check(entry: dict):
    year, month = parse_period(entry["period"])
    if not entry.get("ready") or entry.get("year") != year or entry.get("month") != month:
        raise ValueError("Invalid date or readiness in climate manifest")
    if set(entry.get("products",{})) != set(PARAMS):
        raise ValueError(f"Missing climate products for {entry['period']}")
    for key,product in entry["products"].items():
        needle=f"/{release_tag(year)}/{entry['period']}-{key}.webp"
        if any(needle not in product.get(view,{}).get("file","") for view in VIEWS):
            raise ValueError(f"Wrong release path: {entry['period']}/{key}")


def render(period: str, reference_dir: Path, output: Path):
    year, month=parse_period(period)
    output.mkdir(parents=True,exist_ok=True)
    products={}
    client=cds_client() if year > BASELINE_END else None
    for key,meta in PARAMS.items():
        p=reference_dir/f"month_{month:02d}_{key}.npz"
        validate_reference(p,key,month)
        with np.load(p,allow_pickle=False) as data:
            lat=np.asarray(data["lat"],dtype="float32")
            lon=np.asarray(data["lon"],dtype="float32")
            values=np.asarray(data["values"],dtype="float32")
            years=np.asarray(data["year"],dtype=int)
        if year<=BASELINE_END:
            current=values[year-HISTORY_START]
            rank_history=values
        else:
            cur_lat,cur_lon,current_cube=retrieve(client,key,[year],month,output)
            if not (np.allclose(lat,cur_lat) and np.allclose(lon,cur_lon)):
                raise RuntimeError(f"Grid mismatch in {period}/{key}")
            current=current_cube[0]
            rank_history=np.concatenate([values,current[None,:,:]],axis=0)
        normal=np.nanmean(values[(years>=REFERENCE_START)&(years<=REFERENCE_END)],axis=0)
        anomaly=(current-normal).astype("float32")
        rank=rank_field(current,rank_history)
        atlas=output/f"{period}-{key}.webp"
        render_triptych(current,anomaly,rank,lat,lon,
            meta=meta,key=key,label=f"{MONTH_NAMES[month]} {year}",
            destination=atlas,rank_total=len(rank_history),rank_end=max(BASELINE_END,year))
        url=f"https://github.com/{REPO}/releases/download/{release_tag(year)}/{atlas.name}"
        valid=np.isfinite(rank)
        products[key]={
            "label":meta["label"],"short_label":meta["short_label"],
            "unit":meta["unit"],"level_hpa": None,
            "absolute":{"file":url,"tile_index":0},
            "anomaly":{"file":url,"tile_index":1,"unit":meta["anomaly_unit"],
                       "reference_period":"1991–2020"},
            "rank":{"file":url,"tile_index":2,"history_start":HISTORY_START,
                    "history_end":max(BASELINE_END,year),
                    "comparison_years":len(rank_history)-1,
                    "total_rank_positions":len(rank_history),
                    "direction":meta["rank_label"],
                    "rank1_area_percent":area_weighted_fraction(rank<=1,valid,lat),
                    "top3_area_percent":area_weighted_fraction(rank<=3,valid,lat)},
            "stats":{"current_area_mean":area_weighted_mean(current,lat),
                     "reference_area_mean":area_weighted_mean(normal,lat),
                     "anomaly_area_mean":area_weighted_mean(anomaly,lat)},
        }
        print(f"Rendered climate atlas: {period}/{key}",flush=True)
    entry={"ready":True,"year":year,"month":month,"period":period,
        "label":f"{MONTH_NAMES[month]} {year}","reference_period":"1991–2020",
        "products":products}
    manifest_check(entry)
    (output/"manifest.json").write_text(json.dumps(entry,ensure_ascii=False,
        indent=2,allow_nan=False)+"\n",encoding="utf-8")


def plan(index: Path, main: Path, output: Path, batch_size: int):
    idx=json.loads(index.read_text(encoding="utf-8"))
    main_data=json.loads(main.read_text(encoding="utf-8"))
    done=set(idx.get("available_periods",[]))
    # First ensure users can view current-year maps, then backfill historical years.
    recents=sorted([p for p in main_data.get("available_periods",[])
                    if p>="2026-01" and p not in done],reverse=True)
    if recents:
        period=recents[0]
        todo=[period]
    else:
        period=next((f"{y:04d}-{m:02d}" for m in range(1,13)
                     for y in YEARS if f"{y:04d}-{m:02d}" not in done),None)
        if period:
            year,month=parse_period(period)
            todo=[f"{y:04d}-{month:02d}" for y in range(year,min(BASELINE_END,year+batch_size-1)+1)
                  if f"{y:04d}-{month:02d}" not in done]
        else:
            todo=[]
    result={"has_work":"true" if todo else "false",
            "month":period[5:] if period else "00",
            "year":period[:4] if period else "0000",
            "years":json.dumps(todo,separators=(",",":"))}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("a",encoding="utf-8") as file:
        for k,v in result.items():
            file.write(f"{k}={v}\n")
    print(f"Climate atlas plan: {todo}; done {len(done)} periods",flush=True)


def merge(artifacts: Path, root: Path):
    base=root/"era5_europe"/"climatology"
    history=base/"history"
    current=base/"current"
    history.mkdir(parents=True,exist_ok=True)
    current.mkdir(parents=True,exist_ok=True)
    added=[]
    for filename in sorted(artifacts.rglob("manifest.json")):
        entry=json.loads(filename.read_text(encoding="utf-8"))
        manifest_check(entry)
        year=entry["year"]
        period=entry["period"]
        if year<=BASELINE_END:
            dest=history/f"{year}.json"
            data=json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {
                "ready":True,"year":year,"periods":{}}
            data["periods"][period]=entry
        else:
            dest=current/f"{period}.json"
            data=entry
        dest.write_text(json.dumps(data,ensure_ascii=False,indent=2,
            allow_nan=False)+"\n",encoding="utf-8")
        added.append(period)
    if not added: raise RuntimeError("No verified maps provided")
    verified=set()
    for path in sorted(history.glob("????.json")):
        data=json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("periods",{}).values():
            manifest_check(entry)
            verified.add(entry["period"])
    for path in sorted(current.glob("????-??.json")):
        data=json.loads(path.read_text(encoding="utf-8"))
        manifest_check(data)
        verified.add(data["period"])
    index_file=base/"index.json"
    idx=json.loads(index_file.read_text(encoding="utf-8"))
    idx["available_periods"]=sorted(verified)
    idx["completed"]=len(verified)
    idx["latest_month"]=max(verified)
    idx["ready"]=True
    idx["products"]={k:{"label":v["label"],"short_label":v["short_label"],
        "unit":v["unit"]} for k,v in PARAMS.items()}
    index_file.write_text(json.dumps(idx,ensure_ascii=False,indent=2,
        allow_nan=False)+"\n",encoding="utf-8")
    print(f"New verified climate periods: {added} ({len(verified)} total)",flush=True)


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    ref=sub.add_parser("reference")
    ref.add_argument("--month",required=True,type=int)
    ref.add_argument("--key",required=True,choices=PARAMS)
    ref.add_argument("--output",required=True,type=Path)
    plot=sub.add_parser("render")
    plot.add_argument("--period",required=True)
    plot.add_argument("--references",required=True,type=Path)
    plot.add_argument("--output",required=True,type=Path)
    plan_cmd=sub.add_parser("plan")
    plan_cmd.add_argument("--index",required=True,type=Path)
    plan_cmd.add_argument("--main",required=True,type=Path)
    plan_cmd.add_argument("--output",required=True,type=Path)
    plan_cmd.add_argument("--batch-size",type=int,default=2)
    merge_cmd=sub.add_parser("merge")
    merge_cmd.add_argument("--artifacts",required=True,type=Path)
    merge_cmd.add_argument("--root",type=Path,default=Path("."))
    args=p.parse_args()
    if args.command=="reference":
        reference(args.month,args.key,args.output)
    elif args.command=="render":
        render(args.period,args.references,args.output)
    elif args.command=="plan":
        plan(args.index,args.main,args.output,args.batch_size)
    elif args.command=="merge":
        merge(args.artifacts,args.root)


if __name__=="__main__":
    main()
