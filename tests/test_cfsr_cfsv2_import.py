"""Historical CFSR/CFSv2 source selection and 0.5-degree Europe remapping."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pytest
from scripts import import_cfsr_cfsv2_1991_2020 as ingest
from scripts import build_gfs_cfsr_1991_2020 as reference


def test_official_ncei_url_and_real_april_2011_handover():
    assert ingest.product_for_month(2010, 12) == "CFSR"
    assert ingest.product_for_month(2011, 3) == "CFSR"
    assert ingest.product_for_month(2011, 4) == "CFSv2"
    assert ingest.product_for_month(2020, 12) == "CFSv2"
    assert ingest.source_url(1991, 1) == (
        "https://www.ncei.noaa.gov/thredds/fileServer/model-cfs_reanl_ts/"
        "199101/tmp2m.gdas.199101.grb2"
    )
    assert ingest.source_url(2011, 4) == (
        "https://www.ncei.noaa.gov/thredds/fileServer/model-cfs_v2_anl_ts/"
        "2011/201104/tmp2m.gdas.201104.grib2"
    )
    assert ingest.year_product(2011) == reference.expected_product(2011) == "CFSR+CFSv2"


def test_full_365_daily_calendar_and_leap_day_exclusion():
    for year in range(1991,2021):
        days=reference.expected_days(year)
        assert len(days)==365 and days[0]==f"{year}-01-01"
        assert days[-1]==f"{year}-12-31"
        assert f"{year}-02-29" not in days
        assert len(set(days))==365


def test_spatial_interpolation_preserves_constant_kelvin_field():
    lat=np.repeat(np.arange(90.,-90.1,-1.)[:,None],360,axis=1)
    lon=np.repeat(np.arange(0.,360.,1.)[None,:],181,axis=0)
    a=np.full((181,360),283.15,dtype=np.float32)
    sample=ingest.interpolate_europe(a,lat,lon)
    assert sample.shape==(76,140)
    assert np.allclose(sample,10.,atol=0.002)
    # North-west cell is 71.75N, -24.75E; south-east is 34.25N, 44.75E
    assert np.isclose(ingest.TARGET_LAT[0],71.75)
    assert np.isclose(ingest.TARGET_LAT[-1],34.25)
    assert np.isclose(ingest.TARGET_LON[0],335.25)
    assert np.isclose(ingest.TARGET_LON[-1],44.75)



def test_remapping_handles_reverse_latitude_and_minus180_to180_grid():
    lat=np.repeat(np.arange(-90.,90.1,1.)[:,None],360,axis=1)
    lon=np.repeat(np.arange(-180.,180.,1.)[None,:],181,axis=0)
    vals=np.full((181,360),278.15,dtype=np.float32)
    result=ingest.interpolate_europe(vals,lat,lon)
    assert result.shape==(76,140)
    assert np.allclose(result,5.,atol=0.002)

def test_interpolation_rejects_gaps_and_incorrect_grid():
    x=np.full((3,3),280,dtype=np.float32)
    with pytest.raises(ValueError,match="grid"):
        ingest.interpolate_europe(x,np.zeros_like(x),np.zeros_like(x))
    with pytest.raises(ValueError,match="grid"):
        ingest.interpolate_europe(np.full((4,4),280),np.zeros((3,3)),np.zeros((3,3)))


def test_missing_originals_never_generate_climatology(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        reference.make_normals(tmp_path)


def test_alternate_official_ncar_gdex_high_res_2m_sources_only():
    assert ingest.alternate_source_urls(1992,7) == [
        "https://tds.gdex.ucar.edu/thredds/fileServer/files/g/d093001/1992/"
        "tmp2m.gdas.199207.grb2"]
    assert ingest.alternate_source_urls(2018,9) == [
        "https://tds.gdex.ucar.edu/thredds/fileServer/files/g/d094001/2018/"
        "tmp2m.cdas1.201809.grb2"]
    assert ".l.gdas." not in ingest.alternate_source_urls(1992,7)[0]
    assert ".l.cdas1." not in ingest.alternate_source_urls(2018,9)[0]
