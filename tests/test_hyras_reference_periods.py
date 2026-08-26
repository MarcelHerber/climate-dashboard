from pathlib import Path

import scripts.build_hyras_temperature_live_reference as temp_ref
import scripts.update_hyras_maps as precip


def test_hyras_supports_both_climate_reference_periods():
    expected = ((1991, 2020), (1961, 1990))
    assert precip.REFERENCE_PERIODS == expected
    assert temp_ref.REFERENCE_PERIODS == expected
    assert precip.reference_label((1961, 1990)) == "1961-1990"
    assert temp_ref.reference_label((1961, 1990)) == "1961-1990"


def test_precip_climatology_lookup_accepts_1961_1990(monkeypatch):
    listing = (
        '<a href="pr_hyras_1_1961_1990_v6-0_de_AUG.nc">old</a>'
        '<a href="pr_hyras_1_1961_1990_v6-1_de_AUG.nc">new</a>'
        '<a href="pr_hyras_1_1991_2020_v6-1_de_AUG.nc">current</a>'
    )
    monkeypatch.setattr(precip, "directory_text", lambda _url: listing)
    assert precip.latest_clim_filename(8, reference=(1961, 1990)) == "pr_hyras_1_1961_1990_v6-1_de_AUG.nc"
    assert precip.latest_clim_filename(8, reference=(1991, 2020)) == "pr_hyras_1_1991_2020_v6-1_de_AUG.nc"


def test_temperature_climatology_lookup_accepts_1961_1990(monkeypatch):
    listing = (
        '<a href="tas_hyras_1_1961_1990_v6-0_de_AUG.nc">old</a>'
        '<a href="tas_hyras_1_1961_1990_v6-1_de_AUG.nc">new</a>'
        '<a href="tas_hyras_1_1991_2020_v6-1_de_AUG.nc">current</a>'
    )
    monkeypatch.setattr(temp_ref, "listing", lambda _url: listing)
    cfg = temp_ref.CFG["tmean"]
    assert temp_ref.latest_clim(cfg, 8, reference=(1961, 1990)) == "tas_hyras_1_1961_1990_v6-1_de_AUG.nc"
    assert temp_ref.latest_clim(cfg, 8, reference=(1991, 2020)) == "tas_hyras_1_1991_2020_v6-1_de_AUG.nc"


def test_reference_caches_are_isolated_by_period(tmp_path: Path):
    p_old = precip.daily_reference_cache_path(tmp_path, factor=2, reference=(1961, 1990))
    p_new = precip.daily_reference_cache_path(tmp_path, factor=2, reference=(1991, 2020))
    assert p_old.name == "hyras_daily_reference_1961_1990_web2_v1.npz"
    assert p_new.name == "hyras_daily_reference_1991_2020_web2_v1.npz"
    assert p_old != p_new

    t_old = temp_ref.cache_path(tmp_path, temp_ref.CFG["tmax"], 8, reference=(1961, 1990))
    t_new = temp_ref.cache_path(tmp_path, temp_ref.CFG["tmax"], 8, reference=(1991, 2020))
    assert t_old.name == "tmax_month_08_1961_1990.npz"
    assert t_new.name == "tmax_month_08_1991_2020.npz"
    assert t_old != t_new
