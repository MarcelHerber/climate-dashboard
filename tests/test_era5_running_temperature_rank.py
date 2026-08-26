import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from era5_running_temperature_rank import (
    PRODUCTS,
    historical_years,
    extract_day_and_mtd,
    combine_summer_to_date,
    daily_request_year_groups,
    product_filename,
)


def test_historical_universe_is_1950_through_2025():
    years = historical_years()
    assert years[0] == 1950
    assert years[-1] == 2025
    assert len(years) == 76


def test_exactly_three_running_products():
    assert PRODUCTS == ('day', 'month_to_date', 'summer_to_date')
    assert [product_filename(p) for p in PRODUCTS] == [
        'temperature_day_rank.png',
        'temperature_month_to_date_rank.png',
        'temperature_summer_to_date_rank.png',
    ]


def test_daily_requests_are_split_to_one_year_to_stay_below_cds_cost_limit():
    assert daily_request_year_groups([1950, 1951, 1952]) == ((1950,), (1951,), (1952,))


def test_extract_day_and_month_to_date():
    times = np.array(['2020-08-01', '2020-08-02', '2020-08-03'], dtype='datetime64[D]')
    cube = np.array([[[10.0]], [[14.0]], [[20.0]]])
    day, mtd = extract_day_and_mtd(times, cube, target_day=3)
    assert day[0, 0] == 20.0
    assert mtd[0, 0] == 44.0 / 3.0


def test_summer_to_date_august_weighting():
    years = np.array([2020, 2021])
    june = np.array([[[10.0]], [[20.0]]])
    july = np.array([[[20.0]], [[30.0]]])
    aug_mtd = np.array([[[30.0]], [[40.0]]])
    result = combine_summer_to_date({6: june, 7: july}, years, 8, 10, aug_mtd)
    assert np.isclose(result[0, 0, 0], (10*30 + 20*31 + 30*10) / 71)
    assert np.isclose(result[1, 0, 0], (20*30 + 30*31 + 40*10) / 71)


def test_summer_to_date_june_is_month_to_date():
    years = np.array([2020, 2021])
    mtd = np.array([[[11.0]], [[22.0]]])
    result = combine_summer_to_date({}, years, 6, 15, mtd)
    assert np.array_equal(result, mtd)


def test_76_historical_years_plus_current_give_rank_1_through_77():
    from era5_temperature_rank import temperature_rank_field
    history = np.arange(76, dtype=float).reshape(76, 1, 1)
    assert temperature_rank_field(np.array([[100.0]]), history)[0, 0] == 1.0
    assert temperature_rank_field(np.array([[-1.0]]), history)[0, 0] == 77.0


def test_extract_year_day_mtd_splits_one_multiyear_daily_cube():
    from era5_running_temperature_rank import extract_year_day_mtd
    times = np.array([
        '2020-08-01','2020-08-02','2020-08-03',
        '2021-08-01','2021-08-02','2021-08-03',
    ], dtype='datetime64[D]')
    cube = np.array([10,14,20,30,34,40], dtype=float).reshape(6,1,1)
    day, mtd = extract_year_day_mtd(times, cube, np.array([2020,2021]), 3)
    np.testing.assert_allclose(day[:,0,0], [20,40])
    np.testing.assert_allclose(mtd[:,0,0], [44/3,104/3])
