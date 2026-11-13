"""Unit and regression checks for the observation-only NOAA CPC Europe module."""
from datetime import date, datetime, timedelta
from pathlib import Path
import base64

import numpy as np
import xarray as xr

from scripts.update_cpc_europe import (
    day_number, daily_reference, encode_q10, grid_bounds,
    actual_dates, FILL, SOURCE, REFERENCE_MIN_YEARS,
)

ROOT = Path(__file__).resolve().parents[1]

def test_daily_normal_has_unshifted_365_day_calendar():
    assert day_number(date(2026,1,1)) == 0
    assert day_number(date(2026,2,28)) == 58
    assert day_number(date(2026,3,1)) == 59
    assert day_number(date(2024,3,1)) == 59
    assert day_number(date(2026,12,31)) == 364

def test_leap_day_reference_is_interpolated_not_shifted():
    normals=np.arange(365,dtype=float)[:,None,None]
    assert daily_reference(normals,date(2024,2,28))[0,0]==58
    assert daily_reference(normals,date(2024,2,29))[0,0]==58.5
    assert daily_reference(normals,date(2024,3,1))[0,0]==59

def test_quantization_preserves_missing_and_sign():
    a=np.array([np.nan,-8.45,-0.5,0,1.35,9.9],dtype=float)
    encoded=encode_q10(a)
    arr=np.frombuffer(base64.b64decode(encoded),dtype="<i2")
    assert arr.tolist()==[FILL,-84,-5,0,14,99] or arr.tolist()==[FILL,-85,-5,0,14,99]
    assert np.isnan(a[0])

def test_noaa_grids_cover_west_and_east_europe():
    ds=xr.Dataset(coords={
        "lat":np.arange(89.75,-90.0,-0.5),
        "lon":np.arange(0.25,360.0,0.5)
    })
    ys,west,east=grid_bounds(ds)
    lat=ds.lat.values[ys]
    lons=np.concatenate([ds.lon.values[west]-360,ds.lon.values[east]])
    assert len(lat)==76 and len(lons)==140
    assert np.isclose(lons[0],-24.75)
    assert np.isclose(lons[-1],44.75)
    assert np.isclose(lat[0],71.75)
    assert np.isclose(lat[-1],34.25)

def test_time_decoding_and_climate_source():
    t=(datetime(2026,11,10)-datetime(1900,1,1)).total_seconds()/3600
    assert actual_dates(np.array([t]))==[date(2026,11,10)]
    assert SOURCE.startswith("https://psl.noaa.gov/thredds/dodsC/")
    assert REFERENCE_MIN_YEARS >= 10

def test_same_era5_anomaly_palette():
    from scripts.update_era5_land_europe_palette import TEMP_ANOMALY_LEVELS,TEMP_ANOMALY_COLORS
    js=(ROOT/"cpc_europe.js").read_text(encoding="utf-8")
    for c in TEMP_ANOMALY_COLORS:
        assert c in js
    assert len(TEMP_ANOMALY_COLORS)==len(TEMP_ANOMALY_LEVELS)==19

def test_real_dataset_and_clear_observation_disclosure():
    html=(ROOT/"temperatur_anomalie_europa.html").read_text(encoding="utf-8")
    source=(ROOT/"scripts/update_cpc_europe.py").read_text(encoding="utf-8")
    assert "keine Wettermodell" not in html.lower() or "Wettermodell" in html
    assert "kein 24-Stunden-Tagesmittel" in html
    assert "1991–2020" in html and "NOAA" in html
    assert "tmax.day.ltm.1991-2020.nc" in source
    assert "tmin.day.ltm.1991-2020.nc" in source
    assert "ECMWF" not in source and "GFS" not in source

def test_pages_publication_and_mobile_navigation_are_wired():
    build=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")
    mobile=(ROOT/"mobile_navigation.js").read_text(encoding="utf-8")
    assert "temperatur_anomalie_europa.html" in build
    assert "cpc_europe/index.json" in build
    assert "Aktuelle Temperaturabweichung · NOAA CPC" in mobile
