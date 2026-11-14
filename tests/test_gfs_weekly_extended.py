"""Contract for 30-year extended CFSR and genuine original NOAA GFS 7-day maps."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json
import sys
import types

import numpy as np
import pytest

from scripts import update_gfs_weekly_europe_extended as wide

RUN=datetime(2026,11,14,0,tzinfo=timezone.utc)


def verified_meta():
    return {
        "source":"CFSR 1991-03/2011 + CFSv2 04/2011-2020 (T2M f003)",
        "reference_version":"cfsr-cfsv2-t2m-f003-extended-v1",
        "years":30,"source_months":360,"forecast_hour":3,
        "old_core_max_difference_k":0.0,
        "grid_degrees":0.5,
        "lat_north":84.75,"lat_south":24.75,
        "lon_west":-80.25,"lon_east":99.75
    }


def test_grid_dimensions_and_exact_original_europe_overlap():
    assert (wide.W,wide.H)==(361,121)
    assert (wide.LON_WEST,wide.LON_EAST)==(-80.25,99.75)
    assert (wide.LAT_NORTH,wide.LAT_SOUTH)==(84.75,24.75)
    assert (wide.X0,wide.Y0)==(111,26)
    assert wide.LON_WEST+wide.X0*.5==-24.75
    assert wide.LAT_NORTH-wide.Y0*.5==71.75


def test_original_grib_decoding_preserves_old_europe_without_fake_data(monkeypatch):
    meta={
        "edition":2,"discipline":0,"parameterCategory":0,"parameterNumber":0,
        "typeOfLevel":"heightAboveGround","level":2,"forecastTime":165,
        "stepRange":"165","dataDate":20261114,"dataTime":0,
        "validityDate":20261120,"validityTime":2100,
        "Ni":720,"Nj":361,"latitudeOfFirstGridPointInDegrees":90.
    }
    # A varying real-valued global grid catches longitude wraps and latitude flips.
    gl=np.add.outer(np.arange(361,dtype=np.float32)*.011,
                    np.arange(720,dtype=np.float32)*.001)+275
    fake=types.SimpleNamespace(
        codes_grib_new_from_file=lambda file:object(),
        codes_get=lambda gid,key:meta[key],
        codes_get_values=lambda gid:gl.ravel(),
        codes_release=lambda gid:None
    )
    monkeypatch.setitem(sys.modules,"eccodes",fake)
    b=b"GRIB"+b"x"*30000
    old=wide.base.decode_grib(b,RUN,165)
    new=wide.decode_extended_grib(b,RUN,165)
    assert old.shape==(76,140) and new.shape==(121,361)
    assert np.allclose(new[wide.Y0:wide.Y0+76,
                           wide.X0:wide.X0+140],old,atol=1e-4)


def test_extended_7day_valid_calendar_normal_not_run_date_only():
    normal=np.zeros((365,wide.H,wide.W),dtype=np.float32)
    for i in range(7):
        d=(RUN+timedelta(days=i)).date()
        normal[wide.daily.day_index(d)]=np.float32(i)
    source=[
      np.full((wide.H,wide.W),
              (RUN+timedelta(hours=step)).date().day-RUN.date().day+2,
              dtype=np.float32)
      for step in wide.base.LEADS
    ]
    result=wide.calculate(RUN,source,normal,verified_meta())
    assert result["width"]==361 and result["height"]==121
    assert result["sample_count"]==28 and result["period_days"]==7
    assert result["reference_version"]=="cfsr-cfsv2-t2m-f003-extended-v1"
    assert result["valid_to_utc"]=="2026-11-20T21:00:00Z"
    anom=wide.daily.decode_q10(result["anomaly_mean_q10_b64"],(121,361))
    assert np.allclose(anom,2)


def test_incomplete_forecast_rejected():
    fields=[np.ones((wide.H,wide.W),dtype=np.float32) for _ in wide.base.LEADS]
    base=np.zeros((365,wide.H,wide.W),dtype=np.float32)
    with pytest.raises(ValueError,match="28"):
        wide.calculate(RUN,fields[:-1],base,verified_meta())
    fields[-1][0,0]=np.nan
    with pytest.raises(ValueError,match="28"):
        wide.calculate(RUN,fields,base,verified_meta())


def test_load_reference_refuses_unverified_data(tmp_path):
    path=tmp_path/"normal.npz"
    normals=np.zeros((365,121,361),dtype=np.float32)
    counts=np.full(normals.shape,30,dtype=np.uint8)
    data=verified_meta()
    np.savez_compressed(path,normal_t2m_c=normals,year_count=counts,
                        metadata_json=json.dumps(data))
    a,m=wide.load_reference(path)
    assert a.shape==(365,121,361) and m["source_months"]==360
    data["source_months"]=359
    np.savez_compressed(path,normal_t2m_c=normals,year_count=counts,
                        metadata_json=json.dumps(data))
    with pytest.raises(ValueError,match="contract"):
        wide.load_reference(path)


def test_no_reference_no_extended_publication(tmp_path):
    with pytest.raises(RuntimeError,match="not finished"):
        wide.load_reference(tmp_path/"missing.npz")
