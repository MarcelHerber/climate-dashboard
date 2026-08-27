import numpy as np

from scripts.build_hyras_historical_period_archive import (
    MISSING_I16,
    PERIOD_KEYS,
    RESOLUTION_KM,
    mean_packed,
    period_meta,
)


def test_native_one_kilometre():
    assert RESOLUTION_KM == 1


def test_period_keys_are_12_months_4_seasons_and_year():
    assert PERIOD_KEYS[:12] == tuple(f"month_{m:02d}" for m in range(1, 13))
    assert PERIOD_KEYS[12:] == ("spring", "summer", "autumn", "winter", "year")
    assert len(PERIOD_KEYS) == 17


def test_mean_packed_weights_days_not_months():
    jan = (np.array([[3100]], dtype=np.int64), np.array([[31]], dtype=np.uint16))
    feb = (np.array([[5600]], dtype=np.int64), np.array([[28]], dtype=np.uint16))
    out = mean_packed([jan, feb])
    assert out[0, 0] == round((3100 + 5600) / 59)


def test_mean_packed_keeps_missing():
    a = (np.array([[0]], dtype=np.int64), np.array([[0]], dtype=np.uint16))
    assert mean_packed([a])[0, 0] == MISSING_I16


def test_winter_ends_in_selected_year():
    meta = period_meta(1952, "winter", True)
    assert meta["label"] == "Winter 1951/52"
    assert meta["start_date"] == "1951-12-01"
    assert meta["end_date"] == "1952-02-29"
