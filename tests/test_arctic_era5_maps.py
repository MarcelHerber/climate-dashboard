"""Offline scientific-contract tests for ERA5 Arctic map acquisition and export."""
from __future__ import annotations
import importlib.util
from datetime import date
from pathlib import Path
import json
import sys
import numpy as np
import pytest
import xarray as xr

P=Path(__file__).resolve().parents[1]/"scripts"/"build_arctic_era5_maps.py"
spec=importlib.util.spec_from_file_location("arctic_era5_maps",P)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)


def fake_field(day="2026-10-31",years=None):
    lats=np.arange(90,79.9,-.5)
    lons=np.arange(0,360,.5)
    dates=np.array([np.datetime64(str(y)+"-10-01") for y in years] if years
                   else [np.datetime64(day)])
    # Offline fixture only. Must never be written to published directory.
    field=np.full((len(dates),len(lats),len(lons)),258.0)
    return xr.DataArray(field,dims=("time","latitude","longitude"),
                        coords={"time":dates,"latitude":lats,"longitude":lons},
                        name="t2m")


def test_daily_request_has_correct_area_time_and_daily_aggregation():
    req=m.daily_request(date(2026,10,31))
    assert req["area"]==[90,-180,80,180]
    assert req["daily_statistic"]=="daily_mean"
    assert req["frequency"]=="1_hourly"
    assert req["time_zone"]=="utc+00:00"
    assert req["grid"]=="0.5/0.5"
    assert req["variable"]==["2m_temperature"]


def test_baseline_uses_all_30_climate_years():
    req=m.monthly_request(10)
    assert req["year"]==list(map(str,range(1991,2021)))
    assert req["month"]==["10"]
    assert req["product_type"]=="monthly_averaged_reanalysis"


def test_grids_normalize_and_dates_checked():
    da=fake_field()
    lat,lon,kelvin=m.validate_daily(da,date(2026,10,31))
    assert kelvin.shape==(21,720)
    assert lat[0]==80 and lat[-1]==90
    assert lon[0]==-180 and lon[-1]==179.5
    with pytest.raises(ValueError,match="timestamp"):
        m.validate_daily(da,date(2026,10,30))


def test_monthly_ref_rejects_incomplete_1991_2020():
    d=fake_field(years=list(range(1991,2021)))
    lat,lon,average=m.validate_monthly(d,10)
    assert average.shape==(21,720)
    assert np.isclose(average.mean(),258)
    with pytest.raises(ValueError,match="incomplete"):
        m.validate_monthly(fake_field(years=list(range(1992,2021))),10)


def test_area_weighted_mean_not_unweighted_dmi_index():
    lats=np.array([80.,85.,90.])
    vals=np.array([[0.,0.],[10.,10.],[20.,20.]])
    avg=m.cap_mean(vals,lats)
    assert 0<avg<10


def test_reject_malformed_data():
    d=fake_field()
    d.values[0,0,0]=np.nan
    with pytest.raises(ValueError,match="implausible"):
        m.validate_daily(d,date(2026,10,31))


def test_manifest_never_accepts_missing_maps(tmp_path):
    payload={"schema":1,"ready":True,"reference_period":"1991-2020",
        "latest_date":"2026-10-31",
        "days":[{"date":"2026-10-31",
                 "boundary_version":m.BOUNDARY_VERSION,
                 "temperature_png":"maps/t2m_20261031.png",
                 "anomaly_png":"maps/anomaly_20261031.png",
                 "mean_c":-11.5,"mean_anomaly_k":4.3}]}
    with pytest.raises(ValueError,match="invalid ERA5 PNG"):
        m.validate_manifest(payload,tmp_path)
    payload["days"][0]["temperature_png"]="../outside.png"
    with pytest.raises(ValueError,match="Unsafe"):
        m.validate_manifest(payload,tmp_path)


def test_no_fabricated_data_from_failed_cds(tmp_path):
    class FailClient:
        def retrieve(self,*args,**kwargs):
            raise RuntimeError("CDS source unavailable")
    with pytest.raises(RuntimeError,match="No real ERA5"):
        m.build(output=tmp_path,today=date(2026,11,8),client=FailClient(),max_new_days=1)
    assert not (tmp_path/"index.json").exists()


def test_offline_synthetic_plot_only_to_temporary_test_folder(tmp_path):
    lats=np.arange(80,90.1,.5)
    lons=np.arange(-180,180,.5)
    synthetic=np.full((len(lats),len(lons)),-15.0)
    path=tmp_path/"synthetic-not-for-publication.png"
    m.render_map(lats,lons,synthetic,date(2026,10,31),"temperature",path,-15.0)
    assert m.valid_image(path)
    assert path.stat().st_size>25000


def test_verified_polar_coastlines_are_downloaded_and_not_silently_omitted():
    coast, borders = m.load_polar_boundaries()
    assert len(coast) >= 5, "High-Arctic shoreline geometries missing"
    assert m.BOUNDARY_VERSION == 2
    # No imaginary country border is required where no real border exists
    # between 80 and 90 degrees north.
    assert isinstance(borders, list)


def test_map_rendering_fails_closed_if_boundary_layer_is_unavailable(tmp_path,monkeypatch):
    def unavailable():
        raise RuntimeError("No verified Natural Earth coastlines")
    monkeypatch.setattr(m,"load_polar_boundaries",unavailable)
    lat=np.arange(80,90.1,.5)
    lon=np.arange(-180,180,.5)
    out=tmp_path/"must-not-publish-borderless.png"
    with pytest.raises(RuntimeError,match="coastlines"):
        m.render_map(lat,lon,np.full((len(lat),len(lon)),-15.0),
                     date(2026,10,31),"temperature",out,-15.)
    assert not out.exists()
