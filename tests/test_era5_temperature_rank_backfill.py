import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from era5_temperature_rank_backfill import (
    build_single_year_month_products,
    month_target_dates,
    rank_contribution,
)
from era5_temperature_rank_backfill_probe import resolve_available_through


def test_month_target_dates_january():
    dates = month_target_dates(2026, 1, 3)
    assert dates == ['2026-01-01', '2026-01-02', '2026-01-03']


def test_past_complete_month_uses_indexed_data_without_live_probe():
    def fail_probe():
        raise AssertionError('Live probe must not be called for an already covered month')

    available, used_live_probe = resolve_available_through(
        2026,
        6,
        30,
        date(2026, 9, 11),
        fail_probe,
    )
    assert available == date(2026, 9, 11)
    assert used_live_probe is False


def test_target_beyond_indexed_data_uses_live_probe():
    available, used_live_probe = resolve_available_through(
        2026,
        9,
        12,
        date(2026, 9, 11),
        lambda: date(2026, 9, 12),
    )
    assert available == date(2026, 9, 12)
    assert used_live_probe is True


def test_january_products_include_previous_december_for_winter():
    times = np.array(['2026-01-01', '2026-01-02', '2026-01-03'], dtype='datetime64[D]')
    cube = np.array([10.0, 14.0, 18.0]).reshape(3, 1, 1)
    previous_december = np.array([[[2.0]]])
    dates, products = build_single_year_month_products(
        times=times,
        cube=cube,
        year=2026,
        month=1,
        end_day=3,
        complete_month_fields={},
        previous_december=previous_december,
    )
    assert dates.tolist() == ['2026-01-01', '2026-01-02', '2026-01-03']
    np.testing.assert_allclose(products['day'][:, 0, 0], [10, 14, 18])
    np.testing.assert_allclose(products['month_to_date'][:, 0, 0], [10, 12, 14])
    np.testing.assert_allclose(products['year_to_date'][:, 0, 0], [10, 12, 14])
    expected_winter = [
        (2 * 31 + 10 * 1) / 32,
        (2 * 31 + 12 * 2) / 33,
        (2 * 31 + 14 * 3) / 34,
    ]
    np.testing.assert_allclose(products['season_to_date'][:, 0, 0], expected_winter)


def test_rank_contribution_uses_strictly_greater_for_warm_rank():
    current = {
        key: np.array([[[10.0]], [[20.0]]])
        for key in ('day', 'month_to_date', 'season_to_date', 'year_to_date')
    }
    history = {
        key: np.array([[[11.0]], [[20.0]]])
        for key in current
    }
    greater, valid = rank_contribution(current, history)
    assert greater.shape == (2, 4, 1, 1)
    assert valid.shape == (2, 4, 1, 1)
    assert np.all(greater[0] == 1)
    assert np.all(greater[1] == 0)
    assert np.all(valid == 1)
