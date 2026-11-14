"""Real-data contract for the independent seven-day GFS/CFSR 1991–2020 map."""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
import numpy as np
import pytest
import sys
import types
from scripts import update_gfs_weekly_europe as wk

RUN=datetime(2026,11,14,0,tzinfo=timezone.utc)

def test_28_six_hour_steps_7_days_not_one_day():
    assert len(wk.LEADS)==28
    assert wk.LEADS==tuple(range(3,166,6))
    assert (RUN+timedelta(hours=wk.LEADS[0])).hour==3
    assert (RUN+timedelta(hours=wk.LEADS[-1])).date()==date(2026,11,20)
    assert not any(v%6==0 for v in wk.LEADS)

def test_real_official_gfs_paths_and_idx_filter():
    u=wk.source_url(RUN,165,"s3")
    assert u.endswith("gfs.20261114/00/atmos/gfs.t00z.pgrb2.0p50.f165")
    with pytest.raises(ValueError):
        wk.source_url(RUN,0,"s3")
    idx=("1:100:d=2026111400:TMP:2 m above ground:165 hour fcst:\n"
         "2:300100:d=2026111400:RH:2 m above ground:165 hour fcst:\n")
    assert wk.field_range(idx,RUN,165)==(100,300099)
    with pytest.raises(ValueError,match="No unique"):
        wk.field_range(idx,RUN,3)

def test_historical_1991_2020_baseline_used_on_valid_dates(monkeypatch):
    baseline=np.zeros((365,76,140),dtype=np.float32)
    # A distinct normal per valid date: prove we aren't subtracting the run date 28 times.
    reference_days={date(2026,11,14)+timedelta(days=n) for n in range(7)}
    for d in reference_days:
        baseline[wk.daily.day_index(d)]=np.float32(d.day)
    fields=[np.full((76,140),float((RUN+timedelta(hours=h)).day+2),dtype=np.float32)
            for h in wk.LEADS]
    result=wk.calculate(RUN,fields,baseline)
    anomaly=wk.daily.decode_q10(result["anomaly_mean_q10_b64"],(76,140))
    assert np.allclose(anomaly,2)
    assert result["sample_count"]==28 and result["period_days"]==7
    assert result["valid_from_utc"]=="2026-11-14T03:00:00Z"
    assert result["valid_to_utc"]=="2026-11-20T21:00:00Z"

def test_refuse_partial_forecasts_and_wrong_grids():
    base=np.zeros((365,76,140),dtype=np.float32)
    fields=[np.ones((76,140),dtype=np.float32) for _ in wk.LEADS]
    with pytest.raises(ValueError):
        wk.calculate(RUN,fields[:-1],base)
    fields[-1][0,0]=np.nan
    with pytest.raises(ValueError):
        wk.calculate(RUN,fields,base)

def test_valid_run_cycles_and_recent_candidates():
    now=datetime(2026,11,14,10,tzinfo=timezone.utc)
    c=wk.run_candidates(now)
    assert c[0]==RUN and len(c)==3 and c[1] < c[0]
    assert wk.run_candidates(now,cycle=6,day=date(2026,11,13))==[
        datetime(2026,11,13,6,tzinfo=timezone.utc)]
    with pytest.raises(ValueError):
        wk.run_candidates(now,cycle=3,day=date(2026,11,13))

def test_actual_grib_metadata_includes_correct_future_validity(monkeypatch):
    meta={
        "edition":2,"discipline":0,"parameterCategory":0,"parameterNumber":0,
        "typeOfLevel":"heightAboveGround","level":2,"forecastTime":165,
        "stepRange":"165","dataDate":20261114,"dataTime":0,
        "validityDate":20261120,"validityTime":2100,
        "Ni":720,"Nj":361,"latitudeOfFirstGridPointInDegrees":90.
    }
    fake=types.SimpleNamespace(
        codes_grib_new_from_file=lambda f:object(),
        codes_get=lambda gid,key:meta[key],
        codes_get_values=lambda gid:np.full(720*361,280.15),
        codes_release=lambda gid:None
    )
    monkeypatch.setitem(sys.modules,"eccodes",fake)
    a=wk.decode_grib(b"GRIB"+b"x"*30000,RUN,165)
    assert a.shape==(76,140) and np.allclose(a,7,atol=.01)
    meta["forecastTime"]=162
    with pytest.raises(ValueError,match="provenance"):
        wk.decode_grib(b"GRIB"+b"x"*30000,RUN,165)
    meta["forecastTime"]=165
    meta["validityDate"]=20261119
    with pytest.raises(ValueError,match="provenance"):
        wk.decode_grib(b"GRIB"+b"x"*30000,RUN,165)
