"""CFSR/CFSv2 +3 hour temperature climate-reference integrity.

Original f000 archives must never be mislabelled as +3h samples; all
1991–2020 samples come from homogeneous 00/06/12/18 initialisations,
valid at 03/09/15/21 UTC on the same calendar day.
"""
from __future__ import annotations
from datetime import date
import json
import numpy as np
import pytest
from scripts import import_cfsr_cfsv2_f003_1991_2020 as ingest
from scripts import build_gfs_cfsr_f003_1991_2020 as builder

def test_1991_2020_calendar_and_real_transition():
    assert builder.SOURCE.name == "reference_sources_f003"
    assert builder.DEST.name == "climatology_1991_2020_f003.npz"
    assert "f003" in builder.REFERENCE_NAME
    assert ingest.product_for_month(2011,3) == "CFSR"
    assert ingest.product_for_month(2011,4) == "CFSv2"
    assert ingest.TARGET_LAT.shape==(76,)
    assert ingest.TARGET_LON.shape==(140,)
    assert all(len(builder.expected_days(y))==365 for y in range(1991,2021))

def test_no_mixing_f000_with_f003(tmp_path):
    arr=np.full((365,4,76,140),5,dtype=np.float32)
    dates=np.array(builder.expected_days(1991))
    def meta(lead):
        return {
            "year":1991,"product":"CFSR","hours_utc":[3,9,15,21],
            "cycles_utc":[0,6,12,18],"forecast_hour":lead,
            "parameter":"2m temperature","units":"degC",
            "source_files":[{
                "month":m,"days":len([x for x in dates if x[5:7]==f"{m:02d}"]),
                "product":"CFSR",
                "primary_source_url":ingest.source_url(1991,m),
                "primary_source_sha256":"a"*64
            } for m in range(1,13)]
        }
    path=tmp_path/"t2m_6h_1991.npz"
    np.savez_compressed(path,temp_c=arr,dates=dates,metadata_json=json.dumps(meta(0)))
    with pytest.raises(ValueError,match="zero-lead|forecast|synoptic|lead"):
        builder.check_source(1991,path)
    np.savez_compressed(path,temp_c=arr,dates=dates,metadata_json=json.dumps(meta(3)))
    fields,source=builder.check_source(1991,path)
    assert fields.shape==(365,4,76,140)
    assert source["forecast_hour"]==3

def test_missing_years_must_block_f003_climatology(tmp_path):
    with pytest.raises(FileNotFoundError):
        builder.make_normals(tmp_path)

def test_source_url_and_grid():
    assert ingest.source_url(1992,7).endswith("tmp2m.gdas.199207.grb2")
    assert ingest.alternate_source_urls(2018,9)[0].endswith("tmp2m.cdas1.201809.grb2")
    lat=np.repeat(np.arange(90.,-90.1,-1.)[:,None],360,axis=1)
    lon=np.repeat(np.arange(0.,360.,1.)[None,:],181,axis=0)
    vals=np.full((181,360),273.15+12,dtype=np.float32)
    eu=ingest.interpolate_europe(vals,lat,lon)
    assert eu.shape==(76,140)
    assert np.allclose(eu,12,atol=.005)
