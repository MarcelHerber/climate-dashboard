import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from era5_running_temperature_rank import (
    PRODUCTS,
    historical_years,
    products_for_month,
    season_for_month,
    extract_day_and_mtd,
    extract_year_day_mtd,
    combine_year_to_date,
    combine_season_to_date,
    combine_summer_to_date,
    daily_request_year_groups,
    product_filename,
)


def test_historical_universe_tracks_current_year():
    years = historical_years(2026)
    assert years[0] == 1950
    assert years[-1] == 2025
    assert len(years) == 76
    years_2027 = historical_years(2027)
    assert years_2027[-1] == 2026
    assert len(years_2027) == 77


def test_four_year_round_products():
    assert PRODUCTS == ('day', 'month_to_date', 'season_to_date', 'year_to_date')
    assert products_for_month(1) == PRODUCTS
    assert products_for_month(6) == PRODUCTS
    assert products_for_month(9) == PRODUCTS
    assert [product_filename(p) for p in PRODUCTS] == [
        'temperature_day_rank.png',
        'temperature_month_to_date_rank.png',
        'temperature_season_to_date_rank.png',
        'temperature_year_to_date_rank.png',
    ]


def test_seasons_follow_meteorological_calendar():
    assert season_for_month(3) == ('spring', 'Frühling', 3)
    assert season_for_month(6) == ('summer', 'Sommer', 6)
    assert season_for_month(9) == ('autumn', 'Herbst', 9)
    assert season_for_month(12) == ('winter', 'Winter', 12)
    assert season_for_month(1) == ('winter', 'Winter', 12)
    assert season_for_month(2) == ('winter', 'Winter', 12)


def test_daily_requests_are_split_to_one_year_to_stay_below_cds_cost_limit():
    assert daily_request_year_groups([1950, 1951, 1952]) == ((1950,), (1951,), (1952,))


def test_extract_day_and_month_to_date():
    times = np.array(['2020-08-01', '2020-08-02', '2020-08-03'], dtype='datetime64[D]')
    cube = np.array([[[10.0]], [[14.0]], [[20.0]]])
    day, mtd = extract_day_and_mtd(times, cube, target_day=3)
    assert day[0, 0] == 20.0
    assert mtd[0, 0] == 44.0 / 3.0


def test_year_to_date_september_weighting_including_leap_year():
    years = np.array([2020, 2021])
    complete = {month: np.array([[[float(month)]], [[float(month + 10)]]]) for month in range(1, 9)}
    sep_mtd = np.array([[[9.0]], [[19.0]]])
    result = combine_year_to_date(complete, years, 9, 10, sep_mtd)
    weights_2020 = [31, 29, 31, 30, 31, 30, 31, 31]
    weights_2021 = [31, 28, 31, 30, 31, 30, 31, 31]
    expected_2020 = (sum(month * days for month, days in zip(range(1, 9), weights_2020)) + 9 * 10) / (sum(weights_2020) + 10)
    expected_2021 = (sum((month + 10) * days for month, days in zip(range(1, 9), weights_2021)) + 19 * 10) / (sum(weights_2021) + 10)
    assert np.isclose(result[0, 0, 0], expected_2020)
    assert np.isclose(result[1, 0, 0], expected_2021)


def test_summer_season_to_date_august_weighting():
    years = np.array([2020, 2021])
    june = np.array([[[10.0]], [[20.0]]])
    july = np.array([[[20.0]], [[30.0]]])
    aug_mtd = np.array([[[30.0]], [[40.0]]])
    result = combine_season_to_date({6: june, 7: july}, years, 8, 10, aug_mtd)
    assert np.isclose(result[0, 0, 0], (10*30 + 20*31 + 30*10) / 71)
    assert np.isclose(result[1, 0, 0], (20*30 + 30*31 + 40*10) / 71)


def test_autumn_season_to_date_october_weighting():
    years = np.array([2020])
    september = np.array([[[10.0]]])
    october_mtd = np.array([[[20.0]]])
    result = combine_season_to_date({9: september}, years, 10, 15, october_mtd)
    assert np.isclose(result[0, 0, 0], (10*30 + 20*15) / 45)


def test_winter_january_includes_previous_december():
    years = np.array([2020, 2021])
    previous_december = np.array([[[5.0]], [[15.0]]])
    january_mtd = np.array([[[10.0]], [[20.0]]])
    result = combine_season_to_date(
        {},
        years,
        1,
        10,
        january_mtd,
        previous_december=previous_december,
    )
    assert np.isclose(result[0, 0, 0], (5*31 + 10*10) / 41)
    assert np.isclose(result[1, 0, 0], (15*31 + 20*10) / 41)


def test_first_winter_is_missing_without_december_1949():
    years = np.array([1950, 1951])
    previous_december = np.array([[[np.nan]], [[10.0]]])
    january_mtd = np.array([[[5.0]], [[20.0]]])
    result = combine_season_to_date(
        {},
        years,
        1,
        10,
        january_mtd,
        previous_december=previous_december,
    )
    assert np.isnan(result[0, 0, 0])
    assert np.isclose(result[1, 0, 0], (10*31 + 20*10) / 41)


def test_summer_compatibility_helper_still_matches():
    years = np.array([2020])
    june = np.array([[[10.0]]])
    july_mtd = np.array([[[20.0]]])
    season = combine_season_to_date({6: june}, years, 7, 10, july_mtd)
    legacy = combine_summer_to_date({6: june}, years, 7, 10, july_mtd)
    np.testing.assert_allclose(season, legacy)


def test_february_29_day_can_be_missing_in_non_leap_history():
    times = np.array([
        '2020-02-28','2020-02-29',
        '2021-02-27','2021-02-28',
    ], dtype='datetime64[D]')
    cube = np.array([10,12,20,22], dtype=float).reshape(4,1,1)
    day, mtd = extract_year_day_mtd(times, cube, np.array([2020,2021]), 29)
    assert day[0,0,0] == 12
    assert np.isnan(day[1,0,0])
    assert mtd[0,0,0] == 11
    assert mtd[1,0,0] == 21


def test_rank_range_with_76_historical_years():
    from era5_temperature_rank import temperature_rank_field
    history = np.arange(76, dtype=float).reshape(76, 1, 1)
    assert temperature_rank_field(np.array([[100.0]]), history)[0, 0] == 1.0
    assert temperature_rank_field(np.array([[-1.0]]), history)[0, 0] == 77.0
