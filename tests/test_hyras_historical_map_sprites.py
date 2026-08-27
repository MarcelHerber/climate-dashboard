import numpy as np

from scripts.build_hyras_historical_map_sprites import (
    COLS,
    PERIOD_KEYS,
    ROWS,
    anomaly_mean_c,
    mean_c,
)


def test_sprite_grid_has_room_for_all_periods():
    assert len(PERIOD_KEYS) == 17
    assert COLS * ROWS >= len(PERIOD_KEYS)
    assert (COLS, ROWS) == (5, 4)


def test_period_order_is_stable():
    assert PERIOD_KEYS[:3] == ("month_01", "month_02", "month_03")
    assert PERIOD_KEYS[-5:] == ("spring", "summer", "autumn", "winter", "year")


def test_means_ignore_missing():
    q = np.array([[100, 300], [-32768, 500]], dtype=np.int16)
    assert mean_c(q) == 3.0


def test_anomaly_mean_uses_common_valid_mask():
    q = np.array([[100, 300], [-32768, 500]], dtype=np.int16)
    r = np.array([[50, 250], [100, -32768]], dtype=np.int16)
    assert anomaly_mean_c(q, r) == 0.5
