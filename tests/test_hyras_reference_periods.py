from pathlib import Path

import scripts.build_hyras_reference_1961_1990 as refs


def test_hyras_supports_both_climate_reference_periods():
    expected = ((1991, 2020), (1961, 1990))
    assert refs.REFERENCE_PERIODS == expected
    assert refs.DEFAULT_REFERENCE == (1991, 2020)
    assert refs.TARGET_REFERENCE == (1961, 1990)
    assert refs.reference_label((1961, 1990)) == "1961-1990"
    assert refs.reference_slug((1961, 1990)) == "1961_1990"


def test_temperature_climatology_lookup_accepts_1961_1990(monkeypatch):
    listing = (
        '<a href="tas_hyras_1_1961_1990_v6-0_de_AUG.nc">old</a>'
        '<a href="tas_hyras_1_1961_1990_v6-1_de_AUG.nc">new</a>'
        '<a href="tas_hyras_1_1991_2020_v6-1_de_AUG.nc">current</a>'
    )
    monkeypatch.setattr(refs.temp, "listing", lambda _url: listing)
    cfg = refs.temp.CFG["tmean"]
    assert refs.latest_temperature_clim(cfg, 8, (1961, 1990)) == "tas_hyras_1_1961_1990_v6-1_de_AUG.nc"
    assert refs.latest_temperature_clim(cfg, 8, (1991, 2020)) == "tas_hyras_1_1991_2020_v6-1_de_AUG.nc"


def test_reference_caches_are_isolated_by_period(tmp_path: Path):
    p_old = refs.daily_reference_cache_path(tmp_path, factor=2, reference=(1961, 1990))
    p_new = refs.daily_reference_cache_path(tmp_path, factor=2, reference=(1991, 2020))
    assert p_old.name == "hyras_daily_reference_1961_1990_web2_v1.npz"
    assert p_new.name == "hyras_daily_reference_1991_2020_web2_v1.npz"
    assert p_old != p_new

    t_old = refs.temperature_cache_path(tmp_path, refs.temp.CFG["tmax"], 8, (1961, 1990))
    t_new = refs.temperature_cache_path(tmp_path, refs.temp.CFG["tmax"], 8, (1991, 2020))
    assert t_old.name == "tmax_month_08_1961_1990.npz"
    assert t_new.name == "tmax_month_08_1991_2020.npz"
    assert t_old != t_new


def test_month_segments_keep_full_and_partial_months_separate():
    assert refs._month_segments("2026-06-01", "2026-08-23") == [
        (2026, 6, 1, 30),
        (2026, 7, 1, 31),
        (2026, 8, 1, 23),
    ]
