"""GFS f000 0.5-degree data integrity and 1991-2020 CFSR reference gates."""
from __future__ import annotations
from datetime import date
import json
from pathlib import Path
import sys
import types
import numpy as np
import pytest

from scripts import update_gfs_analysis_europe as gfs
from scripts import build_gfs_cfsr_1991_2020 as ref

ROOT=Path(__file__).resolve().parents[1]

def test_only_real_f000_nomads_analysis():
    url=gfs.analysis_url(date(2026,11,12),0)
    assert "gfs.t00z.pgrb2.0p50.f000" in url
    assert "var_TMP=on" in url and "lev_2_m_above_ground=on" in url
    assert "20261112" in url
    with pytest.raises(ValueError):
        gfs.analysis_url(date(2026,11,12),3)

def test_no_illusion_of_0p1_data_or_forecast():
    assert gfs.WIDTH==140 and gfs.HEIGHT==76
    assert gfs.CYCLES==(0,6,12,18)
    src=(ROOT/"scripts/update_gfs_analysis_europe.py").read_text(encoding="utf-8")
    assert '"forecast_hour": 0' in src
    assert "gfs_analysis_europe/climatology_1991_2020.npz" not in src or "CFSR" in src
    assert "f003" not in src and "open_meteo" not in src.lower()

def test_grib_analysis_validation_and_correct_grid_shift(monkeypatch):
    meta={
        "edition":2, "typeOfLevel":"heightAboveGround", "level":2,
        "forecastTime":0, "stepRange":"0", "dataDate":20261112,
        "dataTime":600, "Ni":720, "Nj":361,
        "latitudeOfFirstGridPointInDegrees":90.0
    }
    fake=types.SimpleNamespace(
        codes_grib_new_from_file=lambda f: object(),
        codes_get=lambda gid,key:meta[key],
        codes_get_values=lambda gid:np.full(720*361,280.15),
        codes_release=lambda gid:None
    )
    monkeypatch.setitem(sys.modules,"eccodes",fake)
    a=gfs.grib_2m_analysis(b"GRIB"+b"x"*300,date(2026,11,12),6)
    assert a.shape==(76,140)
    assert np.allclose(a,7.0,atol=0.01)
    meta["forecastTime"]=3
    with pytest.raises(ValueError,match="f000"):
        gfs.grib_2m_analysis(b"GRIB"+b"x"*300,date(2026,11,12),6)

def test_reference_days_and_leap_interpolation():
    normals=np.broadcast_to(np.arange(365,dtype=np.float32)[:,None,None],
                            (365,76,140))
    assert gfs.day_index(date(2024,2,29))==-1
    assert gfs.day_index(date(2024,3,1))==59
    assert gfs.normal_for_date(normals,date(2024,2,29))[0,0]==58.5
    assert len(ref.expected_days(1992))==365
    assert "1992-02-29" not in ref.expected_days(1992)

def test_binary_encoding_and_missing_values():
    a=np.array([np.nan,-8.25,0.,24.11,1000],dtype=float)
    b=gfs.decode_q10(gfs.encode_q10(a),(5,))
    assert np.isnan(b[0]) and np.isnan(b[4])
    assert b[1]==-8.2 or b[1]==-8.3
    assert b[2]==0 and b[3]==24.1

def test_no_unverified_cfsr_anomalies(tmp_path):
    z=np.full((76,140),12.0,dtype=np.float32)
    p=gfs.publish_index([(date(2026,11,12),z)],normal=None,
                        out=tmp_path/"index.json")
    assert p["reference_ready"] is False
    assert p["anomaly_q10_b64"] is None
    assert p["type"]=="model_analysis_not_observation"
    assert p["grid_degrees"]==0.5
    saved=json.loads((tmp_path/"index.json").read_text(encoding="utf-8"))
    assert saved["data_through"]=="2026-11-12"

def test_verified_baseline_changes_anomaly_only(tmp_path):
    z=np.full((76,140),12.0,dtype=np.float32)
    baseline=np.full((365,76,140),10.0,dtype=np.float32)
    p=gfs.publish_index([(date(2026,11,12),z)],normal=(baseline,{"years":30}),
                        out=tmp_path/"index.json")
    assert p["reference_ready"] is True
    values=gfs.decode_q10(p["anomaly_q10_b64"],(1,76,140))
    assert np.all(values==2)
    original=gfs.decode_q10(p["temperature_q10_b64"],(1,76,140))
    assert np.all(original==12)

def test_invalid_baseline_is_rejected(tmp_path):
    p=tmp_path/"invalid.npz"
    np.savez_compressed(p,normal_t2m_c=np.zeros((365,76,140),dtype=np.float32),
        year_count=np.full((365,76,140),30,dtype=np.int16),
        metadata_json=json.dumps({"source":"ERA5","first_year":1991}))
    with pytest.raises(ValueError,match="provenance"):
        gfs.read_normals(p)

def test_reference_builder_needs_all_30_years(tmp_path):
    with pytest.raises(FileNotFoundError,match="1991"):
        ref.make_normals(tmp_path)

def test_baseline_and_map_disclosure_and_pages():
    html=(ROOT/"gfs_analysis_europe.html").read_text(encoding="utf-8")
    js=(ROOT/"gfs_analysis_europe.js").read_text(encoding="utf-8")
    mobile=(ROOT/"mobile_navigation.js").read_text(encoding="utf-8")
    pages=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")
    assert "GFS" in html and "CFSR" in html and "1991–2020" in html
    assert "GFS-Analyse · CFSR" in mobile
    assert "gfs_analysis_europe.html" in pages and "gfs_analysis_europe.js" in pages
    assert "cpc_europe/index.json" in js
    assert "reference_ready" in js and 'value="anomaly"' in html
    cpc=(ROOT/"cpc_europe.js").read_text(encoding="utf-8")
    for color in ["#3A006F","#FDFCFC","#FDAFCB"]:
        assert color in js and color in cpc
