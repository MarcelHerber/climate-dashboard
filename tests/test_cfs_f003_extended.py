"""Strict metadata and domain tests before 30-year original CFSR/CFSv2 backfill."""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pytest

from scripts import build_cfs_f003_extended_1991_2020 as wide
from scripts import probe_cfs_f003_wider_europe as region
from scripts import build_gfs_cfsr_f003_1991_2020 as original


def test_wide_grid_covers_old_europe_by_exact_integer_cells():
    assert region.H==121 and region.W==361
    assert (region.NORTH,region.WEST)==(84.75,-80.25)
    assert region.NORTH-.5*(region.H-1)==24.75
    assert region.WEST+.5*(region.W-1)==99.75
    assert region.NORTH-region.CORE_Y*.5==71.75
    assert region.WEST+region.CORE_X*.5==-24.75


def generate_year(tmp_path,year=2020,step=3):
    days=original.expected_days(year)
    files=[]
    for month in range(1,13):
        product="CFSR" if (year,month)<(2011,4) else "CFSv2"
        n=sum(d[5:7]==f"{month:02d}" for d in days)
        files.append({
            "month":month,"product":product,
            "primary_source_url":"https://www.ncei.noaa.gov/verified-original/"+str(month),
            "primary_source_sha256":"f"*64,
            "days":n
        })
    meta={
        "year":year,"product":original.expected_product(year),
        "forecast_hour":step,"hours_utc":[3,9,15,21],
        "cycles_utc":[0,6,12,18],
        "shape":[365,region.H,region.W],
        "north":region.NORTH,"west":region.WEST,
        "south":24.75,"east":99.75,
        "source_files":files
    }
    path=tmp_path/f"t2m_f003_extended_{year}.npz"
    temperature=np.full((365,region.H,region.W),5,dtype=np.float32)
    np.savez_compressed(path,temperature_daily_c=temperature,
                        dates=np.asarray(days),metadata_json=json.dumps(meta))
    return path


def test_valid_full_original_year(tmp_path):
    p=generate_year(tmp_path)
    field,meta=wide.check_year(2020,p)
    assert field.shape==(365,121,361)
    assert meta["source_files"][11]["days"]==31


def test_wrong_forecast_step_rejected(tmp_path):
    p=generate_year(tmp_path,step=0)
    with pytest.raises(ValueError,match="source identity"):
        wide.check_year(2020,p)


def test_reject_missing_reference_year(tmp_path):
    with pytest.raises(FileNotFoundError):
        wide.check_year(1991,tmp_path/"missing.npz")


def test_leap_day_is_never_in_climatology():
    assert len(original.expected_days(2020))==365
    assert "2020-02-29" not in original.expected_days(2020)


def test_2011_original_CFSR_to_CFSv2_transition(tmp_path):
    p=generate_year(tmp_path,year=2011)
    field,meta=wide.check_year(2011,p)
    assert meta["source_files"][2]["product"]=="CFSR"
    assert meta["source_files"][3]["product"]=="CFSv2"
    assert meta["product"]=="CFSR+CFSv2"
