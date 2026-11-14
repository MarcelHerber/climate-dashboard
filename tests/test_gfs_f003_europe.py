"""True model +3h temperature against homogeneous CFSR/CFSv2 f003 normals."""
from datetime import date
import json
import numpy as np
import pytest
import sys
import types
from scripts import update_gfs_f003_europe as gfs

def test_official_0p50_gfs_f003_only():
    d=date(2026,11,12)
    assert "f003" in gfs.object_url(d,6,host="s3")
    assert "0p50.f003" in gfs.analysis_url(d,6)
    assert "f000" not in gfs.object_url(d,6,host="s3")
    assert gfs.BASELINE.name=="climatology_1991_2020_f003.npz"
    assert gfs.RAW.name=="f003_daily"

def test_grib_field_valid_at_cycle_plus_three(monkeypatch):
    meta={
        "edition":2,"typeOfLevel":"heightAboveGround","level":2,
        "forecastTime":3,"stepRange":"3","dataDate":20261112,
        "dataTime":600,"validityDate":20261112,"validityTime":900,
        "Ni":720,"Nj":361,"latitudeOfFirstGridPointInDegrees":90.0
    }
    fake=types.SimpleNamespace(
        codes_grib_new_from_file=lambda f:object(),
        codes_get=lambda gid,key:meta[key],
        codes_get_values=lambda gid:np.full(720*361,285.15),
        codes_release=lambda gid:None
    )
    monkeypatch.setitem(sys.modules,"eccodes",fake)
    field=gfs.grib_2m_analysis(b"GRIB"+b"x"*300,date(2026,11,12),6)
    assert field.shape==(76,140) and np.allclose(field,12,atol=.01)
    meta["forecastTime"]=0
    with pytest.raises(ValueError,match="f003"):
        gfs.grib_2m_analysis(b"GRIB"+b"x"*300,date(2026,11,12),6)
    meta["forecastTime"]=3
    meta["validityTime"]=600
    with pytest.raises(ValueError,match="initialization"):
        gfs.grib_2m_analysis(b"GRIB"+b"x"*300,date(2026,11,12),6)

def test_reference_is_f003_only(tmp_path):
    p=tmp_path/"normal.npz"
    meta={
        "source":"CFSR 1991-03/2011 + CFSv2 04/2011-2020 (T2M f003)",
        "first_year":1991,"last_year":2020,"years":30,
        "sample_hours_utc":[3,9,15,21],"forecast_hour":3,
        "reference_version":"cfsr-cfsv2-t2m-f003-v1",
        "grid":"CPC-aligned GFS 0.5 degree Europe",
        "reference":"1991-2020","source_months":360
    }
    vals=np.full((365,76,140),10,dtype=np.float32)
    counts=np.full(vals.shape,30,dtype=np.int16)
    np.savez_compressed(p,normal_t2m_c=vals,year_count=counts,
                        metadata_json=json.dumps(meta))
    assert gfs.read_normals(p)[1]["forecast_hour"]==3
    meta["forecast_hour"]=0
    np.savez_compressed(p,normal_t2m_c=vals,year_count=counts,
                        metadata_json=json.dumps(meta))
    with pytest.raises(ValueError,match="provenance"):
        gfs.read_normals(p)

def test_true_f003_anomaly_calculation_and_gating(tmp_path):
    d=date(2026,11,12)
    arr=np.full((76,140),12,dtype=np.float32)
    no=gfs.publish_index([(d,arr)],normal=None,out=tmp_path/"no.json")
    assert no["reference_ready"] is False and no["anomaly_q10_b64"] is None
    ref=np.full((365,76,140),10,dtype=np.float32)
    result=gfs.publish_index([(d,arr)],normal=(ref,{"forecast_hour":3}),
                             out=tmp_path/"yes.json")
    assert result["reference_ready"] is True
    assert "f003" in result["provider"]
    assert result["type"]=="model_forecast_not_observation"
    v=gfs.decode_q10(result["anomaly_q10_b64"],(1,76,140))
    assert np.all(v==2)
