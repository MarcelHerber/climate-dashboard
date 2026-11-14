#!/usr/bin/env python3
"""Convert each original CFSR/CFSv2 TMP2M f003 year into an extended daily grid.

Uses precisely the official 360 monthly originals and 00/06/12/18+3h fields
already validated by the old narrow-grid importer. Only spatial target changes.
Annual artifacts are DAILY MEANS to conserve GitHub Actions artifact storage.
No synthetic forecast, ERA5, or interpolated UTC time is permitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np

from scripts import import_cfsr_cfsv2_f003_1991_2020 as original
from scripts import build_gfs_cfsr_f003_1991_2020 as historical
from scripts import probe_cfs_f003_wider_europe as wide

OUT=Path("gfs_analysis_europe/reference_sources_f003_extended")


def import_year(year:int,output:Path=OUT)->Path:
    if year<1991 or year>2020:
        raise ValueError("Reference years must be 1991–2020")
    wide.configure_extended()
    with tempfile.TemporaryDirectory(prefix="cfs-wide-year-") as td:
        archive=original.import_year(year,Path(td))
        with np.load(archive,allow_pickle=False) as z:
            temp=np.asarray(z["temp_c"],dtype=np.float32)
            dates=z["dates"].tolist()
            metadata=json.loads(str(z["metadata_json"]))
        if temp.shape!=(365,4,wide.H,wide.W) or dates!=historical.expected_days(year):
            raise ValueError("Original CFS source failed extended 365-day/4-cycle validation")
        if metadata["forecast_hour"]!=3 or metadata["hours_utc"]!=[3,9,15,21]:
            raise ValueError("Historical originals aren't consistent f003")
        if len(metadata["source_files"])!=12:
            raise ValueError("Missing monthly CFSR/CFSv2 provenance")
        # Convert 4 authentic daily cycle temperatures into a single verified
        # daily original mean; entire 30-year reference is daily only.
        daily=temp.mean(axis=1,dtype=np.float64).astype(np.float32)
        if not np.isfinite(daily).all() or not np.all((-100<daily)&(daily<70)):
            raise ValueError("Bad extended CFS 2m temperatures")
        meta={
            "year":year,
            "product":historical.expected_product(year),
            "forecast_hour":3,
            "hours_utc":[3,9,15,21],
            "cycles_utc":[0,6,12,18],
            "grid":"0.5degree-aligned North Atlantic–Ural f003 extension",
            "shape":[365,wide.H,wide.W],
            "north":wide.NORTH,"west":wide.WEST,
            "south":wide.NORTH-.5*(wide.H-1),
            "east":wide.WEST+.5*(wide.W-1),
            "source_files":metadata["source_files"],
            "method":"Daily mean of 4 genuine +3h original CFSR/CFSv2 TMP2M fields",
        }
        path=output/f"t2m_f003_extended_{year}.npz"
        path.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(path,temperature_daily_c=daily,
                            dates=np.asarray(dates),
                            metadata_json=json.dumps(meta,separators=(",",":")))
        print("Verified enlarged original CFS f003 year",year,path,daily.shape,flush=True)
        return path


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--output",type=Path,default=OUT)
    args=p.parse_args()
    import_year(args.year,args.output)
